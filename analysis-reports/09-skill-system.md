# Claude Code 技能系统深度分析报告

## 1. 模块概述

Claude Code 的技能系统是一个多层次的、可扩展的命令执行框架，核心职责：

1. **技能发现与加载**：从多个来源发现和加载技能
2. **YAML Frontmatter解析**：解析技能的元数据配置
3. **条件激活**：基于文件路径模式动态激活技能
4. **执行模式**：支持Inline（内联展开）和Fork（子代理执行）
5. **权限控制**：技能调用需要权限确认
6. **MCP集成**：从MCP服务器发现和调用远程技能

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        SkillTool (入口)                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Inline执行     │  │  Fork执行       │  │  远程技能       │
│ (内容展开)      │  │ (子代理)        │  │ (AKI/GCS)       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     技能发现与加载层                              │
│  loadSkillsDir.ts | bundledSkills.ts | mcpSkillBuilders.ts      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心组件分析

### 2.1 YAML Frontmatter解析

**FrontmatterData 类型定义**：
```typescript
type FrontmatterData = {
  'allowed-tools'?: string | string[] | null
  description?: string | null
  model?: string | null  // 'haiku', 'sonnet', 'opus', 'inherit'
  context?: 'inline' | 'fork' | null  // 执行上下文
  agent?: string | null  // Fork时使用的代理类型
  paths?: string | string[] | null  // 条件激活路径
  hooks?: HooksSettings | null
  effort?: string | null  // 思考努力级别
  shell?: string | null  // 'bash' 或 'powershell'
}
```

### 2.2 技能类型系统

**PromptCommand（核心技能类型）**：
```typescript
type PromptCommand = {
  type: 'prompt'
  progressMessage: string
  allowedTools?: string[]
  model?: string
  source: SettingSource | 'builtin' | 'mcp' | 'plugin' | 'bundled'
  context?: 'inline' | 'fork'
  agent?: string
  paths?: string[]
  getPromptForCommand(args, context): Promise<ContentBlockParam[]>
}
```

### 2.3 技能加载器

**多源并行加载**：
```typescript
const [managedSkills, userSkills, projectSkills, additionalSkills, legacyCommands] =
  await Promise.all([
    loadSkillsFromSkillsDir(managedSkillsDir, 'policySettings'),
    loadSkillsFromSkillsDir(userSkillsDir, 'userSettings'),
    loadSkillsFromSkillsDir(projectSkillsDir, 'projectSettings'),
    loadSkillsFromSkillsDir(additionalDir, 'projectSettings'),
    loadSkillsFromCommandsDir(cwd),
  ])
```

**技能来源**：
- `bundled` - 内置技能，编译到CLI中
- `skills` - 用户/项目技能目录
- `plugin` - 插件提供的技能
- `mcp` - MCP服务器提供的技能

### 2.4 条件技能激活

```typescript
export function activateConditionalSkillsForPaths(filePaths: string[], cwd: string) {
  for (const [name, skill] of conditionalSkills) {
    const skillIgnore = ignore().add(skill.paths)
    for (const filePath of filePaths) {
      if (skillIgnore.ignores(relativePath)) {
        dynamicSkills.set(name, skill)
        conditionalSkills.delete(name)
      }
    }
  }
}
```

---

## 3. 关键代码解读

### 3.1 SkillTool 执行流程

**权限检查**：
```typescript
async checkPermissions({ skill, args }, context) {
  // 安全属性白名单 - 仅包含这些属性的技能自动放行
  const SAFE_SKILL_PROPERTIES = new Set([
    'type', 'progressMessage', 'contentLength', 'argNames', 'model', ...
  ])

  if (skillHasOnlySafeProperties(commandObj)) {
    return { behavior: 'allow' }
  }

  return { behavior: 'ask', message: `Execute skill: ${commandName}` }
}
```

**Forked执行**：
```typescript
async function executeForkedSkill(command, args, context) {
  const { modifiedGetAppState, promptMessages } =
    await prepareForkedCommandContext(command, args, context)

  // 运行子代理
  for await (const message of runAgent({
    agentDefinition,
    promptMessages,
    toolUseContext: { ...context, getAppState: modifiedGetAppState },
  })) {
    agentMessages.push(message)
  }

  return { data: { success: true, status: 'forked', result: resultText } }
}
```

### 3.2 参数替换系统

**支持的占位符**：
```typescript
// $ARGUMENTS - 完整参数字符串
// $ARGUMENTS[0], $ARGUMENTS[1] - 索引参数
// $0, $1 - 索引参数简写
// $foo, $bar - 命名参数

export function substituteArguments(content, args, argumentNames) {
  const parsedArgs = parseArguments(args)  // shell-quote解析

  // 替换命名参数、索引参数、完整参数
  content = content.replace(/\$ARGUMENTS\[(\d+)\]/g, ...)
  content = content.replace(/\$(\d+)(?!\w)/g, ...)
  content = content.replaceAll('$ARGUMENTS', args)

  return content
}
```

### 3.3 Shell命令执行

技能内容中可以嵌入Shell命令：

**支持的语法**：
- 代码块：```! command ```
- 内联：!`command`

**安全约束**：MCP技能不执行shell命令（远程不可信）

---

## 4. 设计亮点

### 4.1 多源统一抽象

技能系统将5种不同来源的技能统一为 `Command` 类型，无论来源如何，都通过相同的 `getPromptForCommand()` API 获取内容。

### 4.2 条件激活模式

通过 `paths` frontmatter 实现技能的条件激活：
```yaml
---
paths: "src/**/*.ts"
---
```

只有当模型操作匹配路径的文件时，该技能才会被激活。

### 4.3 Inline vs Fork 执行模式

- **Inline**（默认）：技能内容展开到当前对话中，共享上下文
- **Fork**：技能在独立子代理中执行，有独立的token预算

### 4.4 安全属性白名单

权限系统使用白名单机制：只有包含"安全"属性的技能才能自动放行。任何新增属性默认需要权限确认。

### 4.5 懒加载文件提取

内置技能可以声明 `files` 对象，在首次调用时提取到临时目录：
```typescript
files: {
  "schemas/config.json": "{...}",
  "templates/output.md": "..."
}
```

---

## 5. 文件路径索引

| 文件路径 | 职责 |
|---------|------|
| `src/tools/SkillTool/SkillTool.ts` | SkillTool主实现 |
| `src/tools/SkillTool/prompt.ts` | 技能列表格式化 |
| `src/utils/frontmatterParser.ts` | YAML Frontmatter解析器 |
| `src/skills/loadSkillsDir.ts` | 技能目录加载器 |
| `src/skills/bundledSkills.ts` | 内置技能注册API |
| `src/skills/mcpSkillBuilders.ts` | MCP技能构建器注册 |
| `src/types/command.ts` | Command类型定义 |
| `src/utils/argumentSubstitution.ts` | $ARGUMENTS参数替换 |
| `src/utils/promptShellExecution.ts` | 技能内Shell命令执行 |

---

**报告完成**。该技能系统展现了灵活的扩展性设计，通过多源统一、条件激活、安全白名单等机制实现了既强大又安全的技能管理。