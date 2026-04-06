# Claude Code 技能系统深度分析报告

## 模块概述（通俗开场）

### 一句话角色定位

**技能系统是 Claude Code 的"可扩展指令库"**——它像一个智能助手随身携带的工具箱，用户可以随时添加新的"技能手册"，让助手学会新的工作流程。

### 核心职责

想象一个智能助手的工具箱：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code 技能系统                            │
├─────────────────────────────────────────────────────────────────┤
│  1. 【技能发现】    从多个来源发现可用的技能                         │
│  2. 【元数据解析】  读取技能的名称、描述、参数等信息                  │
│  3. 【条件激活】    根据文件路径自动激活相关技能                     │
│  4. 【内容展开】    将技能内容注入到对话中                          │
│  5. 【参数替换】    将用户参数填充到技能模板                        │
│  6. 【权限控制】    确保技能安全执行                                │
└─────────────────────────────────────────────────────────────────┘
```

### 与其他模块的关系图

```
                    ┌──────────────┐
                    │  QueryEngine │  ← 调用 SkillTool
                    │  (查询引擎)   │
                    └──────┬───────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │                    SkillTool                         │
    │                   (技能工具)                          │
    ├─────────────────────────────────────────────────────┤
    │                                                      │
    │   技能来源                  执行模式                  │
    │  ┌─────────────┐         ┌─────────────┐            │
    │  │ Bundled    │         │ Inline      │            │
    │  │ (内置)     │ ───────→│ (内联展开)   │            │
    │  │            │         └─────────────┘            │
    │  │ User/Project│        ┌─────────────┐            │
    │  │ (用户/项目) │ ───────→│ Fork        │            │
    │  │            │         │ (子Agent执行)│            │
    │  │ Plugin    │          └─────────────┘            │
    │  │ (插件)     │                                     │
    │  │            │                                     │
    │  │ MCP       │                                     │
    │  │ (远程)     │                                     │
    │  └─────────────┘                                     │
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

## 核心概念（生活化类比）

### 1. Skill（技能）—— 可执行的指令手册

技能就像一本详细的操作手册，告诉 Claude 如何完成特定任务：

```
┌─────────────────────────────────────────────────────────────────┐
│                    技能结构示例                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  文件: skills/review-pr/SKILL.md                                │
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
│  3. Check for:                                                  │
│     - Security vulnerabilities                                  │
│     - Code quality issues                                       │
│     - Test coverage                                             │
│  4. Provide a summary with recommendations                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**生活类比**：技能就像给助手一张"任务卡片"——上面写着任务目标、可用工具、具体步骤。

### 2. Frontmatter（前置元数据）—— 技能的"身份证"

每个技能文件开头都有 YAML 格式的元数据：

```yaml
---
name: commit                    # 技能名称
description: Create a commit    # 简短描述
argument-hint: <message>        # 参数提示
arguments: message scope        # 命名参数
allowed-tools: [Bash, Read]     # 允许使用的工具
model: haiku                    # 模型覆盖
context: fork                   # 执行模式：inline/fork
agent: general-purpose          # Fork 时使用的 Agent 类型
paths: "src/**/*.ts"            # 条件激活路径
hooks:                          # 技能触发时的 Hook
  PreToolUse: [...]
---
```

**生活类比**：就像药品包装盒上的说明书——名称、用途、用法、禁忌都写得清清楚楚。

### 3. 执行模式（Inline vs Fork）—— 两种工作方式

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

### 4. 参数替换（$ARGUMENTS）—— 动态内容填充

技能支持多种参数占位符：

```
┌─────────────────────────────────────────────────────────────────┐
│                    参数占位符语法                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
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
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5. 技能来源（5 种来源）

```
┌─────────────────────────────────────────────────────────────────┐
│                    技能来源层次                                    │
├──────────────┬──────────────────────────────────────────────────┤
│    来源      │                    说明                          │
├──────────────┼──────────────────────────────────────────────────┤
│  bundled     │  内置技能，编译到 CLI 中，所有用户可用            │
│  policySettings│ 企业策略配置，由管理员定义                     │
│  userSettings │ 用户全局技能，~/.claude/skills/                 │
│  projectSettings│ 项目技能，.claude/skills/                     │
│  plugin      │ 插件提供的技能                                    │
│  mcp         │ MCP 服务器提供的远程技能                          │
└──────────────┴──────────────────────────────────────────────────┘
```

### 6. 条件激活（paths）—— 按需加载

技能可以声明 `paths` 属性，只有当操作匹配这些路径时才激活：

```yaml
---
name: typescript-helper
paths: "src/**/*.ts"
---
```

**生活类比**：就像智能音箱的"场景模式"——只有当你在特定场景（如"正在编辑 TypeScript 文件"）时，相关技能才会被唤醒。

---

## 完整工作流程（数据流图）

### 技能发现与加载流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    技能发现与加载流程                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  启动时: getSkillDirCommands(cwd)                                   │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第一阶段：并行加载                                                   │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [1] 加载管理技能 (policySettings)                                   │
│       ~/.claude-policy/skills/                                      │
│       ↓                                                             │
│       loadSkillsFromSkillsDir(managedSkillsDir)                     │
│                                                                      │
│  [2] 加载用户技能 (userSettings)                                     │
│       ~/.claude/skills/                                              │
│       ↓                                                             │
│       loadSkillsFromSkillsDir(userSkillsDir)                        │
│                                                                      │
│  [3] 加载项目技能 (projectSettings)                                  │
│       .claude/skills/ (从 cwd 向上遍历)                             │
│       ↓                                                             │
│       loadSkillsFromSkillsDir(projectSkillsDir)                     │
│                                                                      │
│  [4] 加载额外目录技能 (--add-dir)                                    │
│       ↓                                                             │
│       loadSkillsFromSkillsDir(additionalDir)                        │
│                                                                      │
│  [5] 加载遗留命令 (commands_DEPRECATED)                              │
│       .claude/commands/                                              │
│       ↓                                                             │
│       loadSkillsFromCommandsDir(cwd)                                │
│                                                                      │
│  [6] 注册内置技能 (bundled)                                         │
│       已在模块初始化时通过 registerBundledSkill() 注册               │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第二阶段：合并去重                                                   │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [7] 解析文件真实路径                                                │
│       realpath(filePath) → 处理符号链接                             │
│                                                                      │
│  [8] 去重                                                            │
│       同一文件只保留第一个加载的来源                                  │
│       避免符号链接导致的重复                                          │
│                                                                      │
│  [9] 分离条件技能                                                    │
│       有 paths 属性 → conditionalSkills Map                         │
│       无 paths 属性 → 直接可用技能列表                               │
│                                                                      │
│  输出: Command[] 可用技能列表                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 技能执行流程（SkillTool）

```
┌─────────────────────────────────────────────────────────────────────┐
│                    技能执行完整流程                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: skill="review-pr", args="123"                                │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第一阶段：验证                                                       │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [1] validateInput()                                                 │
│       ├── 检查技能名称格式                                           │
│       ├── 移除前导斜杠 (/review-pr → review-pr)                     │
│       ├── 查找技能是否存在                                           │
│       └── 检查是否禁止模型调用                                        │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第二阶段：权限检查                                                   │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [2] checkPermissions()                                              │
│       ├── 检查 deny 规则 → 命中则拒绝                               │
│       ├── 检查 allow 规则 → 命中则放行                               │
│       ├── 检查安全属性白名单                                         │
│       │    └── 只有安全属性 → 自动放行                              │
│       └── 默认 → 弹出确认对话框                                      │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第三阶段：执行                                                       │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [3] call() - 主执行函数                                             │
│       │                                                              │
│       ├── context === 'fork' ?                                      │
│       │   │                                                          │
│       │   ├── YES: executeForkedSkill()                             │
│       │   │   ├── prepareForkedCommandContext()                     │
│       │   │   ├── 创建独立 Agent                                     │
│       │   │   ├── runAgent() 多轮执行                                │
│       │   │   └── 返回 {status: 'forked', result}                   │
│       │   │                                                          │
│       │   └── NO: Inline 执行                                        │
│       │       │                                                      │
│       │       ├── processPromptSlashCommand()                       │
│       │       │   ├── getPromptForCommand()                         │
│       │       │   │   ├── substituteArguments() 参数替换            │
│       │       │   │   ├── 替换 ${CLAUDE_SKILL_DIR}                  │
│       │       │   │   ├── 替换 ${CLAUDE_SESSION_ID}                 │
│       │       │   │   └── executeShellCommandsInPrompt()            │
│       │       │   └── 返回处理后的内容                               │
│       │       │                                                      │
│       │       └── 返回 newMessages + contextModifier                │
│       │                                                              │
│  ══════════════════════════════════════════════════════════════════ │
│  第四阶段：上下文修改                                                 │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [4] contextModifier() - 修改后续执行上下文                          │
│       ├── allowedTools → 添加到 alwaysAllowRules                    │
│       ├── model → 覆盖后续查询使用的模型                             │
│       └── effort → 设置思考努力级别                                  │
│                                                                      │
│  输出: ToolResult { success, commandName, newMessages?, ... }        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 条件技能激活流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    条件技能激活流程                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  触发: Read/Write/Edit 工具操作文件                                  │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [1] activateConditionalSkillsForPaths(filePaths, cwd)              │
│       │                                                              │
│       ▼                                                              │
│                                                                      │
│  [2] 遍历 conditionalSkills Map                                      │
│       │                                                              │
│       │  for each (name, skill) in conditionalSkills:               │
│       │   │                                                          │
│       │   ▼                                                          │
│       │                                                              │
│       │  [3] 构建 ignore 匹配器                                      │
│       │       skillIgnore = ignore().add(skill.paths)               │
│       │       │                                                      │
│       │       ▼                                                      │
│       │                                                              │
│       │  [4] 检查每个文件路径                                        │
│       │       for each filePath in filePaths:                       │
│       │         │                                                    │
│       │         ├── 计算相对路径                                     │
│       │         │   relativePath = relative(cwd, filePath)          │
│       │         │                                                    │
│       │         ├── 路径检查                                         │
│       │         │   ├── 空路径 → 跳过                               │
│       │         │   ├── 以 .. 开头 → 跳过                           │
│       │         │   └── 绝对路径 → 跳过                              │
│       │         │                                                    │
│       │         └── 模式匹配                                         │
│       │             if skillIgnore.ignores(relativePath):           │
│       │               │                                              │
│       │               ├── 激活技能                                   │
│       │               │   dynamicSkills.set(name, skill)            │
│       │               │                                              │
│       │               ├── 从待激活列表移除                           │
│       │               │   conditionalSkills.delete(name)            │
│       │               │                                              │
│       │               └── 记录已激活                                 │
│       │                   activatedConditionalSkillNames.add(name)  │
│       │                                                              │
│       ▼                                                              │
│                                                                      │
│  [5] 发送技能变更信号                                                │
│       skillsLoaded.emit()                                           │
│                                                                      │
│  结果: 匹配的技能被添加到 dynamicSkills，可在后续查询中使用           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 关键代码解读（逐行注释）

### 1. 技能加载器 getSkillDirCommands

```typescript
// 文件: src/skills/loadSkillsDir.ts
// 行号: 638-803

export const getSkillDirCommands = memoize(
  async (cwd: string): Promise<Command[]> => {
    // ===== 第一阶段：确定加载路径 =====

    // 用户全局技能目录
    const userSkillsDir = join(getClaudeConfigHomeDir(), 'skills')
    // 企业管理技能目录
    const managedSkillsDir = join(getManagedFilePath(), '.claude', 'skills')
    // 项目技能目录（从 cwd 向上遍历到 home）
    const projectSkillsDirs = getProjectDirsUpToHome('skills', cwd)

    // ===== 第二阶段：并行加载所有来源 =====

    // 并行加载 5 种来源的技能
    const [
      managedSkills,        // 企业策略技能
      userSkills,           // 用户全局技能
      projectSkillsNested,  // 项目技能（可能有多个父目录）
      additionalSkillsNested, // --add-dir 技能
      legacyCommands,       // 遗留 /commands/ 目录
    ] = await Promise.all([
      // 企业技能：检查环境变量禁用
      isEnvTruthy(process.env.CLAUDE_CODE_DISABLE_POLICY_SKILLS)
        ? Promise.resolve([])
        : loadSkillsFromSkillsDir(managedSkillsDir, 'policySettings'),

      // 用户技能：检查设置源启用
      isSettingSourceEnabled('userSettings') && !skillsLocked
        ? loadSkillsFromSkillsDir(userSkillsDir, 'userSettings')
        : Promise.resolve([]),

      // 项目技能：检查设置源启用
      projectSettingsEnabled
        ? Promise.all(
            projectSkillsDirs.map(dir =>
              loadSkillsFromSkillsDir(dir, 'projectSettings'),
            ),
          )
        : Promise.resolve([]),

      // 额外目录技能
      projectSettingsEnabled
        ? Promise.all(
            additionalDirs.map(dir =>
              loadSkillsFromSkillsDir(join(dir, '.claude', 'skills'), 'projectSettings'),
            ),
          )
        : Promise.resolve([]),

      // 遗留命令格式
      skillsLocked ? Promise.resolve([]) : loadSkillsFromCommandsDir(cwd),
    ])

    // ===== 第三阶段：合并去重 =====

    // 合并所有技能
    const allSkillsWithPaths = [
      ...managedSkills,
      ...userSkills,
      ...projectSkillsNested.flat(),
      ...additionalSkillsNested.flat(),
      ...legacyCommands,
    ]

    // 并行解析文件真实路径（处理符号链接）
    const fileIds = await Promise.all(
      allSkillsWithPaths.map(({ skill, filePath }) =>
        skill.type === 'prompt'
          ? getFileIdentity(filePath)  // realpath() 解析
          : Promise.resolve(null),
      ),
    )

    // 去重：同一文件只保留第一个
    const seenFileIds = new Map<string, SettingSource>()
    const deduplicatedSkills: Command[] = []

    for (let i = 0; i < allSkillsWithPaths.length; i++) {
      const entry = allSkillsWithPaths[i]
      if (entry?.skill.type !== 'prompt') continue

      const { skill } = entry
      const fileId = fileIds[i]

      // 文件不存在或无法解析：直接添加
      if (fileId === null || fileId === undefined) {
        deduplicatedSkills.push(skill)
        continue
      }

      // 已存在：跳过重复
      const existingSource = seenFileIds.get(fileId)
      if (existingSource !== undefined) {
        logForDebugging(`Skipping duplicate skill '${skill.name}'`)
        continue
      }

      seenFileIds.set(fileId, skill.source)
      deduplicatedSkills.push(skill)
    }

    // ===== 第四阶段：分离条件技能 =====

    const unconditionalSkills: Command[] = []
    const newConditionalSkills: Command[] = []

    for (const skill of deduplicatedSkills) {
      // 有 paths 属性且未激活 → 条件技能
      if (
        skill.type === 'prompt' &&
        skill.paths &&
        skill.paths.length > 0 &&
        !activatedConditionalSkillNames.has(skill.name)
      ) {
        newConditionalSkills.push(skill)
      } else {
        unconditionalSkills.push(skill)
      }
    }

    // 存储条件技能，等待路径匹配时激活
    for (const skill of newConditionalSkills) {
      conditionalSkills.set(skill.name, skill)
    }

    return unconditionalSkills
  },
)
```

### 2. 参数替换 substituteArguments

```typescript
// 文件: src/utils/argumentSubstitution.ts
// 行号: 94-145

export function substituteArguments(
  content: string,          // 技能原始内容
  args: string | undefined, // 用户传入的参数
  appendIfNoPlaceholder = true,
  argumentNames: string[] = [],  // 命名参数定义
): string {
  // 无参数：直接返回原内容
  if (args === undefined || args === null) {
    return content
  }

  // 使用 shell-quote 解析参数（支持引号、转义）
  const parsedArgs = parseArguments(args)
  const originalContent = content

  // ===== 替换命名参数 =====
  // 如果定义了 arguments: foo bar
  // 则 $foo → parsedArgs[0], $bar → parsedArgs[1]
  for (let i = 0; i < argumentNames.length; i++) {
    const name = argumentNames[i]
    if (!name) continue

    // 匹配 $name 但不匹配 $name[...] 或 $nameXxx
    content = content.replace(
      new RegExp(`\\$${name}(?![\\[\\w])`, 'g'),
      parsedArgs[i] ?? '',
    )
  }

  // ===== 替换索引参数 =====
  // $ARGUMENTS[0], $ARGUMENTS[1], ...
  content = content.replace(/\$ARGUMENTS\[(\d+)\]/g, (_, indexStr: string) => {
    const index = parseInt(indexStr, 10)
    return parsedArgs[index] ?? ''
  })

  // ===== 替换简写索引参数 =====
  // $0, $1, $2, ...
  content = content.replace(/\$(\d+)(?!\w)/g, (_, indexStr: string) => {
    const index = parseInt(indexStr, 10)
    return parsedArgs[index] ?? ''
  })

  // ===== 替换完整参数 =====
  // $ARGUMENTS → 完整参数字符串
  content = content.replaceAll('$ARGUMENTS', args)

  // ===== 无占位符处理 =====
  // 如果内容中没有找到任何占位符，追加参数说明
  if (content === originalContent && appendIfNoPlaceholder && args) {
    content = content + `\n\nARGUMENTS: ${args}`
  }

  return content
}
```

### 3. SkillTool 权限检查

```typescript
// 文件: src/tools/SkillTool/SkillTool.ts
// 行号: 432-578

async checkPermissions(
  { skill, args },
  context,
): Promise<PermissionDecision> {
  const trimmed = skill.trim()
  const commandName = trimmed.startsWith('/') ? trimmed.substring(1) : trimmed

  const appState = context.getAppState()
  const permissionContext = appState.toolPermissionContext

  // 查找技能对象
  const commands = await getAllCommands(context)
  const commandObj = findCommand(commandName, commands)

  // ===== 辅助函数：规则匹配 =====
  const ruleMatches = (ruleContent: string): boolean => {
    const normalizedRule = ruleContent.startsWith('/')
      ? ruleContent.substring(1)
      : ruleContent

    // 精确匹配
    if (normalizedRule === commandName) return true

    // 前缀匹配 (review:* 匹配 review-pr)
    if (normalizedRule.endsWith(':*')) {
      const prefix = normalizedRule.slice(0, -2)
      return commandName.startsWith(prefix)
    }
    return false
  }

  // ===== 检查 deny 规则 =====
  const denyRules = getRuleByContentsForTool(permissionContext, SkillTool, 'deny')
  for (const [ruleContent, rule] of denyRules.entries()) {
    if (ruleMatches(ruleContent)) {
      return {
        behavior: 'deny',
        message: `Skill execution blocked by permission rules`,
        decisionReason: { type: 'rule', rule },
      }
    }
  }

  // ===== 检查 allow 规则 =====
  const allowRules = getRuleByContentsForTool(permissionContext, SkillTool, 'allow')
  for (const [ruleContent, rule] of allowRules.entries()) {
    if (ruleMatches(ruleContent)) {
      return {
        behavior: 'allow',
        updatedInput: { skill, args },
        decisionReason: { type: 'rule', rule },
      }
    }
  }

  // ===== 安全属性白名单 =====
  // 如果技能只有"安全"属性，自动放行
  if (commandObj?.type === 'prompt' && skillHasOnlySafeProperties(commandObj)) {
    return {
      behavior: 'allow',
      updatedInput: { skill, args },
    }
  }

  // ===== 默认：询问用户 =====
  // 生成权限建议
  const suggestions = [
    // 精确匹配建议
    {
      type: 'addRules' as const,
      rules: [{ toolName: SKILL_TOOL_NAME, ruleContent: commandName }],
      behavior: 'allow' as const,
      destination: 'localSettings' as const,
    },
    // 前缀匹配建议
    {
      type: 'addRules' as const,
      rules: [{ toolName: SKILL_TOOL_NAME, ruleContent: `${commandName}:*` }],
      behavior: 'allow' as const,
      destination: 'localSettings' as const,
    },
  ]

  return {
    behavior: 'ask',
    message: `Execute skill: ${commandName}`,
    suggestions,
    updatedInput: { skill, args },
    metadata: commandObj ? { command: commandObj } : undefined,
  }
}
```

### 4. Fork 模式执行

```typescript
// 文件: src/tools/SkillTool/SkillTool.ts
// 行号: 122-289

async function executeForkedSkill(
  command: Command & { type: 'prompt' },
  commandName: string,
  args: string | undefined,
  context: ToolUseContext,
  canUseTool: CanUseToolFn,
  parentMessage: AssistantMessage,
  onProgress?: ToolCallProgress<Progress>,
): Promise<ToolResult<Output>> {

  const startTime = Date.now()
  const agentId = createAgentId()

  // ===== 准备 Fork 上下文 =====
  const { modifiedGetAppState, baseAgent, promptMessages, skillContent } =
    await prepareForkedCommandContext(command, args || '', context)

  // 合并 effort 设置
  const agentDefinition = command.effort !== undefined
    ? { ...baseAgent, effort: command.effort }
    : baseAgent

  const agentMessages: Message[] = []

  try {
    // ===== 运行子 Agent =====
    for await (const message of runAgent({
      agentDefinition,
      promptMessages,
      toolUseContext: {
        ...context,
        getAppState: modifiedGetAppState,
      },
      canUseTool,
      isAsync: false,
      querySource: 'agent:custom',
      model: command.model as ModelAlias | undefined,
      availableTools: context.options.tools,
      override: { agentId },
    })) {
      agentMessages.push(message)

      // 报告进度
      if ((message.type === 'assistant' || message.type === 'user') && onProgress) {
        const normalizedNew = normalizeMessages([message])
        for (const m of normalizedNew) {
          const hasToolContent = m.message.content.some(
            c => c.type === 'tool_use' || c.type === 'tool_result',
          )
          if (hasToolContent) {
            onProgress({
              toolUseID: `skill_${parentMessage.message.id}`,
              data: {
                message: m,
                type: 'skill_progress',
                prompt: skillContent,
                agentId,
              },
            })
          }
        }
      }
    }

    // ===== 提取结果 =====
    const resultText = extractResultText(agentMessages, 'Skill execution completed')
    agentMessages.length = 0  // 释放内存

    return {
      data: {
        success: true,
        commandName,
        status: 'forked',
        agentId,
        result: resultText,
      },
    }
  } finally {
    // 清理状态
    clearInvokedSkillsForAgent(agentId)
  }
}
```

---

## 设计亮点（工程智慧）

### 1. 多源统一抽象（简化复杂性）

所有技能来源被统一为 `Command` 类型：

```typescript
type Command = CommandBase & (
  | PromptCommand   // Markdown 技能
  | LocalCommand    // 本地 JS 命令
  | LocalJSXCommand // 本地 JSX 命令
)
```

**设计智慧**：
- 无论来自哪里，都通过 `getPromptForCommand()` 获取内容
- 调用者无需关心技能来源
- 易于添加新的技能来源

### 2. 条件激活模式（按需加载）

```typescript
// 技能声明 paths 属性
paths: "src/**/*.ts"

// 只有操作 TypeScript 文件时才激活
activateConditionalSkillsForPaths(['src/utils/foo.ts'], cwd)
```

**设计智慧**：
- 减少 token 消耗：不相关的技能不加载
- 提高准确性：只在相关上下文中显示
- 使用 gitignore 风格匹配，用户熟悉

### 3. 安全属性白名单（默认拒绝）

```typescript
const SAFE_SKILL_PROPERTIES = new Set([
  'type', 'name', 'description', 'model', 'effort', ...
])

function skillHasOnlySafeProperties(command: Command): boolean {
  for (const key of Object.keys(command)) {
    if (!SAFE_SKILL_PROPERTIES.has(key)) {
      // 有未知属性 → 需要权限确认
      return false
    }
  }
  return true
}
```

**设计智慧**：
- 新增属性默认需要权限确认
- 防止恶意技能利用未知属性
- 安全默认值原则

### 4. 内置技能懒加载（性能优化）

```typescript
type BundledSkillDefinition = {
  files?: Record<string, string>  // 文件内容嵌入
  getPromptForCommand: ...
}

// 首次调用时提取文件
let extractionPromise: Promise<string | null> | undefined
getPromptForCommand = async (args, ctx) => {
  extractionPromise ??= extractBundledSkillFiles(name, files)
  const extractedDir = await extractionPromise
  // ...
}
```

**设计智慧**：
- 内置技能编译到二进制中
- 参考文件首次使用时才写入磁盘
- 使用 Promise 缓存避免重复提取

### 5. 符号链接去重（正确性保证）

```typescript
async function getFileIdentity(filePath: string): Promise<string | null> {
  try {
    return await realpath(filePath)  // 解析符号链接
  } catch {
    return null
  }
}

// 使用解析后的路径去重
const seenFileIds = new Map<string, SettingSource>()
```

**设计智慧**：
- 同一文件可能通过多个路径访问（符号链接、父目录重叠）
- 使用 `realpath` 获取真实路径
- 避免同一技能被加载多次

### 6. 动态技能发现（灵活性）

```typescript
// 操作文件时动态发现嵌套的技能目录
export async function discoverSkillDirsForPaths(filePaths: string[], cwd: string) {
  // 从文件路径向上遍历，查找 .claude/skills/
  while (currentDir.startsWith(resolvedCwd + pathSep)) {
    const skillDir = join(currentDir, '.claude', 'skills')
    if (await fs.stat(skillDir)) {
      newDirs.push(skillDir)
    }
    currentDir = dirname(currentDir)
  }
}
```

**设计智慧**：
- 嵌套项目可以有自己的技能
- 操作文件时自动发现相关技能
- Gitignore 检查避免加载 node_modules 中的技能

---

## 完整示例：一次技能调用的完整流程

假设用户执行 `/commit fix: update login logic`：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    技能调用完整示例                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  用户输入: /commit fix: update login logic                           │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  Step 1: 输入处理                                                    │
│          skill = "commit"                                            │
│          args = "fix: update login logic"                           │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  Step 2: validateInput()                                             │
│          ├── 移除前导斜杠: commit                                    │
│          ├── 查找技能: 找到内置 commit 技能                          │
│          └── 检查类型: type === 'prompt' ✓                          │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  Step 3: checkPermissions()                                          │
│          ├── 内置技能                                                │
│          ├── 只有安全属性                                            │
│          └── 返回 { behavior: 'allow' }                             │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  Step 4: call() - Inline 执行                                        │
│          │                                                           │
│          ├── processPromptSlashCommand("commit", args)              │
│          │   │                                                       │
│          │   ├── getPromptForCommand()                              │
│          │   │   ├── 获取 commit 技能内容                           │
│          │   │   ├── substituteArguments()                          │
│          │   │   │   └── $ARGUMENTS → "fix: update login logic"    │
│          │   │   └── 返回处理后的提示                               │
│          │   │                                                       │
│          │   └── addInvokedSkill() - 注册到会话状态                  │
│          │                                                           │
│          └── 返回 newMessages                                       │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  Step 5: contextModifier()                                           │
│          └── 无修改（commit 技能未指定 allowedTools）                 │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  Step 6: 结果                                                        │
│          newMessages 注入到对话中                                    │
│          Claude 收到技能内容，开始执行 git commit 流程                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**技能内容展开示例**：

```
原始技能内容:
---
name: commit
argument-hint: <message>
---

Create a git commit with the message: $ARGUMENTS

Steps:
1. Run `git status` to see what changed
2. Run `git diff` to understand the changes
3. Stage relevant files with `git add`
4. Create the commit

展开后:
Create a git commit with the message: fix: update login logic

Steps:
1. Run `git status` to see what changed
2. Run `git diff` to understand the changes
3. Stage relevant files with `git add`
4. Create the commit
```

---

## 文件路径索引

### 核心工具
- `src/tools/SkillTool/SkillTool.ts` - **SkillTool 主实现**
- `src/tools/SkillTool/constants.ts` - 常量定义
- `src/tools/SkillTool/prompt.ts` - 技能列表格式化

### 技能加载
- `src/skills/loadSkillsDir.ts` - **技能目录加载器**
- `src/skills/bundledSkills.ts` - 内置技能注册 API
- `src/skills/mcpSkillBuilders.ts` - MCP 技能构建器

### 内置技能
- `src/skills/bundled/index.ts` - 内置技能入口
- `src/skills/bundled/commit.ts` - Git 提交技能
- `src/skills/bundled/review-pr.ts` - PR 审核技能
- `src/skills/bundled/loop.ts` - 循环执行技能
- `src/skills/bundled/remember.ts` - 记忆技能
- ... 更多内置技能

### 类型定义
- `src/types/command.ts` - **Command 类型定义**
- `src/types/permissions.ts` - 权限相关类型

### 辅助工具
- `src/utils/argumentSubstitution.ts` - **$ARGUMENTS 参数替换**
- `src/utils/frontmatterParser.ts` - YAML Frontmatter 解析器
- `src/utils/promptShellExecution.ts` - 技能内 Shell 命令执行

---

## 总结

Claude Code 的技能系统是一个精心设计的可扩展框架：

| 特性 | 实现方式 | 效果 |
|------|---------|------|
| **多源统一** | Command 类型抽象 | 简化复杂性 |
| **条件激活** | paths frontmatter | 按需加载 |
| **安全默认** | 白名单权限检查 | 防止滥用 |
| **懒加载** | Promise 缓存 | 性能优化 |
| **符号链接去重** | realpath 解析 | 正确性保证 |
| **动态发现** | 文件操作触发 | 灵活性 |

这个系统让用户可以通过简单的 Markdown 文件扩展 Claude 的能力，而无需修改源码。技能可以来自用户、项目、插件或 MCP 服务器，形成了一个丰富的技能生态系统。