# Claude Code 技能系统深度分析报告

## 模块概述

### 一句话角色定位

**技能系统是 Claude Code 的独立命令系统**——它有自己的目录结构、加载逻辑和注册机制，与 Tools 系统是不同的设计，通过 SkillTool 与 Agent 连接。

### 核心架构理解

```
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code 架构分层                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ CLI Commands 系统 (src/commands/)                            ││
│  │ - /help, /clear, /config, /status, /mcp...                  ││
│  │ - 类型: local, local-jsx                                     ││
│  │ - 职责: 处理用户在 REPL 中输入的界面命令                      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Skills 系统 (src/skills/) ←── 独立的 prompt 模板系统          ││
│  │                                                              ││
│  │ - /commit, /review-pr, /doctor, /remember...                ││
│  │ - 类型: prompt (prompt 模板)                                 ││
│  │                                                              ││
│  │ 有自己的:                                                    ││
│  │   ├── 目录结构: bundled/, loadSkillsDir.ts                   ││
│  │   ├── 加载逻辑: getSkillDirCommands(), discoverSkillDirs()   ││
│  │   ├── 注册机制: registerBundledSkill()                       ││
│  │   └── 来源标识: loadedFrom (bundled/skills/plugin/mcp)       ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Tools 系统 (src/tools/)                                      ││
│  │ - Bash, Read, Edit, Glob, Grep, Skill, Agent...             ││
│  │ - 职责: Agent 通过 Tools 执行具体操作                         ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 连接点: SkillTool                                            ││
│  │ - Agent 通过这个 Tool 调用 Skills 系统                       ││
│  │ - Skills 的 prompt 模板展开后注入对话                         ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 与其他模块的关系

```
                    ┌──────────────┐
                    │  QueryEngine │
                    │  (查询引擎)   │
                    └──────┬───────┘
                           │ Agent 决定调用技能
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │                    SkillTool                         │
    │              (连接 Skills 和 Agent)                   │
    ├─────────────────────────────────────────────────────┤
    │                                                      │
    │  Agent 调用流程:                                      │
    │  skill_listing (发现) ──→ SkillTool({skill, args})   │
    │                          │                           │
    │                          ▼                           │
    │  Skills 系统 ──→ getPromptForCommand() ──→ 展开模板   │
    │                                                      │
    │  执行模式:                                           │
    │  ┌─────────────┐         ┌─────────────┐            │
    │  │ Inline      │         │ Fork        │            │
    │  │ (展开到对话) │         │ (子Agent)   │            │
    │  └─────────────┘         └─────────────┘            │
    └─────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ 权限系统  │     │ 子Agent  │     │ 设置管理  │
    │(Permission)│    │(runAgent) │    │(Settings) │
    └──────────┘     └──────────┘     └──────────┘
```

---

## Skills 系统架构

### 1. Command 类型：Skills 和 CLI Commands 的统一抽象

Skills 和 CLI Commands 共享同一个 `Command` 类型，实现统一抽象：

```typescript
// src/types/command.ts
type Command = CommandBase &
  (PromptCommand | LocalCommand | LocalJSXCommand)
```

| 类型 | 用途 | 示例 |
|-----|-----|-----|
| `prompt` | Prompt 模板命令 | Skills (/commit, /review-pr) |
| `local` | 本地函数命令 | 部分 CLI 命令 |
| `local-jsx` | JSX UI 命令 | /skills, /mcp, /config |

**PromptCommand 结构**（Skills 使用的类型）：

```typescript
type PromptCommand = {
  type: 'prompt'
  progressMessage: string
  contentLength: number
  allowedTools?: string[]
  model?: string
  source: SettingSource | 'builtin' | 'mcp' | 'plugin' | 'bundled'
  context?: 'inline' | 'fork'
  agent?: string
  effort?: EffortValue
  paths?: string[]
  getPromptForCommand(args: string, context): Promise<ContentBlockParam[]>
}
```

### 2. Skills 来源标识（loadedFrom）

通过 `loadedFrom` 字段区分技能来源：

```
┌──────────────────────┬──────────────────────────────────────────────────┐
│      loadedFrom      │                       说明                      │
├──────────────────────┼──────────────────────────────────────────────────┤
│ bundled              │ 内置技能，编译到 CLI 中，所有用户可用            │
│ skills               │ 用户/项目技能目录，.claude/skills/               │
│ plugin               │ 插件提供的技能                                    │
│ mcp                  │ MCP 服务器提供的远程技能                          │
│ managed              │ 企业策略配置，由管理员定义                        │
│ commands_DEPRECATED  │ 遗留命令目录，.claude/commands/                   │
└──────────────────────┴──────────────────────────────────────────────────┘
```

### 3. Skills 目录结构

```
src/skills/
├── bundledSkills.ts      # 内置技能注册 API
├── loadSkillsDir.ts      # 技能目录加载器（核心）
├── mcpSkillBuilders.ts   # MCP 技能构建器
└── bundled/              # 内置技能实现
    ├── index.ts          # 聚合所有内置技能
    ├── commit.ts         # Git 提交技能
    ├── review-pr.ts      # PR 审核技能
    ├── doctor.ts         # 诊断技能
    ├── loop.ts           # 循环执行技能
    ├── remember.ts       # 记忆技能
    └── ...               # 更多内置技能
```

---

## 核心概念（生活化类比）

### 1. Skill（技能）—— Prompt 模板命令

技能是 Markdown 格式的 prompt 模板，告诉 Claude 如何完成特定任务：

```
┌─────────────────────────────────────────────────────────────────┐
│                    技能结构示例                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  文件: .claude/skills/review-pr/SKILL.md                        │
│  ─────────────────────────────────────────────────────────────  │
│  ---                                                             │
│  name: review-pr                                                │
│  description: Review a pull request for quality and security    │
│  argument-hint: <pr-number>                                     │
│  allowed-tools: [Bash, Read, Grep]                              │
│  ---                                                             │
│                                                                  │
│  You are reviewing pull request #$ARGUMENTS[0].                 │
│                                                                  │
│  Steps:                                                         │
│  1. Use `gh pr view $ARGUMENTS[0]` to get PR details           │
│  2. Read the changed files and analyze the diff                │
│  3. Check for security vulnerabilities and code quality        │
│  4. Provide a summary with recommendations                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**生活类比**：技能就像一张"任务卡片"——上面写着任务目标、可用工具、具体步骤。当 Agent 调用时，这张卡片的内容被展开到对话中。

### 2. Frontmatter（前置元数据）—— 技能的配置信息

每个技能文件开头都有 YAML 格式的配置：

```yaml
---
name: commit                    # 技能名称
description: Create a commit    # 简短描述（用于 skill_listing）
argument-hint: <message>        # 参数提示（显示在 UI）
arguments: message scope        # 命名参数定义
allowed-tools: [Bash, Read]     # 执行时可用的工具
model: haiku                    # 模型覆盖
context: fork                   # 执行模式：inline/fork
agent: general-purpose          # Fork 时使用的 Agent 类型
paths: "src/**/*.ts"            # 条件激活路径
hooks:                          # 技能触发时的 Hook
  PreToolUse: [...]
---
```

### 3. 执行模式（Inline vs Fork）

```
┌─────────────────────────────────────────────────────────────────┐
│                    执行模式对比                                   │
├──────────────┬──────────────────────────────────────────────────┤
│     模式      │                    说明                          │
├──────────────┼──────────────────────────────────────────────────┤
│   Inline     │  技能内容直接展开到当前对话                        │
│   (内联)     │  共享上下文和 token 预算                          │
│              │  适合简单任务                                     │
├──────────────┼──────────────────────────────────────────────────┤
│   Fork       │  技能在独立子 Agent 中执行                         │
│   (分叉)     │  有独立的上下文和 token 预算                       │
│              │  适合复杂、长时间任务                               │
└──────────────┴──────────────────────────────────────────────────┘
```

**生活类比**：
- **Inline** = 在同一个会议室里讨论，大家共享同一个白板
- **Fork** = 派一个助手去另一个房间独立工作，完成后汇报结果

### 4. 参数替换（$ARGUMENTS）

技能支持多种参数占位符：

```
┌─────────────────────────────────────────────────────────────────┐
│                    参数占位符语法                                 │
├─────────────────────────────────────────────────────────────────┤
│  用户调用: /review-pr 123 main-branch                            │
│                                                                  │
│  技能内容中的占位符:                                              │
│  ├── $ARGUMENTS         → "123 main-branch"   (完整参数)        │
│  ├── $ARGUMENTS[0]      → "123"               (第一个参数)      │
│  ├── $ARGUMENTS[1]      → "main-branch"       (第二个参数)      │
│  ├── $0                 → "123"               (简写: 第一个)    │
│  ├── $1                 → "main-branch"       (简写: 第二个)    │
│  │                                                              │
│  │  如果定义了 arguments: pr branch                              │
│  ├── $pr               → "123"               (命名参数)        │
│  └── $branch           → "main-branch"       (命名参数)        │
└─────────────────────────────────────────────────────────────────┘
```

### 5. 条件激活（paths）

技能可以声明 `paths` 属性，只有当操作匹配这些路径时才激活：

```yaml
---
name: typescript-helper
paths: "src/**/*.ts"
---
```

**工作原理**：当 Agent 操作（Read/Write/Edit）匹配路径的文件时，技能被自动添加到可用技能列表。

---

## 加载机制

### Skill 系统加载流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Skill 系统加载流程                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  启动时:                                                            │
│  ────────────────────────────────────────────────────────────────── │
│  main.tsx ──→ initBundledSkills() [同步注册]                        │
│              │                                                       │
│              └── registerBundledSkill() 推入 bundledSkills[] 数组    │
│                                                                      │
│  首次调用 getCommands():                                            │
│  ────────────────────────────────────────────────────────────────── │
│  commands.ts ──→ getSkills() [异步并行加载]                          │
│                │                                                     │
│                ├── getSkillDirCommands(cwd) [memoized]              │
│                │   ├── loadSkillsFromSkillsDir() 用户/项目技能       │
│                │   ├── loadSkillsFromCommandsDir() [遗留格式]        │
│                │   └── discoverSkillDirsForPaths() [动态发现]        │
│                │                                                     │
│                ├── getPluginSkills()                                │
│                ├── getBundledSkills() [返回已注册的]                 │
│                └── getBuiltinPluginSkillCommands()                  │
│                                                                      │
│  运行时按需发现:                                                     │
│  ────────────────────────────────────────────────────────────────── │
│  文件操作 ──→ activateConditionalSkillsForPaths()                   │
│             │                                                        │
│             └── 匹配 paths frontmatter 的技能被激活                   │
│                 dynamicSkills.set(name, skill)                      │
│                                                                      │
│  输出: getSkillToolCommands() ──→ Agent 可调用的 skills 列表         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 关键加载函数

| 函数 | 职责 |
|-----|-----|
| `initBundledSkills()` | 同步注册内置技能到内存 |
| `getSkillDirCommands()` | 异步加载用户/项目技能目录 |
| `getSkillToolCommands()` | 获取 Agent 可调用的 skills |
| `discoverSkillDirsForPaths()` | 动态发现嵌套项目中的技能目录 |
| `activateConditionalSkillsForPaths()` | 激活匹配 paths 的条件技能 |

---

## Agent 调用流程

### Agent 如何发现技能

Agent 通过 `skill_listing` attachment 发现可用技能：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    skill_listing attachment                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  来源: src/utils/attachments.ts                                     │
│                                                                      │
│  格式:                                                               │
│  system-reminder:                                                   │
│  skill_listing:                                                     │
│  - commit: Create a git commit with staged changes                  │
│  - review-pr: Review a pull request for quality                     │
│  - doctor: Run diagnostic checks on your environment                │
│  - remember: Store information across sessions                      │
│  ...                                                                │
│                                                                      │
│  限制: 占用 1% context window，优先保留 bundled skills              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Agent 如何调用技能

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Agent 调用流程                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: skill="review-pr", args="123"                                │
│                                                                      │
│  Phase 1: validateInput()                                           │
│  ────────────────────────────────────────────────────────────────── │
│  ├── 移除前导斜杠 (/review-pr → review-pr)                          │
│  ├── 查找技能是否存在                                                │
│  └── 检查是否禁止模型调用                                            │
│                                                                      │
│  Phase 2: checkPermissions()                                        │
│  ────────────────────────────────────────────────────────────────── │
│  ├── 检查 deny 规则 → 命中则拒绝                                    │
│  ├── 检查 allow 规则 → 命中则放行                                    │
│  ├── 检查安全属性白名单 → 只有安全属性则自动放行                     │
│  └── 默认 → 弹出确认对话框                                           │
│                                                                      │
│  Phase 3: call()                                                    │
│  ────────────────────────────────────────────────────────────────── │
│  │                                                                   │
│  ├── context === 'fork' ?                                           │
│  │   │                                                               │
│  │   ├── YES: executeForkedSkill()                                  │
│  │   │   ├── prepareForkedCommandContext()                         │
│  │   │   ├── runAgent() 创建独立 Agent                              │
│  │   │   └── 返回 {status: 'forked', result}                        │
│  │   │                                                               │
│  │   └── NO: Inline 执行                                             │
│  │       │                                                           │
│  │       ├── processPromptSlashCommand()                            │
│  │       │   ├── getPromptForCommand() 获取技能内容                 │
│  │       │   ├── substituteArguments() 参数替换                     │
│  │       │   └── 返回处理后的 prompt                                 │
│  │       │                                                           │
│  │       └── 返回 newMessages (展开到对话)                          │
│                                                                      │
│  Phase 4: contextModifier()                                         │
│  ────────────────────────────────────────────────────────────────── │
│  ├── allowedTools → 添加到 alwaysAllowRules                         │
│  ├── model → 覆盖后续查询使用的模型                                  │
│  └── effort → 设置思考努力级别                                       │
│                                                                      │
│  输出: ToolResult { success, commandName, newMessages?, ... }        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 深度解析：系统提示词注入机制

### 两阶段内容注入

Skill 系统采用**两阶段注入策略**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    两阶段内容注入                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  阶段 1: 发现阶段 (skill_listing)                                    │
│  ────────────────────────────────────────────────────────────────── │
│  注入内容: 仅技能名称 + 简短描述                                      │
│  格式: "- commit: Create a git commit with staged changes"          │
│  目的: 让 LLM 知道有哪些技能可用                                     │
│  Token 成本: 低（限制在 1% context window）                          │
│                                                                      │
│  阶段 2: 调用阶段 (getPromptForCommand)                              │
│  ────────────────────────────────────────────────────────────────── │
│  注入内容: 技能完整 prompt 模板                                      │
│  格式: 完整 Markdown 内容（步骤、示例、Shell 命令等）                 │
│  触发: LLM 调用 SkillTool 时                                         │
│  Token 成本: 按需加载，只有实际使用的技能才消耗                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 为什么这样设计？

| 问题 | 解决方案 |
|-----|---------|
| 50+ 技能完整内容会占用大量 token | 初始只注入名称+描述（< 1% context） |
| LLM 需要知道有哪些技能可用 | skill_listing 提供技能目录 |
| 完整内容只在调用时才需要 | getPromptForCommand 按需加载 |

### 完整流程示例

```
┌─────────────────────────────────────────────────────────────────────┐
│                    完整流程示例: /commit 技能                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [Turn 0] 初始注入                                                   │
│  ────────────────────────────────────────────────────────────────── │
│  LLM 收到:                                                           │
│  <system-reminder>                                                   │
│  The following skills are available:                                 │
│  - commit: Create a git commit with staged changes                   │
│  - review-pr: Review a pull request...                               │
│  ...                                                                 │
│  </system-reminder>                                                  │
│                                                                      │
│  → LLM 只看到简介，token 消耗低                                       │
│                                                                      │
│  [Turn 1] LLM 决定调用 commit 技能                                   │
│  ────────────────────────────────────────────────────────────────── │
│  LLM 输出:                                                           │
│  {                                                                   │
│    "type": "tool_use",                                               │
│    "name": "Skill",                                                  │
│    "input": { "skill": "commit", "args": "fix bug" }                 │
│  }                                                                   │
│                                                                      │
│  [Turn 2] 技能完整内容加载                                           │
│  ────────────────────────────────────────────────────────────────── │
│  SkillTool 调用 getPromptForCommand():                               │
│  - 从内存/文件读取完整 Markdown                                       │
│  - 执行参数替换、Shell 命令等                                         │
│  - 返回处理后的完整内容                                               │
│                                                                      │
│  注入到对话:                                                         │
│  <user message isMeta="true">                                        │
│  Create a git commit with the message: fix bug                       │
│                                                                      │
│  Steps:                                                              │
│  1. Run `git status` to see what changed                             │
│  2. Run `git diff` to understand the changes                         │
│  3. Stage relevant files with `git add`                              │
│  4. Create the commit                                                │
│                                                                      │
│  Current branch: main                                                │
│  Changed files: src/foo.ts, src/bar.ts                               │
│  </user message>                                                     │
│                                                                      │
│  → 完整内容按需加载，只有被调用的技能才消耗 token                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### skill_listing Attachment 结构

技能列表通过 `skill_listing` attachment 类型注入到 LLM 上下文中：

```typescript
// src/utils/attachments.ts
type Attachment = {
  type: 'skill_listing'
  content: string      // 格式化的技能列表
  skillCount: number   // 技能数量
  isInitial: boolean   // 是否首次注入（Turn 0）
}
```

### 注入流程详解

```
┌─────────────────────────────────────────────────────────────────────┐
│                    skill_listing 注入流程                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [1] getAttachments() (attachments.ts:875)                          │
│      │                                                               │
│      └─> maybe('skill_listing', () => getSkillListingAttachments()) │
│                                                                      │
│  [2] getSkillListingAttachments() (attachments.ts:2661-2751)        │
│      │                                                               │
│      ├── getSkillToolCommands(cwd)  // 获取本地技能                  │
│      ├── getMcpSkillCommands()      // 获取 MCP 技能                 │
│      ├── sentSkillNames 跟踪        // 避免重复注入                  │
│      │                                                               │
│      └── formatCommandsWithinBudget() // 格式化，限制 1% context    │
│                                                                      │
│  [3] normalizeAttachmentForAPI() (messages.ts:3728-3738)            │
│      │                                                               │
│      └── 转换为 UserMessage，包装在 <system-reminder> 标签中         │
│                                                                      │
│  [4] 注入到 API 请求的 messages 数组                                 │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 最终格式（发送给 LLM 的内容）

```xml
<system-reminder>
The following skills are available for use with the Skill tool:

- commit: Create a git commit with staged changes
- review-pr: Review a pull request for quality
- doctor: Run diagnostic checks on your environment
- remember: Store information across sessions
- mcp: Manage MCP servers and tools
...
</system-reminder>
```

**关键特性**：

| 特性 | 实现 | 效果 |
|-----|-----|-----|
| **去重** | `sentSkillNames` Map 跟踪已发送技能 | 避免重复注入 |
| **Delta 更新** | 后续只注入新增技能 | 节省 context |
| **预算限制** | 1% context window，单条描述最多 250 字符 | 控制 token 消耗 |
| **优先级** | Bundled 技能优先保留完整描述 | 保证核心技能可见 |

### 关键代码

```typescript
// src/utils/attachments.ts:2661-2751
async function getSkillListingAttachments(
  toolUseContext: ToolUseContext,
): Promise<Attachment[]> {
  const cwd = getProjectRoot()
  const localCommands = await getSkillToolCommands(cwd)
  const mcpSkills = getMcpSkillCommands(toolUseContext.getAppState().mcp.commands)

  // 跟踪已发送的技能
  let sent = sentSkillNames.get(agentKey)
  if (!sent) {
    sent = new Set()
    sentSkillNames.set(agentKey, sent)
  }

  // 只发送新增的技能
  const newSkills = allCommands.filter(cmd => !sent.has(cmd.name))
  const isInitial = sent.size === 0  // 首次注入标记

  for (const cmd of newSkills) {
    sent.add(cmd.name)
  }

  // 格式化并返回
  const content = formatCommandsWithinBudget(newSkills, contextWindowTokens)
  return [{ type: 'skill_listing', content, skillCount: newSkills.length, isInitial }]
}
```

---

## 深度解析：内容按需加载机制

### 不同技能类型的加载时机

| 技能类型 | 内容加载时机 | 懒加载元素 |
|---------|------------|-----------|
| 文件技能 (`/skills/`) | **发现时** - 读取文件 | Shell 命令在调用时执行 |
| Bundled 简单 | 编译时内联 | Shell 命令在调用时执行 |
| Bundled 重型 (如 `/claude-api`) | **调用时** - 动态 import | 整个内容模块懒加载 |
| Built-in (如 `/insights`) | **调用时** - lazy shim | 整个命令模块懒加载 |

### getPromptForCommand() 处理流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    getPromptForCommand() 处理流程                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: args = "fix bug", skill markdown content                     │
│                                                                      │
│  [1] 参数替换 (substituteArguments)                                  │
│      ├── $ARGUMENTS → "fix bug"                                     │
│      ├── $ARGUMENTS[0] → "fix"                                      │
│      └── 命名参数 $message → "fix bug"                              │
│                                                                      │
│  [2] 变量替换                                                        │
│      ├── ${CLAUDE_SKILL_DIR} → /path/to/skill                       │
│      └── ${CLAUDE_SESSION_ID} → session-uuid                        │
│                                                                      │
│  [3] Shell 命令执行 (executeShellCommandsInPrompt)                  │
│      └── !`git status` → 实际执行并替换结果                          │
│                                                                      │
│  输出: ContentBlockParam[] = [{ type: 'text', text: finalContent }] │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 关键代码：createSkillCommand

```typescript
// src/skills/loadSkillsDir.ts:344-398
export function createSkillCommand({
  skillName,
  markdownContent,  // 发现时已读取
  baseDir,
  argumentNames,
  ...
}): Command {
  return {
    type: 'prompt',
    name: skillName,
    contentLength: markdownContent.length,
    async getPromptForCommand(args, toolUseContext) {
      // 1. 基础目录头部
      let finalContent = baseDir
        ? `Base directory for this skill: ${baseDir}\n\n${markdownContent}`
        : markdownContent

      // 2. 参数替换
      finalContent = substituteArguments(finalContent, args, true, argumentNames)

      // 3. 变量替换
      if (baseDir) {
        finalContent = finalContent.replace(/\$\{CLAUDE_SKILL_DIR\}/g, skillDir)
      }
      finalContent = finalContent.replace(/\$\{CLAUDE_SESSION_ID\}/g, getSessionId())

      // 4. Shell 命令执行
      finalContent = await executeShellCommandsInPrompt(finalContent, toolUseContext, ...)

      return [{ type: 'text', text: finalContent }]
    },
  }
}
```

### 缓存机制

```
┌─────────────────────────────────────────────────────────────────────┐
│                    缓存层次                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [发现缓存] lodash memoize                                           │
│  ├── getSkillDirCommands() - 文件系统 I/O 只做一次                   │
│  ├── loadAllCommands() - 命令聚合只做一次                            │
│  └── getSkillToolCommands() - 过滤只做一次                           │
│                                                                      │
│  [提取缓存] Promise memoization                                      │
│  └── extractionPromise ??= extractBundledSkillFiles()               │
│      // Bundled 技能的参考文件只提取一次                             │
│                                                                      │
│  [懒加载] 动态 import                                                │
│  └── 在 getPromptForCommand 内部 import('./heavyContent.js')        │
│      // 重型内容只在调用时加载                                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 深度解析：LLM 调用 Skill 的格式

### SkillTool 工具定义（发送给 API）

```json
{
  "name": "Skill",
  "description": "Execute a skill within the main conversation\n\nWhen users ask you to perform tasks, check if any of the available skills match...\n\nHow to invoke:\n- skill: \"pdf\" - invoke the pdf skill\n- skill: \"commit\", args: \"-m 'Fix bug'\" - invoke with arguments\n...",
  "input_schema": {
    "type": "object",
    "properties": {
      "skill": {
        "type": "string",
        "description": "The skill name. E.g., \"commit\", \"review-pr\", or \"pdf\""
      },
      "args": {
        "type": "string",
        "description": "Optional arguments for the skill"
      }
    },
    "required": ["skill"]
  }
}
```

### LLM 输出的 tool_use 块格式

**完整结构**：

```json
{
  "type": "tool_use",
  "id": "toolu_abc123",
  "name": "Skill",
  "input": {
    "skill": "commit",
    "args": "-m 'Fix bug'"
  }
}
```

**流式传输过程**：

```
event: content_block_start
data: {"index":0,"content_block":{"type":"tool_use","id":"toolu_abc123","name":"Skill"}}

event: content_block_delta
data: {"index":0,"delta":{"type":"input_json_delta","partial_json":"{\"skill\":"}}

event: content_block_delta
data: {"index":0,"delta":{"type":"input_json_delta","partial_json":"\"commit\""}}

event: content_block_delta
data: {"index":0,"delta":{"type":"input_json_delta","partial_json":",\"args\":\"-m 'Fix bug'\"}"}}

event: content_block_stop
data: {"index":0}
```

### Tool Result 返回格式

**Inline 技能**（默认）：

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_abc123",
  "content": "Launching skill: commit"
}
```

随后技能内容作为新消息注入对话。

**Forked 技能**（独立 Agent 执行）：

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_abc123",
  "content": "Skill \"heavy-analysis\" completed (forked execution).\n\nResult:\n[分析结果...]"
}
```

### 调用示例对照

| 用户输入 | LLM 输出的 tool_use |
|---------|-------------------|
| `/commit` | `{skill: "commit"}` |
| `/commit -m "fix bug"` | `{skill: "commit", args: "-m \"fix bug\""}` |
| `/review-pr 123` | `{skill: "review-pr", args: "123"}` |
| `/ms-office-suite:pdf` | `{skill: "ms-office-suite:pdf"}` |

---

## 关键代码解读

### 1. 技能加载器 getSkillDirCommands

```typescript
// 文件: src/skills/loadSkillsDir.ts

export const getSkillDirCommands = memoize(
  async (cwd: string): Promise<Command[]> => {
    // ===== 确定加载路径 =====
    const userSkillsDir = join(getClaudeConfigHomeDir(), 'skills')
    const managedSkillsDir = join(getManagedFilePath(), '.claude', 'skills')
    const projectSkillsDirs = getProjectDirsUpToHome('skills', cwd)

    // ===== 并行加载所有来源 =====
    const [
      managedSkills,
      userSkills,
      projectSkillsNested,
      legacyCommands,
    ] = await Promise.all([
      loadSkillsFromSkillsDir(managedSkillsDir, 'policySettings'),
      loadSkillsFromSkillsDir(userSkillsDir, 'userSettings'),
      Promise.all(projectSkillsDirs.map(dir =>
        loadSkillsFromSkillsDir(dir, 'projectSettings'),
      )),
      loadSkillsFromCommandsDir(cwd),  // 遗留格式
    ])

    // ===== 合并去重 =====
    const allSkillsWithPaths = [
      ...managedSkills,
      ...userSkills,
      ...projectSkillsNested.flat(),
      ...legacyCommands,
    ]

    // 使用 realpath 解析符号链接去重
    const fileIds = await Promise.all(
      allSkillsWithPaths.map(({ skill, filePath }) =>
        skill.type === 'prompt' ? getFileIdentity(filePath) : null,
      ),
    )

    // ===== 分离条件技能 =====
    const unconditionalSkills: Command[] = []
    const newConditionalSkills: Command[] = []

    for (const skill of deduplicatedSkills) {
      if (skill.paths && skill.paths.length > 0) {
        newConditionalSkills.push(skill)  // 等待路径匹配激活
      } else {
        unconditionalSkills.push(skill)
      }
    }

    return unconditionalSkills
  },
)
```

### 2. 参数替换 substituteArguments

```typescript
// 文件: src/utils/argumentSubstitution.ts

export function substituteArguments(
  content: string,
  args: string | undefined,
  argumentNames: string[] = [],
): string {
  if (args === undefined) return content

  const parsedArgs = parseArguments(args)  // shell-quote 解析

  // 替换命名参数: $name → parsedArgs[i]
  for (let i = 0; i < argumentNames.length; i++) {
    content = content.replace(
      new RegExp(`\\$${argumentNames[i]}(?![\\[\\w])`, 'g'),
      parsedArgs[i] ?? '',
    )
  }

  // 替换索引参数: $ARGUMENTS[0], $0
  content = content.replace(/\$ARGUMENTS\[(\d+)\]/g, (_, i) => parsedArgs[i] ?? '')
  content = content.replace(/\$(\d+)(?!\w)/g, (_, i) => parsedArgs[i] ?? '')

  // 替换完整参数: $ARGUMENTS
  content = content.replaceAll('$ARGUMENTS', args)

  return content
}
```

### 3. SkillTool 权限检查

```typescript
// 文件: src/tools/SkillTool/SkillTool.ts

async checkPermissions({ skill, args }, context): Promise<PermissionDecision> {
  const commandName = skill.startsWith('/') ? skill.substring(1) : skill
  const commandObj = findCommand(commandName, await getAllCommands(context))

  // 检查 deny 规则
  for (const [ruleContent, rule] of denyRules) {
    if (ruleMatches(ruleContent, commandName)) {
      return { behavior: 'deny', message: 'Skill blocked by permission rules' }
    }
  }

  // 检查 allow 规则
  for (const [ruleContent, rule] of allowRules) {
    if (ruleMatches(ruleContent, commandName)) {
      return { behavior: 'allow', updatedInput: { skill, args } }
    }
  }

  // 安全属性白名单
  if (skillHasOnlySafeProperties(commandObj)) {
    return { behavior: 'allow', updatedInput: { skill, args } }
  }

  // 默认：询问用户
  return { behavior: 'ask', message: `Execute skill: ${commandName}` }
}
```

---

## 设计亮点

### 1. Skills 系统独立性

Skills 作为独立系统设计：
- 自己的目录结构 (`src/skills/`)
- 自己的加载逻辑 (`loadSkillsDir.ts`)
- 自己的注册机制 (`bundledSkills.ts`)
- 与 Tools 系统通过 SkillTool 连接

**设计智慧**：职责分离，Skills 关注 prompt 模板管理，Tools 关注操作执行。

### 2. Command 类型统一抽象

Skills 和 CLI Commands 共享 `Command` 类型：

```typescript
type Command = CommandBase & (PromptCommand | LocalCommand | LocalJSXCommand)
```

**设计智慧**：
- 无论来自哪里，都通过 `getPromptForCommand()` 获取内容
- 易于添加新的技能来源
- 调用者无需关心技能来源

### 3. 条件激活模式（按需加载）

```typescript
paths: "src/**/*.ts"
// 只有操作 TypeScript 文件时才激活
```

**设计智慧**：
- 减少 token 消耗：不相关的技能不加载
- 使用 gitignore 风格匹配，用户熟悉

### 4. 安全属性白名单（默认拒绝）

```typescript
const SAFE_SKILL_PROPERTIES = new Set([
  'type', 'name', 'description', 'model', 'effort', ...
])
```

**设计智慧**：新增属性默认需要权限确认，防止恶意技能。

### 5. 内置技能懒加载

```typescript
// 内置技能编译到二进制
// 参考文件首次使用时才写入磁盘
extractionPromise ??= extractBundledSkillFiles(name, files)
```

**设计智慧**：减少启动延迟，按需加载参考文件。

---

## 完整示例：Agent 调用 /commit

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Agent 调用 /commit 示例                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Agent 看到:                                                         │
│  skill_listing: "- commit: Create a git commit..."                  │
│                                                                      │
│  Agent 决定: 调用 SkillTool({ skill: "commit", args: "fix bug" })   │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  validateInput(): 检查 commit 技能存在                               │
│                                                                      │
│  checkPermissions(): 内置技能，只有安全属性，自动放行                 │
│                                                                      │
│  call(): Inline 执行                                                 │
│  ├── getPromptForCommand() 获取 commit 技能内容                     │
│  ├── substituteArguments() 替换 $ARGUMENTS → "fix bug"              │
│  └── 返回 newMessages                                               │
│                                                                      │
│  结果: 技能内容展开到对话中                                          │
│  "Create a git commit with the message: fix bug                     │
│   Steps: 1. git status, 2. git diff, 3. git add, 4. commit"         │
│                                                                      │
│  Agent 收到 prompt，开始执行 git 操作                                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 文件路径索引

### Skills 系统核心
- `src/skills/loadSkillsDir.ts` - **技能目录加载器**
- `src/skills/bundledSkills.ts` - 内置技能注册 API
- `src/skills/bundled/index.ts` - 内置技能入口

### SkillTool（连接点）
- `src/tools/SkillTool/SkillTool.ts` - **SkillTool 主实现**
- `src/tools/SkillTool/prompt.ts` - 技能列表格式化

### 类型定义
- `src/types/command.ts` - **Command 类型定义**

### 技能聚合
- `src/commands.ts` - `getSkills()`, `getSkillToolCommands()`

### Agent 发现
- `src/utils/attachments.ts` - skill_listing attachment

### 辅助工具
- `src/utils/argumentSubstitution.ts` - 参数替换
- `src/utils/frontmatterParser.ts` - YAML 解析

---

## 总结

Claude Code 的 Skills 系统是一个独立的 prompt 模板命令系统：

| 特性 | 实现方式 | 效果 |
|------|---------|------|
| **系统独立性** | src/skills/ 目录，独立加载逻辑 | 职责分离 |
| **统一抽象** | Command 类型 | 简化复杂性 |
| **Agent 连接** | SkillTool | 模板展开到对话 |
| **条件激活** | paths frontmatter | 按需加载 |
| **安全默认** | 白名单权限检查 | 防止滥用 |
| **懒加载** | Promise 缓存 | 性能优化 |

**核心架构洞察**：

1. **系统提示词注入**：
   - 通过 `skill_listing` attachment 将技能列表注入 `<system-reminder>`
   - 首次注入全部，后续只注入新增（delta）
   - 预算限制 1% context window

2. **内容加载时机**：
   - 文件技能：发现时读取内容，调用时执行 Shell 命令
   - Bundled 重型：调用时动态 import，整个模块懒加载
   - 缓存层次：memoize（发现）+ Promise memoization（提取）+ 动态 import（调用）

3. **LLM 调用格式**：
   - SkillTool 作为单一工具发送给 API
   - LLM 输出 `{type: "tool_use", name: "Skill", input: {skill, args}}`
   - 流式传输 JSON 片段，累积后解析执行

这个设计让用户可以通过简单的 Markdown 文件扩展 Claude 的能力，形成丰富的技能生态系统。