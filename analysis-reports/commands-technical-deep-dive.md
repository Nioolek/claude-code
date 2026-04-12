# Claude Code 命令技术原理深度分析

*文档生成时间：2026-04-06*  
*代码版本：G:\code\claude-code*

---

## 目录

1. [命令系统架构](#1-命令系统架构)
2. [命令类型详解](#2-命令类型详解)
3. [核心命令技术原理](#3-核心命令技术原理)
4. [配置类命令](#4-配置类命令)
5. [工具与集成类命令](#5-工具与集成类命令)
6. [代码审查类命令](#6-代码审查类命令)
7. [诊断与维护类命令](#7-诊断与维护类命令)
8. [条件启用命令](#8-条件启用命令)
9. [命令扩展机制](#9-命令扩展机制)

---

## 1. 命令系统架构

### 1.1 命令注册中心

所有命令在 `src/commands.ts` 中统一注册，采用**懒加载**设计模式：

```typescript
const COMMANDS = memoize((): Command[] => [
  addDir,
  advisor,
  agents,
  branch,
  btw,
  // ... 约 92 个命令
  ...(process.env.USER_TYPE === 'ant' && !process.env.IS_DEMO
    ? INTERNAL_ONLY_COMMANDS
    : []),
])
```

**关键设计决策：**

| 设计点 | 实现方式 | 优势 |
|--------|----------|------|
| **懒加载** | `load: () => import('./xxx.js')` | 减少启动时间，按需加载 |
| **memoize 缓存** | 避免重复构建命令数组 | 提升性能 |
| **条件渲染** | 特性标志控制命令可见性 | 支持 A/B 测试和灰度发布 |
| **类型安全** | TypeScript 接口约束 | 编译期错误检测 |

### 1.2 命令接口定义

```typescript
// src/types/command.ts
interface Command {
  name: string                              // 命令名称
  description?: string                      // 命令描述
  type: 'local' | 'local-jsx' | 'prompt'   // 命令类型
  aliases?: string[]                        // 别名列表
  argumentHint?: string                     // 参数提示
  isEnabled?: () => boolean                // 启用条件
  isHidden?: boolean                       // 是否隐藏
  supportsNonInteractive?: boolean         // 是否支持非交互模式
  immediate?: boolean                      // 是否立即执行
  load: () => Promise<any>                 // 懒加载函数
  getPromptForCommand?: (...) => Promise<...> // prompt 类型专用
}
```

### 1.3 命令执行流程

```
用户输入 /command
       ↓
命令解析器 (src/commands.ts)
       ↓
类型判断
   ┌───┼───┐
   ↓   ↓   ↓
 local  local-jsx  prompt
   ↓   ↓   ↓
执行 JS  渲染 JSX  生成 Prompt
   ↓   ↓   ↓
返回结果  用户交互  发送给 LLM
```

---

## 2. 命令类型详解

### 2.1 `local` 类型命令

**特点：** 纯 JavaScript 逻辑执行，无 UI 交互

**执行流程：**
```typescript
export const call: LocalCommandCall = async (_, context) => {
  // 1. 访问 context 获取状态
  const { messages, abortController } = context
  
  // 2. 执行逻辑
  await doSomething()
  
  // 3. 返回结果
  return { type: 'text', value: '结果' }
}
```

**典型命令：** `/compact`, `/clear`, `/advisor`, `/files`

### 2.2 `local-jsx` 类型命令

**特点：** 使用 React 组件渲染交互式 UI

**执行流程：**
```typescript
export const call: LocalJSXCommandCall = async (onDone, context) => {
  return <SomeComponent onDone={onDone} context={context} />
}
```

**典型命令：** `/config`, `/help`, `/memory`, `/skills`, `/doctor`

### 2.3 `prompt` 类型命令

**特点：** 生成 Prompt 发送给 LLM，让模型执行任务

**执行流程：**
```typescript
async getPromptForCommand(args, context): Promise<ContentBlockParam[]> {
  return [{ type: 'text', text: `请执行：${args}` }]
}
```

**典型命令：** `/review`, `/commit`, `/security-review`

---

## 3. 核心命令技术原理

### 3.1 `/compact` - 上下文压缩

**文件：** `src/commands/compact/index.ts` → `src/commands/compact/compact.ts`

**命令定义：**
```typescript
const compact = {
  type: 'local',
  name: 'compact',
  description: 'Clear conversation history but keep a summary in context',
  argumentHint: '<optional custom summarization instructions>',
  isEnabled: () => !isEnvTruthy(process.env.DISABLE_COMPACT),
  supportsNonInteractive: true,
  load: () => import('./compact.js'),
}
```

**核心执行逻辑：**

```typescript
export const call: LocalCommandCall = async (args, context) => {
  const { abortController } = context
  let { messages } = context

  // 1. 获取 compact 边界后的消息（REPL 保留 snipped 消息用于 UI 回滚）
  messages = getMessagesAfterCompactBoundary(messages)

  if (messages.length === 0) {
    throw new Error('No messages to compact')
  }

  const customInstructions = args.trim()

  try {
    // 2. 优先尝试 Session Memory Compact（零 API 成本）
    if (!customInstructions) {
      const sessionMemoryResult = await trySessionMemoryCompaction(
        messages,
        context.agentId,
      )
      if (sessionMemoryResult) {
        getUserContext.cache.clear?.()
        runPostCompactCleanup()
        // 重置缓存读取基线，避免 compact 后的下降被标记为异常
        notifyCompaction(context.agentId, 'session-memory')
        return { type: 'text', value: 'Session memory compaction completed' }
      }
    }

    // 3. Session Memory 不可用时，执行 Full Compact（调用 LLM）
    const systemPrompt = buildEffectiveSystemPrompt(
      getSystemPrompt(),
      getSystemContext(),
    )

    const result: CompactionResult = await compactConversation(
      messages,
      systemPrompt,
      customInstructions || undefined,
      abortController,
    )

    // 4. 设置最后摘要的消息 ID
    setLastSummarizedMessageId(result.lastMessageId)

    // 5. 执行后处理清理
    runPostCompactCleanup()

    // 6. 通知 compaction 完成
    notifyCompaction(context.agentId, 'full')

    return { type: 'text', value: 'Compaction completed' }

  } catch (error) {
    if (hasExactErrorMessage(error, ERROR_MESSAGE_USER_ABORT)) {
      throw error
    }
    logError(error)
    throw error
  }
}
```

**两级压缩策略：**

| 模式 | 触发条件 | API 成本 | 保留内容 |
|------|----------|---------|----------|
| **Session Memory Compact** | 无自定义指令 + Session Memory 启用 | 零成本 | 最近消息原样保留 |
| **Full Compact** | 有自定义指令 或 Session Memory 不可用 | 调用 LLM | 全部消息摘要化 |

**关键依赖：**
- `src/services/compact/sessionMemoryCompact.ts` - Session Memory 压缩
- `src/services/compact/compact.ts` - Full Compact 实现
- `src/services/compact/postCompactCleanup.ts` - 后处理清理
- `src/services/api/promptCacheBreakDetection.js` - 缓存中断检测

---

### 3.2 `/clear` - 清除会话

**文件：** `src/commands/clear/index.ts` → `src/commands/clear/clear.ts`

**命令定义：**
```typescript
const clear = {
  type: 'local',
  name: 'clear',
  description: 'Clear conversation history and free up context',
  aliases: ['reset', 'new'],
  supportsNonInteractive: false,
  load: () => import('./clear.js'),
}
```

**核心执行逻辑：**
```typescript
export const call: LocalCommandCall = async (_, context) => {
  await clearConversation(context)
  return { type: 'text', value: '' }
}
```

**清除操作详解：**
```typescript
// src/commands/clear/conversation.ts
export async function clearConversation(context: CommandContext) {
  // 1. 清除会话缓存
  await clearSessionCaches()
  
  // 2. 重置消息历史
  context.setAppState(s => ({ ...s, messages: [] }))
  
  // 3. 清除上下文缓存
  getUserContext.cache.clear?.()
  getSystemContext.cache.clear?.()
  
  // 4. 通知 UI 更新
  context.onDone()
}
```

**与 `/compact` 的区别：**

| 命令 | 保留摘要 | 保留最近消息 | 调用 LLM |
|------|---------|-------------|----------|
| `/clear` | ❌ | ❌ | ❌ |
| `/compact` | ✅ | ✅ (Session Memory) | 可能 |

---

### 3.3 `/memory` - 管理记忆文件

**文件：** `src/commands/memory/index.ts` → `src/commands/memory/memory.tsx`

**命令定义：**
```typescript
const memory: Command = {
  type: 'local-jsx',
  name: 'memory',
  description: 'Edit Claude memory files',
  load: () => import('./memory.js'),
}
```

**React 组件实现：**
```tsx
function MemoryCommand({ onDone }: { onDone: (result?: string) => void }) {
  const handleSelectMemoryFile = async (memoryPath: string) => {
    try {
      // 1. 创建 claude 目录（如果不存在）
      if (memoryPath.includes(getClaudeConfigHomeDir())) {
        await mkdir(getClaudeConfigHomeDir(), { recursive: true })
      }

      // 2. 创建文件（如果不存在）
      try {
        await writeFile(memoryPath, '', { encoding: 'utf8', flag: 'wx' })
      } catch (e: unknown) {
        if (getErrnoCode(e) !== 'EEXIST') throw e  // 文件已存在则忽略
      }
      
      // 3. 在外部编辑器中打开文件
      await editFileInEditor(memoryPath)

      // 4. 返回编辑器信息
      let editorSource = 'default'
      let editorValue = ''
      if (process.env.VISUAL) {
        editorSource = '$VISUAL'
        editorValue = process.env.VISUAL
      } else if (process.env.EDITOR) {
        editorSource = '$EDITOR'
        editorValue = process.env.EDITOR
      }
      
      onDone(`Opened memory file at ${getRelativeMemoryPath(memoryPath)}`)
    } catch (error) {
      logError(error)
      onDone(`Error opening memory file: ${error}`)
    }
  }

  return (
    <Dialog title="Memory" onCancel={handleCancel} color="remember">
      <MemoryFileSelector onSelect={handleSelectMemoryFile} onCancel={handleCancel} />
    </Dialog>
  )
}
```

**记忆文件类型：**

| 文件 | 路径 | 用途 |
|------|------|------|
| `MEMORY.md` | `~/.claude/memory/MEMORY.md` | 长期记忆 |
| `memory/YYYY-MM-DD.md` | `~/.claude/memory/memory/` | 每日笔记 |
| `CLAUDE.md` | 项目根目录 | 项目说明 |
| `CLAUDE.local.md` | `~/.claude/CLAUDE.local.md` | 个人配置 |

---

### 3.4 `/help` - 显示帮助

**文件：** `src/commands/help/index.ts` → `src/commands/help/help.tsx`

**命令定义：**
```typescript
const help = {
  type: 'local-jsx',
  name: 'help',
  description: 'Show help and available commands',
  load: () => import('./help.js'),
}
```

**React 组件实现：**
```tsx
export const call: LocalJSXCommandCall = async (onDone, { options: { commands } }) => {
  return <HelpV2 commands={commands} onClose={onDone} />
}
```

**HelpV2 组件功能：**
1. 列出所有可用命令
2. 显示命令描述和参数提示
3. 支持命令搜索
4. 显示快捷键绑定

---

### 3.5 `/config` - 配置面板

**文件：** `src/commands/config/index.ts` → `src/commands/config/config.tsx`

**命令定义：**
```typescript
const config = {
  aliases: ['settings'],
  type: 'local-jsx',
  name: 'config',
  description: 'Open config panel',
  load: () => import('./config.js'),
}
```

**React 组件实现：**
```tsx
export const call: LocalJSXCommandCall = async (onDone, context) => {
  return <Settings onClose={onDone} context={context} defaultTab="Config" />
}
```

**可配置项：**
- 模型选择
- 主题设置
- 快捷键绑定
- MCP 服务器
- 隐私设置
- 通知设置

---

### 3.6 `/mcp` - MCP 服务器管理

**文件：** `src/commands/mcp/index.ts`

**命令定义：**
```typescript
const mcp = {
  type: 'local-jsx',
  name: 'mcp',
  description: 'Manage MCP servers',
  immediate: true,
  argumentHint: '[enable|disable [server-name]]',
  load: () => import('./mcp.js'),
}
```

**MCP（Model Context Protocol）：**
- 允许 Claude Code 与外部服务通信
- 支持服务器启用/禁用
- 提供服务器状态查看

---

### 3.7 `/skills` - 技能管理

**文件：** `src/commands/skills/index.ts` → `src/commands/skills/skills.tsx`

**命令定义：**
```typescript
const skills = {
  type: 'local-jsx',
  name: 'skills',
  description: 'List available skills',
  load: () => import('./skills.js'),
}
```

**React 组件实现：**
```tsx
export async function call(onDone, context): Promise<React.ReactNode> {
  return <SkillsMenu onExit={onDone} commands={context.options.commands} />
}
```

**技能系统架构：**
```
active_skills/          # 内置/激活的技能
├── skill_name/
│   └── SKILL.md       # 技能说明文档
customized_skills/      # 自定义技能
└── skill_name/
    └── SKILL.md
```

---

## 4. 配置类命令

### 4.1 `/advisor` - 顾问模型配置

**文件：** `src/commands/advisor.ts`

**命令定义：**
```typescript
const advisor = {
  type: 'local',
  name: 'advisor',
  description: 'Configure the advisor model',
  argumentHint: '[<model>|off]',
  isEnabled: () => canUserConfigureAdvisor(),
  load: () => import('./advisor.js'),
}
```

**核心逻辑：**
```typescript
const call: LocalCommandCall = async (args, context) => {
  const arg = args.trim().toLowerCase()
  const baseModel = parseUserSpecifiedModel(
    context.getAppState().mainLoopModel ?? getDefaultMainLoopModelSetting(),
  )

  // 无参数：显示当前状态
  if (!arg) {
    const current = context.getAppState().advisorModel
    if (!current) {
      return { type: 'text', value: 'Advisor: not set' }
    }
    return { type: 'text', value: `Advisor: ${current}` }
  }

  // 关闭顾问
  if (arg === 'unset' || arg === 'off') {
    context.setAppState(s => ({ ...s, advisorModel: undefined }))
    updateSettingsForSource('userSettings', { advisorModel: undefined })
    return { type: 'text', value: 'Advisor disabled' }
  }

  // 设置新模型
  const normalizedModel = normalizeModelStringForAPI(arg)
  const { valid, error } = await validateModel(resolvedModel)
  if (!valid) {
    return { type: 'text', value: `Invalid model: ${error}` }
  }

  context.setAppState(s => ({ ...s, advisorModel: normalizedModel }))
  updateSettingsForSource('userSettings', { advisorModel: normalizedModel })
  return { type: 'text', value: `Advisor set to ${normalizedModel}` }
}
```

**顾问机制：**
- 使用双模型架构：主模型处理任务，顾问模型提供建议
- 仅特定模型支持顾问功能
- 设置持久化到用户配置文件

---

### 4.2 `/theme` - 主题切换

**文件：** `src/commands/theme/index.ts`

**命令定义：**
```typescript
const theme = {
  type: 'local-jsx',
  name: 'theme',
  description: 'Change the theme',
  load: () => import('./theme.js'),
}
```

**支持主题：**
- `light` - 浅色主题
- `dark` - 深色主题
- `system` - 跟随系统

---

### 4.3 `/vim` - Vim 模式切换

**文件：** `src/commands/vim/index.ts`

**命令定义：**
```typescript
const command = {
  name: 'vim',
  description: 'Toggle between Vim and Normal editing modes',
  supportsNonInteractive: false,
  type: 'local',
  load: () => import('./vim.js'),
}
```

**Vim 模式功能：**
- 正常模式：导航、删除、复制
- 插入模式：文本输入
- 命令行模式：搜索、替换

---

### 4.4 `/model` - 模型切换

**文件：** `src/commands/model/index.ts`

**功能：**
- 切换主对话模型
- 显示可用模型列表
- 支持模型别名

---

## 5. 工具与集成类命令

### 5.1 `/add-dir` - 添加工作目录

**文件：** `src/commands/add-dir/index.ts`

**命令定义：**
```typescript
const addDir = {
  type: 'local-jsx',
  name: 'add-dir',
  description: 'Add a new working directory',
  argumentHint: '<path>',
  load: () => import('./add-dir.js'),
}
```

**功能：**
- 添加新的工作目录到当前会话
- 支持相对路径和绝对路径
- 自动验证目录存在性

---

### 5.2 `/branch` - 分支管理

**文件：** `src/commands/branch/index.ts`

**命令定义：**
```typescript
const branch = {
  type: 'local-jsx',
  name: 'branch',
  aliases: feature('FORK_SUBAGENT') ? [] : ['fork'],
  description: 'Create a branch of the current conversation at this point',
  argumentHint: '[name]',
  load: () => import('./branch.js'),
}
```

**分支功能：**
- 创建当前对话的分支
- 支持自定义分支名称
- 分支间独立上下文

---

### 5.3 `/context` - 上下文可视化

**文件：** `src/commands/context/index.ts`

**命令定义：**
```typescript
export const context: Command = {
  name: 'context',
  description: 'Visualize current context usage as a colored grid',
  type: 'local-jsx',
  load: () => import('./context.js'),
}
```

**可视化方式：**
- 彩色网格显示 token 使用分布
- 区分系统提示、用户消息、助手响应
- 显示剩余上下文窗口

---

### 5.4 `/diff` - 查看差异

**文件：** `src/commands/diff/index.ts`

**命令定义：**
```typescript
export default {
  type: 'local-jsx',
  name: 'diff',
  description: 'View uncommitted changes and per-turn diffs',
  load: () => import('./diff.js'),
}
```

**功能：**
- 显示未提交的 Git 变更
- 按对话轮次显示差异
- 支持文件筛选

---

### 5.5 `/files` - 文件列表

**文件：** `src/commands/files/index.ts`

**命令定义：**
```typescript
const files = {
  type: 'local',
  name: 'files',
  description: 'List all files currently in context',
  isEnabled: () => process.env.USER_TYPE === 'ant',  // 仅内部可用
  supportsNonInteractive: true,
  load: () => import('./files.js'),
}
```

---

## 6. 代码审查类命令

### 6.1 `/review` - PR 审查

**文件：** `src/commands/review.ts`

**命令定义：**
```typescript
const review: Command = {
  type: 'prompt',
  name: 'review',
  description: 'Review a pull request',
  progressMessage: 'reviewing pull request',
  async getPromptForCommand(args): Promise<ContentBlockParam[]> {
    return [{ type: 'text', text: LOCAL_REVIEW_PROMPT(args) }]
  },
}
```

**Prompt 模板：**
```typescript
const LOCAL_REVIEW_PROMPT = (args: string) => `
  You are an expert code reviewer. Follow these steps:

  1. If no PR number is provided, run \`gh pr list\` to show open PRs
  2. If a PR number is provided, run \`gh pr view <number>\` to get PR details
  3. Run \`gh pr diff <number>\` to get the diff
  4. Analyze the changes and provide a thorough code review

  Focus on:
  - Code correctness
  - Following project conventions
  - Performance implications
  - Test coverage
  - Security considerations

  PR number: ${args}
`
```

**允许的工具：**
- `gh pr list`
- `gh pr view`
- `gh pr diff`

---

### 6.2 `/ultrareview` - 深度审查

**文件：** `src/commands/review.ts`

**命令定义：**
```typescript
const ultrareview: Command = {
  type: 'local-jsx',
  name: 'ultrareview',
  description: `~10–20 min · Finds and verifies bugs in your branch`,
  isEnabled: () => isUltrareviewEnabled(),
  load: () => import('./review/ultrareviewCommand.js'),
}
```

**与 `/review` 的区别：**

| 特性 | `/review` | `/ultrareview` |
|------|-----------|----------------|
| 类型 | `prompt` | `local-jsx` |
| 执行位置 | 本地 | Claude Code Web |
| 时间 | ~1-2 分钟 | ~10-20 分钟 |
| 深度 | 基础审查 | 深度 Bug 检测 + 验证 |

---

### 6.3 `/commit` - Git 提交

**文件：** `src/commands/commit.ts`

**命令定义：**
```typescript
const command = {
  type: 'prompt',
  name: 'commit',
  description: 'Create a git commit',
  allowedTools: [
    'Bash(git add:*)',
    'Bash(git status:*)',
    'Bash(git commit:*)',
  ],
  async getPromptForCommand(_args, context) {
    const promptContent = getPromptContent()
    return executeShellCommandsInPrompt(promptContent, context)
  },
}
```

**Prompt 内容：**
```typescript
function getPromptContent(): string {
  return `## Context
- Current git status: !\`git status\`
- Current git diff: !\`git diff HEAD\`
- Current branch: !\`git branch --show-current\`
- Recent commits: !\`git log --oneline -10\`

## Git Safety Protocol
- NEVER update git config
- NEVER skip hooks (--no-verify) unless explicitly requested
- ALWAYS create NEW commits, never --amend
- Do not commit files with secrets

## Your task
1. Analyze staged changes
2. Draft commit message following repo style
3. Stage files and create commit using HEREDOC syntax
`
}
```

**安全协议：**
- 禁止修改 git 配置
- 禁止跳过 hooks
- 禁止使用 `--amend`
- 禁止提交敏感文件

---

### 6.4 `/security-review` - 安全审查

**文件：** `src/commands/security-review.ts`

**命令类型：** `prompt`

**允许的工具：**
```
Bash(git diff:*), Bash(git status:*), Bash(git log:*), 
Bash(git show:*), Bash(git remote show:*), 
Read, Glob, Grep, LS, Task
```

**审查重点：**
| 类别 | 检测内容 |
|------|---------|
| **输入验证** | SQL 注入、命令注入、XXE、模板注入 |
| **认证授权** | 认证绕过、权限提升、会话管理 |
| **加密与密钥** | 硬编码密钥、弱加密、密钥管理 |
| **代码执行** | RCE、反序列化、YAML 注入 |
| **数据泄露** | 敏感数据日志、PII 处理、API 泄露 |

**输出格式：**
```markdown
## HIGH Confidence Findings
[仅列出>80% 确信的可利用漏洞]

## Summary
[风险评估和修复建议]
```

---

### 6.5 `/commit-push-pr` - 提交并推送 PR

**文件：** `src/commands/commit-push-pr.ts`

**功能：**
1. 创建 Git 提交
2. 推送到远程
3. 创建 Pull Request
4. 可选：请求审查

---

## 7. 诊断与维护类命令

### 7.1 `/doctor` - 诊断工具

**文件：** `src/commands/doctor/index.ts` → `src/commands/doctor/doctor.tsx`

**命令定义：**
```typescript
const doctor: Command = {
  name: 'doctor',
  description: 'Diagnose and verify your Claude Code installation and settings',
  isEnabled: () => !isEnvTruthy(process.env.DISABLE_DOCTOR_COMMAND),
  type: 'local-jsx',
  load: () => import('./doctor.js'),
}
```

**React 组件：**
```tsx
export const call: LocalJSXCommandCall = (onDone, _context, _args) => {
  return Promise.resolve(<Doctor onDone={onDone} />)
}
```

**诊断项目：**
- Node.js 版本检查
- 安装完整性验证
- 配置文件检查
- API 连接测试
- 权限验证
- 环境变量检测

---

### 7.2 `/status` - 状态显示

**文件：** `src/commands/status/index.ts`

**命令定义：**
```typescript
const status = {
  type: 'local-jsx',
  name: 'status',
  description: 'Show Claude Code status including version, model, account, API connectivity',
  immediate: true,
  load: () => import('./status.js'),
}
```

**显示内容：**
- Claude Code 版本
- 当前模型
- 账户信息
- API 连接状态
- 工具状态

---

### 7.3 `/usage` - 用量统计

**文件：** `src/commands/usage/index.ts`

**命令定义：**
```typescript
export default {
  type: 'local-jsx',
  name: 'usage',
  description: 'Show plan usage limits',
  availability: ['claude-ai'],
  load: () => import('./usage.js'),
}
```

**统计内容：**
- API 调用次数
- Token 使用量
- 剩余配额
- 计费周期

---

### 7.4 `/cost` - 成本显示

**文件：** `src/commands/cost/index.ts`

**命令定义：**
```typescript
const cost = {
  type: 'local',
  name: 'cost',
  description: 'Show the total cost and duration of the current session',
  get isHidden() {
    if (process.env.USER_TYPE === 'ant') return false
    return isClaudeAISubscriber()
  },
  supportsNonInteractive: true,
  load: () => import('./cost.js'),
}
```

**成本计算：**
```typescript
// 基于 token 使用量和模型定价
cost = (input_tokens * input_rate) + (output_tokens * output_rate)
```

---

### 7.5 `/upgrade` - 升级应用

**文件：** `src/commands/upgrade/index.ts`

**功能：**
- 检查最新版本
- 执行升级流程
- 显示更新日志

---

## 8. 条件启用命令

### 8.1 特性标志控制

以下命令仅在特定特性标志启用时可用：

| 命令 | 特性标志 | 说明 |
|------|---------|------|
| `/brief` | `KAIROS` / `KAIROS_BRIEF` | 简报功能 |
| `/assistant` | `KAIROS` | 助手功能 |
| `/bridge` | `BRIDGE_MODE` | 桥接模式 |
| `/remote-control` | `DAEMON` + `BRIDGE_MODE` | 远程控制 |
| `/voice` | `VOICE_MODE` | 语音模式 |
| `/fork` | `FORK_SUBAGENT` | 子代理分叉 |
| `/workflows` | `WORKFLOW_SCRIPTS` | 工作流脚本 |

### 8.2 条件实现示例

```typescript
// src/commands.ts
const briefCommand =
  feature('KAIROS') || feature('KAIROS_BRIEF')
    ? require('./commands/brief.js').default
    : null

const forkCmd = feature('FORK_SUBAGENT')
  ? require('./commands/fork/index.js').default
  : null

// 在命令数组中条件添加
const COMMANDS = memoize((): Command[] => [
  // ... 核心命令
  ...(briefCommand ? [briefCommand] : []),
  ...(forkCmd ? [forkCmd] : []),
])
```

---

## 9. 命令扩展机制

### 9.1 创建新命令

**步骤 1：创建命令目录**
```bash
mkdir src/commands/my-command
```

**步骤 2：创建 index.ts**
```typescript
import type { Command } from '../../commands.js'

const myCommand: Command = {
  type: 'local-jsx',
  name: 'my-command',
  description: 'My custom command',
  argumentHint: '[optional-arg]',
  load: () => import('./my-command.js'),
}

export default myCommand
```

**步骤 3：创建实现文件**
```typescript
// local 类型
export const call: LocalCommandCall = async (_, context) => {
  // 实现逻辑
  return { type: 'text', value: 'Result' }
}

// local-jsx 类型
export const call: LocalJSXCommandCall = (onDone, context) => {
  return <MyComponent onDone={onDone} />
}
```

**步骤 4：注册命令**
```typescript
// src/commands.ts
import myCommand from './commands/my-command/index.js'

const COMMANDS = memoize((): Command[] => [
  // ... 现有命令
  myCommand,
])
```

### 9.2 命令类型选择指南

| 需求 | 推荐类型 |
|------|---------|
| 纯逻辑处理，无 UI | `local` |
| 需要用户交互界面 | `local-jsx` |
| 需要 LLM 执行任务 | `prompt` |
| 立即执行，无确认 | `immediate: true` |
| 支持非交互模式 | `supportsNonInteractive: true` |

### 9.3 插件命令

通过 `/plugin` 命令可以加载外部插件，扩展命令系统：

```typescript
// 插件命令格式
{
  name: 'plugin-command',
  type: 'local',
  source: 'plugin',
  pluginName: 'my-plugin',
  load: () => import('my-plugin/command.js'),
}
```

---

## 附录 A：命令完整列表

详见 `commands-reference.md`

---

## 附录 B：关键文件索引

| 文件 | 说明 |
|------|------|
| `src/commands.ts` | 命令注册中心 |
| `src/types/command.ts` | 命令类型定义 |
| `src/commands/*/index.ts` | 命令元数据 |
| `src/commands/*/*.ts(x)` | 命令实现 |

---

## 附录 C：环境变量

| 变量 | 作用 |
|------|------|
| `DISABLE_COMPACT` | 禁用 `/compact` 命令 |
| `DISABLE_DOCTOR_COMMAND` | 禁用 `/doctor` 命令 |
| `DISABLE_LOGIN_COMMAND` | 禁用 `/login` 命令 |
| `DISABLE_LOGOUT_COMMAND` | 禁用 `/logout` 命令 |
| `DISABLE_FEEDBACK_COMMAND` | 禁用 `/feedback` 命令 |
| `DISABLE_INSTALL_GITHUB_APP_COMMAND` | 禁用 `/install-github-app` 命令 |
| `USER_TYPE=ant` | Anthropic 员工模式 |
| `IS_DEMO` | 演示模式 |

---

## 附录 D：更多命令深度分析

### D.1 `/rewind` - 回退到检查点

**文件：** `src/commands/rewind/index.ts` → `src/commands/rewind/rewind.ts`

**命令定义：**
```typescript
const rewind = {
  description: `Restore the code and/or conversation to a previous point`,
  name: 'rewind',
  aliases: ['checkpoint'],
  type: 'local',
  supportsNonInteractive: false,
  load: () => import('./rewind.js'),
}
```

**核心逻辑：**
```typescript
export async function call(_args: string, context: ToolUseContext): Promise<LocalCommandResult> {
  if (context.openMessageSelector) {
    context.openMessageSelector()
  }
  return { type: 'skip' }  // 不追加任何消息
}
```

**功能：**
- 打开消息选择器 UI
- 允许用户选择历史检查点
- 恢复代码和对话到选定状态

---

### D.2 `/release-notes` - 查看更新日志

**文件：** `src/commands/release-notes/release-notes.ts`

**核心逻辑：**
```typescript
export async function call(): Promise<LocalCommandResult> {
  // 尝试获取最新日志（500ms 超时）
  let freshNotes: Array<[string, string[]]> = []
  
  try {
    const timeoutPromise = new Promise<void>((_, reject) => {
      setTimeout(() => reject(new Error('Timeout')), 500)
    })
    await Promise.race([fetchAndStoreChangelog(), timeoutPromise])
    freshNotes = getAllReleaseNotes(await getStoredChangelog())
  } catch {
    // 获取失败或超时则使用缓存
  }

  if (freshNotes.length > 0) {
    return { type: 'text', value: formatReleaseNotes(freshNotes) }
  }

  const cachedNotes = getAllReleaseNotes(await getStoredChangelog())
  if (cachedNotes.length > 0) {
    return { type: 'text', value: formatReleaseNotes(cachedNotes) }
  }

  return {
    type: 'text',
    value: `See the full changelog at: ${CHANGELOG_URL}`,
  }
}
```

**输出格式：**
```
Version 2.0.20260406.1:
· Improved context window management
· Fixed compact command edge cases

Version 2.0.20260405.1:
· Added new /rewind command
· Performance improvements
```

---

### D.3 `/resume` - 恢复会话

**文件：** `src/commands/resume/index.ts`

**命令定义：**
```typescript
const resume: Command = {
  type: 'local-jsx',
  name: 'resume',
  description: 'Resume a previous conversation',
  aliases: ['continue'],
  argumentHint: '[conversation id or search term]',
  load: () => import('./resume.js'),
}
```

**功能：**
- 列出历史会话
- 支持按 ID 或关键词搜索
- 加载选定会话的上下文

---

### D.4 `/rename` - 重命名会话

**文件：** `src/commands/rename/index.ts`

**命令定义：**
```typescript
const rename = {
  type: 'local-jsx',
  name: 'rename',
  description: 'Rename the current conversation',
  immediate: true,
  argumentHint: '[name]',
  load: () => import('./rename.js'),
}
```

**`immediate: true` 含义：**
- 立即执行，无需确认
- 不显示加载状态
- 直接更新会话元数据

---

### D.5 `/hooks` - Hook 配置

**文件：** `src/commands/hooks/index.ts`

**命令定义：**
```typescript
const hooks = {
  type: 'local-jsx',
  name: 'hooks',
  description: 'View hook configurations for tool events',
  immediate: true,
  load: () => import('./hooks.js'),
}
```

**Hook 类型：**
| Hook 事件 | 触发时机 |
|----------|---------|
| `before_edit` | 文件编辑前 |
| `after_edit` | 文件编辑后 |
| `before_bash` | Bash 命令执行前 |
| `after_bash` | Bash 命令执行后 |

---

### D.6 `/permissions` - 工具权限管理

**文件：** `src/commands/permissions/index.ts`

**命令定义：**
```typescript
const permissions = {
  type: 'local-jsx',
  name: 'permissions',
  aliases: ['allowed-tools'],
  description: 'Manage allow & deny tool permission rules',
  load: () => import('./permissions.js'),
}
```

**权限规则格式：**
```
允许：Read, Glob, Grep, LS
允许：Bash(git status:*)
允许：Bash(git diff:*)
拒绝：Bash(rm:*)
拒绝：Bash(sudo:*)
```

---

### D.7 `/privacy-settings` - 隐私设置

**文件：** `src/commands/privacy-settings/index.ts`

**命令定义：**
```typescript
const privacySettings = {
  type: 'local-jsx',
  name: 'privacy-settings',
  description: 'View and update your privacy settings',
  isEnabled: () => isConsumerSubscriber(),
  load: () => import('./privacy-settings.js'),
}
```

**隐私级别：**
| 级别 | 说明 |
|------|------|
| `essential` | 仅必要的数据收集 |
| `standard` | 标准数据收集 |
| `enhanced` | 增强数据收集（用于改进） |

---

### D.8 `/install-github-app` - 安装 GitHub 应用

**文件：** `src/commands/install-github-app/index.ts`

**命令定义：**
```typescript
const installGitHubApp = {
  type: 'local-jsx',
  name: 'install-github-app',
  description: 'Set up Claude GitHub Actions for a repository',
  availability: ['claude-ai', 'console'],
  isEnabled: () => !isEnvTruthy(process.env.DISABLE_INSTALL_GITHUB_APP_COMMAND),
  load: () => import('./install-github-app.js'),
}
```

**功能：**
- 在仓库中配置 GitHub Actions
- 设置 Claude Code 自动化工作流
- 配置 PR 审查、Issue 处理等

---

### D.9 存根命令（Stub Commands）

以下命令当前被禁用（仅内部可用或未实现）：

```typescript
// share/index.js
export default { isEnabled: () => false, isHidden: true, name: 'stub' }

// teleport/index.js
export default { isEnabled: () => false, isHidden: true, name: 'stub' }
```

**存根命令列表：**
- `/share` - 分享会话
- `/teleport` - 瞬移功能
- `/issue` - Issue 管理
- `/onboarding` - 入职引导
- `/ctx_viz` - 上下文可视化
- `/good-claude` - Good Claude 模式
- `/bughunter` - Bug 猎人
- `/backfill-sessions` - 回填会话
- `/autofix-pr` - 自动修复 PR
- `/env` - 环境变量
- `/oauth-refresh` - OAuth 刷新
- `/debug-tool-call` - 调试工具调用
- `/ant-trace` - 追踪功能
- `/perf-issue` - 性能问题

---

## 附录 E：命令调用链示例

### E.1 `/compact` 完整调用链

```
用户输入 /compact
    ↓
src/commands.ts: COMMANDS 数组
    ↓
src/commands/compact/index.ts: compact 对象
    ↓
load: () => import('./compact.js')
    ↓
src/commands/compact/compact.ts: call 函数
    ↓
trySessionMemoryCompaction() [优先]
    ├─→ src/services/compact/sessionMemoryCompact.ts
    └─→ 成功则返回，失败则继续
    ↓
compactConversation() [Fallback]
    ├─→ src/services/compact/compact.ts
    ├─→ 调用 LLM 生成摘要
    └─→ 返回压缩结果
    ↓
runPostCompactCleanup()
    ├─→ src/services/compact/postCompactCleanup.ts
    └─→ 清理缓存、恢复文件
    ↓
notifyCompaction()
    ├─→ src/services/api/promptCacheBreakDetection.js
    └─→ 通知缓存中断检测
    ↓
返回结果给 UI
```

### E.2 `/review` 完整调用链

```
用户输入 /review 123
    ↓
src/commands.ts: COMMANDS 数组
    ↓
src/commands/review.ts: review 对象
    ↓
getPromptForCommand('123', context)
    ↓
LOCAL_REVIEW_PROMPT('123')
    ├─→ 生成 Prompt 模板
    └─→ 插入 PR 编号
    ↓
executeShellCommandsInPrompt()
    ├─→ src/utils/promptShellExecution.js
    └─→ 预执行 shell 命令获取上下文
    ↓
返回 ContentBlockParam[]
    ↓
发送给 LLM 执行
```

### E.3 `/config` 完整调用链

```
用户输入 /config
    ↓
src/commands.ts: COMMANDS 数组
    ↓
src/commands/config/index.ts: config 对象
    ↓
load: () => import('./config.js')
    ↓
src/commands/config/config.tsx: call 函数
    ↓
return <Settings onClose={onDone} context={context} defaultTab="Config" />
    ↓
src/components/Settings/Settings.js: Settings 组件
    ├─→ 渲染配置面板
    ├─→ 处理用户交互
    └─→ 调用 onDone 关闭
    ↓
返回结果
```

---

*本文档基于 Claude Code 源代码分析生成*
*最后更新：2026-04-06*
