# Claude Code 工具系统分析报告

## 模块概述

工具系统是 Claude Code 的「万能工具箱」，就像一个**全能装修队的工具房**——每个工具都有明确的功能定义、安全操作规程和使用权限。当 AI 需要与外部环境交互（读写文件、执行命令、搜索代码等）时，必须通过这个工具系统来完成。

### 核心职责

1. **工具定义**：通过 `Tool` 类型定义每个工具的完整契约
2. **工具注册**：通过 `buildTool` 工厂函数简化工具创建
3. **工具池组装**：根据权限上下文动态组装可用工具集
4. **权限集成**：每个工具都有独立的权限检查逻辑

### 生活化类比

| 概念 | 类比 | 说明 |
|------|------|------|
| `Tool` 类型 | 工具使用说明书 | 定义工具的功能、参数、安全规程 |
| `buildTool` | 工具出厂设置 | 填充默认值，确保安全基线 |
| `inputSchema` | 参数规格表 | 规定输入参数的类型和格式 |
| `checkPermissions` | 操作许可证检查 | 确认是否有权限执行此操作 |
| `assembleToolPool` | 工具房配置 | 根据项目需求筛选可用工具 |

---

## 核心概念详解

### 1. Tool 类型定义（src/Tool.ts:362-695）

`Tool` 类型是整个工具系统的核心契约，每个工具必须实现这个接口。它就像一份**完整的工具使用说明书**，包含以下章节：

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Tool 接口结构                                  │
├─────────────────────────────────────────────────────────────────────┤
│  【身份标识】                                                         │
│  • name: string          → 工具名称（如 "Bash"、"Read"）              │
│  • aliases?: string[]    → 别名列表（用于向后兼容）                   │
│  • searchHint?: string   → 搜索提示（帮助模型找到工具）               │
│                                                                      │
│  【规格定义】                                                         │
│  • inputSchema: Zod      → 输入参数的 Zod schema                     │
│  • inputJSONSchema?      → MCP 工具的 JSON Schema 格式               │
│  • outputSchema?         → 输出结果的类型定义                         │
│                                                                      │
│  【核心功能】                                                         │
│  • call()                → 执行工具的核心逻辑                         │
│  • description()         → 返回给模型的工具描述                       │
│  • prompt()              → 返回给模型的详细使用指南                   │
│                                                                      │
│  【安全控制】                                                         │
│  • checkPermissions()    → 权限检查逻辑                              │
│  • validateInput?()      → 输入验证（权限检查之前）                   │
│  • isConcurrencySafe()   → 是否可并发执行                            │
│  • isReadOnly()          → 是否只读操作                              │
│  • isDestructive?()      → 是否破坏性操作                            │
│                                                                      │
│  【UI 渲染】                                                          │
│  • renderToolUseMessage()     → 渲染工具使用消息                      │
│  • renderToolResultMessage()  → 渲染工具结果消息                      │
│  • userFacingName()           → 用户友好的工具名称                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. buildTool 工厂函数（src/Tool.ts:783-792）

`buildTool` 函数就像**工具出厂设置**——为新工具填充安全默认值，确保即使工具定义不完整也能安全运行。

```typescript
// 安全默认值（fail-closed 策略）
const TOOL_DEFAULTS = {
  isEnabled: () => true,                              // 默认启用
  isConcurrencySafe: (_input?) => false,              // 默认不可并发（保守策略）
  isReadOnly: (_input?) => false,                     // 默认非只读（保守策略）
  isDestructive: (_input?) => false,                  // 默认非破坏性
  checkPermissions: (input, _ctx?) =>
    Promise.resolve({ behavior: 'allow', updatedInput: input }),  // 默认允许
  toAutoClassifierInput: (_input?) => '',             // 默认跳过分类器
  userFacingName: (_input?) => '',                    // 默认空名称
}

// 工厂函数：合并默认值和自定义定义
export function buildTool<D extends AnyToolDef>(def: D): BuiltTool<D> {
  return {
    ...TOOL_DEFAULTS,
    userFacingName: () => def.name,  // 特殊处理：使用工具名作为默认用户名
    ...def,
  } as BuiltTool<D>
}
```

**设计亮点：Fail-Closed 默认策略**

为什么默认值采用保守策略？想象一个**核电站的安全阀**——如果阀门故障，应该默认关闭（fail-closed）而不是默认开启（fail-open）。

- `isConcurrencySafe` 默认 `false`：假设不可并发，防止意外竞争条件
- `isReadOnly` 默认 `false`：假设会写入，触发更严格的权限检查

### 3. 工具注册机制（src/tools.ts）

`getAllBaseTools()` 函数是工具注册的核心，它就像**工具房总清单**——列出所有可用的内置工具。

```typescript
export function getAllBaseTools(): Tools {
  return [
    AgentTool,          // 子代理工具
    TaskOutputTool,     // 任务输出工具
    BashTool,           // Shell 命令执行
    ...(hasEmbeddedSearchTools() ? [] : [GlobTool, GrepTool]),  // 搜索工具
    ExitPlanModeV2Tool, // 退出计划模式
    FileReadTool,       // 文件读取
    FileEditTool,       // 文件编辑
    FileWriteTool,      // 文件写入
    NotebookEditTool,   // Notebook 编辑
    WebFetchTool,       // 网页获取
    WebSearchTool,      // 网页搜索
    SkillTool,          // 技能工具
    // ... 条件性工具（根据 feature flags）
    ...(isTodoV2Enabled() ? [TaskCreateTool, ...] : []),
    ...(process.env.USER_TYPE === 'ant' ? [ConfigTool] : []),
  ]
}
```

**条件加载机制**

工具加载使用多种条件判断，就像**根据客户需求配置工具房**：

| 条件类型 | 示例 | 说明 |
|----------|------|------|
| Feature Flags | `feature('PROACTIVE')` | Bun 编译时死代码消除 |
| 环境变量 | `process.env.USER_TYPE === 'ant'` | 内部用户专属工具 |
| 功能检测 | `isWorktreeModeEnabled()` | 动态功能开关 |
| 预设模式 | `isEnvTruthy(CLAUDE_CODE_SIMPLE)` | 简化模式 |

### 4. 工具池组装（src/tools.ts:345-367）

`assembleToolPool()` 是工具池组装的核心函数，它合并内置工具和 MCP 工具，确保工具集的一致性。

```
┌─────────────────────────────────────────────────────────────────────┐
│                    assembleToolPool 工作流程                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: permissionContext + mcpTools                                  │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 1. getTools(permissionContext)            │                       │
│  │    → 获取内置工具，应用权限过滤            │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 2. filterToolsByDenyRules(mcpTools)       │                       │
│  │    → 过滤被 deny 规则禁止的 MCP 工具       │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 3. sort(byName) + concat                  │                       │
│  │    → 按名称排序，内置工具优先              │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 4. uniqBy('name')                         │                       │
│  │    → 按名称去重，内置工具优先保留          │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  输出: 合并后的工具池 (Tools[])                                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 完整工作流程：工具调用全链路

### 从模型请求到工具执行

当模型决定调用一个工具时，完整的执行链路如下：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        工具调用完整流程                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐                                                        │
│  │ 1. 模型发出请求   │  tool_use block: { name: "Bash", input: {...} }       │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────┐                                                        │
│  │ 2. QueryEngine   │  接收 tool_use，查找对应工具                           │
│  │    解析请求       │  findToolByName(tools, toolName)                      │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────┐                                                        │
│  │ 3. Schema 验证   │  tool.inputSchema.safeParse(input)                    │
│  │    (Zod 检查)    │  → 验证参数类型和格式                                   │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼ (验证失败 → 返回错误)                                               │
│  ┌──────────────────┐                                                        │
│  │ 4. validateInput │  工具特定的输入验证                                     │
│  │    (工具级检查)   │  → 检查路径是否存在、参数是否合理                        │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼ (验证失败 → 返回错误)                                               │
│  ┌──────────────────┐                                                        │
│  │ 5. PreToolUse    │  执行 PreToolUse hooks                                 │
│  │    Hooks         │  → 可能修改输入或阻止执行                               │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────┐                                                        │
│  │ 6. 权限检查       │  canUseTool() + checkPermissions()                   │
│  │    (核心决策)     │  → 14 步决策流程（见权限系统文档）                      │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼ (权限拒绝 → 返回拒绝消息)                                           │
│  ┌──────────────────┐                                                        │
│  │ 7. 执行工具       │  tool.call(input, context, canUseTool, ...)          │
│  │    call()        │  → 实际执行工具逻辑                                     │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────┐                                                        │
│  │ 8. PostToolUse   │  执行 PostToolUse hooks                                │
│  │    Hooks         │  → 可能修改结果或触发后续操作                           │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────┐                                                        │
│  │ 9. 结果映射       │  mapToolResultToToolResultBlockParam()               │
│  │    → API 格式    │  → 将结果转换为 API 兼容格式                           │
│  └──────────────────┘                                                        │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────┐                                                        │
│  │ 10. 返回给模型   │  tool_result block: { content: "...", tool_use_id }   │
│  └──────────────────┘                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 工具执行核心代码（src/services/tools/toolExecution.ts）

`runToolUse` 是工具执行的入口函数：

```typescript
export async function* runToolUse(
  toolUse: ToolUseBlock,          // 模型发出的 tool_use 请求
  assistantMessage: AssistantMessage,
  canUseTool: CanUseToolFn,       // 权限检查函数
  toolUseContext: ToolUseContext, // 执行上下文
): AsyncGenerator<MessageUpdateLazy, void> {

  // Step 1: 查找工具
  let tool = findToolByName(toolUseContext.options.tools, toolUse.name)

  // 处理别名查找（向后兼容）
  if (!tool) {
    const fallbackTool = findToolByName(getAllBaseTools(), toolUse.name)
    if (fallbackTool && fallbackTool.aliases?.includes(toolUse.name)) {
      tool = fallbackTool
    }
  }

  // 工具不存在 → 返回错误
  if (!tool) {
    yield { message: createUserMessage({
      content: [{ type: 'tool_result', content: `No such tool: ${toolName}`, is_error: true }]
    })}
    return
  }

  // Step 2-9: 流式执行权限检查和工具调用
  for await (const update of streamedCheckPermissionsAndCallTool(
    tool, toolUse.id, toolInput, toolUseContext, canUseTool, ...
  )) {
    yield update
  }
}
```

---

## 关键代码解读

### 1. buildTool 工厂函数详解

```typescript
// src/Tool.ts:757-792

/**
 * buildTool 工厂函数
 *
 * 设计理念：
 * 1. 所有工具导出都应通过此函数，确保默认值一致性
 * 2. 采用 fail-closed 策略：安全相关的默认值偏向保守
 * 3. 类型系统确保调用者永远看到完整的 Tool 接口
 */
const TOOL_DEFAULTS = {
  // 默认启用 - 大多数工具都应该可用
  isEnabled: () => true,

  // 默认不可并发（保守策略）
  // 原因：并发执行可能导致竞争条件，除非工具明确声明安全
  isConcurrencySafe: (_input?: unknown) => false,

  // 默认非只读（保守策略）
  // 原因：只读工具可以宽松处理，但写入工具需要更严格的权限检查
  isReadOnly: (_input?: unknown) => false,

  // 默认非破坏性
  // 破坏性操作（删除、覆盖）需要额外 UI 提示
  isDestructive: (_input?: unknown) => false,

  // 默认允许权限
  // 如果工具不定义特殊权限逻辑，则使用通用权限系统
  checkPermissions: (input, _ctx?) =>
    Promise.resolve({ behavior: 'allow', updatedInput: input }),

  // 默认跳过分类器
  // 安全相关工具必须覆盖此方法，提供分类器输入
  toAutoClassifierInput: (_input?) => '',

  // 默认空名称（下面会特殊处理）
  userFacingName: (_input?) => '',
}

export function buildTool<D extends AnyToolDef>(def: D): BuiltTool<D> {
  // 运行时展开顺序很重要：
  // 1. TOOL_DEFAULTS 提供基础
  // 2. userFacingName 特殊处理（使用工具名）
  // 3. def 覆盖默认值
  return {
    ...TOOL_DEFAULTS,
    userFacingName: () => def.name,  // 特殊：使用工具名作为默认
    ...def,
  } as BuiltTool<D>
}
```

### 2. FileReadTool 实例解析

```typescript
// src/tools/FileReadTool/FileReadTool.ts:337-718

export const FileReadTool = buildTool({
  // === 身份标识 ===
  name: FILE_READ_TOOL_NAME,           // "Read"
  searchHint: 'read files, images, PDFs, notebooks',  // 搜索提示

  // === 输出控制 ===
  maxResultSizeChars: Infinity,        // 永不持久化（避免循环读取）
  strict: true,                        // 启用严格模式

  // === Schema 定义 ===
  inputSchema: lazySchema(() =>
    z.strictObject({
      file_path: z.string().describe('The absolute path to the file'),
      offset: z.number().int().nonnegative().optional(),
      limit: z.number().int().positive().optional(),
      pages: z.string().optional(),    // PDF 页码范围
    })
  ),

  // === 安全属性 ===
  isConcurrencySafe() { return true },  // 读取是并发安全的
  isReadOnly() { return true },          // 纯读取操作

  // === 权限匹配器 ===
  async preparePermissionMatcher({ file_path }) {
    // 为 hook if 条件准备匹配函数
    return pattern => matchWildcardPattern(pattern, file_path)
  },

  // === 权限检查 ===
  async checkPermissions(input, context): Promise<PermissionDecision> {
    const appState = context.getAppState()
    return checkReadPermissionForTool(
      FileReadTool, input, appState.toolPermissionContext
    )
  },

  // === 输入验证 ===
  async validateInput({ file_path, pages }, context) {
    // 1. PDF 页码格式验证
    if (pages !== undefined) {
      const parsed = parsePDFPageRange(pages)
      if (!parsed) {
        return { result: false, message: `Invalid pages: "${pages}"`, errorCode: 7 }
      }
      if (rangeSize > PDF_MAX_PAGES_PER_READ) {
        return { result: false, message: 'Too many pages', errorCode: 8 }
      }
    }

    // 2. deny 规则检查
    const denyRule = matchingRuleForInput(fullFilePath, context, 'read', 'deny')
    if (denyRule !== null) {
      return { result: false, message: 'File denied by permission settings', errorCode: 1 }
    }

    // 3. 二进制文件检查
    if (hasBinaryExtension(fullFilePath) && !isPDFExtension(ext)) {
      return { result: false, message: 'Cannot read binary files', errorCode: 4 }
    }

    // 4. 设备文件检查（防止无限输出）
    if (isBlockedDevicePath(fullFilePath)) {
      return { result: false, message: 'Cannot read device files', errorCode: 9 }
    }

    return { result: true }
  },

  // === 核心执行逻辑 ===
  async call({ file_path, offset = 1, limit, pages }, context, ...) {
    // 1. 重复读取去重（节省 token）
    const existingState = readFileState.get(fullFilePath)
    if (existingState && rangeMatch && mtimeMatch) {
      return { data: { type: 'file_unchanged', file: { filePath } } }
    }

    // 2. 技能发现（非阻塞）
    const newSkillDirs = await discoverSkillDirsForPaths([fullFilePath], cwd)
    if (newSkillDirs.length > 0) {
      addSkillDirectories(newSkillDirs).catch(() => {})  // fire-and-forget
    }

    // 3. 根据文件类型执行不同的读取逻辑
    if (ext === 'ipynb') {
      // Notebook 处理
      const cells = await readNotebook(resolvedFilePath)
      return { data: { type: 'notebook', file: { filePath, cells } } }
    }

    if (IMAGE_EXTENSIONS.has(ext)) {
      // 图片处理（带 token 预算压缩）
      const data = await readImageWithTokenBudget(resolvedFilePath, maxTokens)
      return { data }
    }

    if (isPDFExtension(ext)) {
      // PDF 处理（页码提取或完整读取）
      if (pages) {
        const result = await extractPDFPages(resolvedFilePath, parsePDFPageRange(pages))
        return { data: result.data }
      }
      const pdfData = await readPDF(resolvedFilePath)
      return { data: pdfData }
    }

    // 默认：文本文件读取
    const { content, lineCount, totalLines } = await readFileInRange(...)
    readFileState.set(fullFilePath, { content, timestamp: mtimeMs, offset, limit })
    return { data: { type: 'text', file: { filePath, content, numLines: lineCount } } }
  },

  // === 结果映射 ===
  mapToolResultToToolResultBlockParam(data, toolUseID) {
    switch (data.type) {
      case 'image':
        return { tool_use_id: toolUseID, type: 'tool_result',
          content: [{ type: 'image', source: { type: 'base64', data: data.file.base64 } }] }
      case 'text':
        return { tool_use_id: toolUseID, type: 'tool_result',
          content: addLineNumbers(data.file) + CYBER_RISK_MITIGATION_REMINDER }
      // ... 其他类型处理
    }
  },
})
```

### 3. assembleToolPool 组装函数

```typescript
// src/tools.ts:345-367

/**
 * 组装完整工具池
 *
 * 这是工具集的单一真相来源，确保 REPL 和 runAgent 使用相同的工具集
 *
 * 设计考量：
 * 1. 内置工具优先排序（确保 prompt cache 稳定）
 * 2. MCP 工具按 deny 规则过滤
 * 3. 按名称去重（内置工具优先保留）
 */
export function assembleToolPool(
  permissionContext: ToolPermissionContext,
  mcpTools: Tools,
): Tools {
  // Step 1: 获取内置工具（已应用权限过滤）
  const builtInTools = getTools(permissionContext)

  // Step 2: 过滤被 deny 规则禁止的 MCP 工具
  const allowedMcpTools = filterToolsByDenyRules(mcpTools, permissionContext)

  // Step 3: 排序策略
  // 为什么内置工具要先排序？因为 prompt cache 的稳定性！
  // 如果 MCP 工具插入到内置工具之间，会破坏 cache key
  const byName = (a: Tool, b: Tool) => a.name.localeCompare(b.name)

  // Step 4: 合并去重
  // uniqBy 保留插入顺序，所以内置工具优先保留
  return uniqBy(
    [...builtInTools].sort(byName).concat(allowedMcpTools.sort(byName)),
    'name',
  )
}
```

---

## 设计亮点

### 1. Fail-Closed 安全默认值

**生活类比**：核电站安全阀

当系统故障时，安全阀应该**默认关闭**（fail-closed）而不是默认开启（fail-open）。工具系统采用同样的策略：

| 属性 | 默认值 | 设计原因 |
|------|--------|----------|
| `isConcurrencySafe` | `false` | 假设不安全，防止竞争条件 |
| `isReadOnly` | `false` | 假设会写入，触发严格权限检查 |
| `isDestructive` | `false` | 假设不破坏，但写入工具应显式声明 |

### 2. 类型安全的工具定义

```typescript
// ToolDef 允许省略默认值，但 BuiltTool 保证完整
type DefaultableToolKeys = 'isEnabled' | 'isConcurrencySafe' | 'isReadOnly' | ...

type ToolDef<Input, Output, P> =
  Omit<Tool<Input, Output, P>, DefaultableToolKeys> &
  Partial<Pick<Tool<Input, Output, P>, DefaultableToolKeys>>

// BuiltTool 类型镜像运行时展开行为
type BuiltTool<D> = Omit<D, DefaultableToolKeys> & {
  [K in DefaultableToolKeys]-?: K extends keyof D ? D[K] : ToolDefaults[K]
}
```

### 3. Lazy Schema 模式

```typescript
// 延迟 schema 构造，避免启动时加载所有 Zod schema
const inputSchema = lazySchema(() =>
  z.strictObject({
    file_path: z.string().describe('The absolute path'),
  })
)

// getter 模式延迟执行
get inputSchema(): InputSchema {
  return inputSchema()  // 首次访问时才构造
}
```

### 4. Prompt Cache 稳定性

```typescript
// 工具排序策略：内置工具作为连续前缀
// 这样 MCP 工具变化不会破坏 prompt cache
return uniqBy(
  [...builtInTools].sort(byName).concat(allowedMcpTools.sort(byName)),
  'name',
)
```

### 5. Feature Flag 条件加载

```typescript
// Bun 的 bun:bundle feature() 实现编译时死代码消除
const SleepTool = feature('PROACTIVE') || feature('KAIROS')
  ? require('./tools/SleepTool/SleepTool.js').SleepTool
  : null

// 简化模式只加载基础工具
if (isEnvTruthy(process.env.CLAUDE_CODE_SIMPLE)) {
  return filterToolsByDenyRules([BashTool, FileReadTool, FileEditTool], permissionContext)
}
```

---

## 模块交互图

```
                    ┌──────────────────────────────────────────────┐
                    │                  QueryEngine                  │
                    │              (工具调用入口)                    │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
┌────────────────────┐      ┌──────────────────────────────────────┐
│    commands.ts     │      │              tools.ts                 │
│  (Slash Commands)  │      │    (工具注册 & 池组装)                 │
│                    │      │                                      │
│  • /commit         │      │  • getAllBaseTools()                 │
│  • /review         │      │  • assembleToolPool()                │
│  • /mcp            │      │  • getTools()                        │
└────────────────────┘      └──────────────────────┬───────────────┘
                                                    │
                    ┌───────────────────────────────┼───────────────────┐
                    │                               │                   │
                    ▼                               ▼                   ▼
          ┌─────────────────┐           ┌─────────────────┐   ┌─────────────────┐
          │    Tool.ts      │           │  toolExecution  │   │ useCanUseTool   │
          │  (类型定义)      │           │   (执行逻辑)     │   │  (权限检查)     │
          │                 │           │                 │   │                 │
          │ • Tool type    │           │ • runToolUse() │   │ • canUseTool() │
          │ • buildTool()  │           │ • checkPerms() │   │ • 14步决策      │
          │ • defaults     │           │ • call()       │   │                 │
          └────────┬────────┘           └────────┬────────┘   └────────┬────────┘
                   │                             │                     │
                   ▼                             ▼                     ▼
    ┌──────────────────────────────────────────────────────────────────────────┐
    │                         Individual Tools                                  │
    │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │
    │  │  BashTool   │ │FileReadTool │ │FileEditTool │ │  AgentTool  │        │
    │  │             │ │             │ │             │ │             │        │
    │  │ • call()    │ │ • call()    │ │ • call()    │ │ • call()    │        │
    │  │ • validate  │ │ • validate  │ │ • validate  │ │ • validate  │        │
    │  │ • perms     │ │ • perms     │ │ • perms     │ │ • perms     │        │
    │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘        │
    │                                                                          │
    │  MCP Tools: mcp__server__tool (通过 MCP 协议动态加载)                    │
    └──────────────────────────────────────────────────────────────────────────┘
```

---

## 文件路径索引

| 类别 | 文件路径 | 职责说明 |
|------|----------|----------|
| **核心类型** | `src/Tool.ts` | Tool 接口定义、buildTool 工厂函数 |
| **工具注册** | `src/tools.ts` | getAllBaseTools、assembleToolPool |
| **工具执行** | `src/services/tools/toolExecution.ts` | runToolUse、checkPermissionsAndCallTool |
| **权限类型** | `src/types/permissions.ts` | PermissionMode、PermissionResult |
| **权限逻辑** | `src/utils/permissions/permissions.ts` | hasPermissionsToUseTool（14步决策） |
| **权限 Hook** | `src/hooks/useCanUseTool.tsx` | useCanUseTool React Hook |
| **工具常量** | `src/constants/tools.ts` | ALL_AGENT_DISALLOWED_TOOLS |
| **具体工具** | `src/tools/*/` | 各工具的具体实现 |

### 工具目录结构

```
src/tools/
├── AgentTool/           # 子代理工具（派发子任务）
│   ├── AgentTool.ts     # 主逻辑
│   └── loadAgentsDir.ts # 加载 agents 目录
├── BashTool/            # Shell 命令执行
│   ├── BashTool.tsx     # UI + 执行逻辑
│   ├── bashPermissions.ts # Bash 权限检查
│   └── prompt.ts        # 工具描述
├── FileReadTool/        # 文件读取
│   ├── FileReadTool.ts  # 核心逻辑
│   ├── UI.ts            # 渲染组件
│   └── prompt.ts        # 工具描述
├── FileEditTool/        # 文件编辑
├── FileWriteTool/       # 文件写入
├── GlobTool/            # 文件模式搜索
├── GrepTool/            # 内容搜索
├── SkillTool/           # 技能调用
├── MCPTool/             # MCP 工具包装
└── ...                  # 其他工具
```

---

## 总结

Claude Code 工具系统展示了优秀的软件工程实践：

1. **强类型安全**：TypeScript 泛型 + Zod schema 确保端到端类型一致性
2. **扩展性**：buildTool 工厂函数使新工具定义只需最少代码
3. **安全性**：多层权限系统 + fail-closed 默认值策略
4. **性能优化**：延迟 schema 构造 + 编译时死代码消除
5. **模块化**：清晰分离工具定义、注册、执行、权限
6. **缓存友好**：工具排序策略确保 prompt cache 稳定性