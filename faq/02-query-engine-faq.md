# Claude Code Query Engine FAQ

本文档解答 Query Engine 相关的技术细节问题。

---

## 1. 配置分层与读取机制

### 配置是怎么分层的？

Claude Code 的配置分为两层：

#### 第一层：QueryConfig（轻量级快照）

```typescript
// src/query/config.ts
type QueryConfig = {
  sessionId: SessionId
  gates: {
    streamingToolExecution: boolean      // Statsig feature gate
    emitToolUseSummaries: boolean        // 环境变量控制
    isAnt: boolean                       // 内部用户标识
    fastModeEnabled: boolean             // 快速模式开关
  }
}
```

**特点**：
- 在每次 `query()` 调用时创建一次
- **不可变**：配置在入口处快照，避免运行时状态变化
- 不包含 `feature()` gates（那些是编译时死代码消除）

**来源**：
- `sessionId` → `getSessionId()` (bootstrap/state.ts)
- `gates.streamingToolExecution` → Statsig feature gate
- `gates.emitToolUseSummaries` → 环境变量 `CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES`

#### 第二层：QueryEngineConfig（完整配置）

```typescript
// src/QueryEngine.ts
type QueryEngineConfig = {
  cwd: string
  tools: Tools                    // 从 src/tools.ts 注册表获取
  commands: Command[]             // 从 src/commands.ts 获取
  mcpClients: MCPServerConnection[]  // MCP 服务器连接
  agents: AgentDefinition[]
  customSystemPrompt?: string     // 用户自定义提示词
  appendSystemPrompt?: string     // 追加系统提示词
  userSpecifiedModel?: string
  maxTurns?: number
  maxBudgetUsd?: number
  // ... 更多字段
}
```

**特点**：
- 包含所有运行时参数
- 由 REPL 或上层调用者组装传入

### 配置读取流程

```
用户启动 CLI
    ↓
main.tsx 解析命令行参数
    ↓
setup() 组装 QueryEngineConfig
    │
    ├─ tools ← src/tools.ts (工具注册表)
    ├─ commands ← src/commands.ts (slash commands)
    ├─ mcpClients ← MCP 连接管理
    └─ customSystemPrompt ← 用户参数
    ↓
QueryEngine 实例化
    ↓
每次 query() 调用时创建 QueryConfig 快照
```

---

## 2. 系统提示词详解

### 系统提示词到底是什么？

系统提示词是发送给 Claude API 的第一条消息，定义了 Claude 的身份、行为准则、工具使用方法等。

**内容结构** (`src/constants/prompts.ts`)：

```typescript
[
  // === 静态部分（可缓存）===
  getSimpleIntroSection(),        // 身份介绍："You are Claude Code..."
  getSimpleSystemSection(),       // 系统规则
  getSimpleDoingTasksSection(),   // 任务执行指南
  getActionsSection(),            // 行为准则
  getUsingYourToolsSection(),     // 工具使用指南
  getSimpleToneAndStyleSection(), // 语气风格
  getOutputEfficiencySection(),   // 输出效率

  SYSTEM_PROMPT_DYNAMIC_BOUNDARY, // 边界标记

  // === 动态部分（session-specific）===
  getSessionSpecificGuidance(),   // 会话特定指引
  loadMemoryPrompt(),             // CLAUDE.md 内容
  computeSimpleEnvInfo(),         // 环境信息（cwd, date）
  getLanguageSection(),           // 语言设置
  getMcpInstructionsSection(),    // MCP 服务器说明
  getScratchpadInstructions(),    // Scratchpad 功能
  // ...
]
```

### 不同状态下是否会不一样？

**是的**，系统提示词会根据运行模式变化：

| 模式 | 提示词特点 |
|------|-----------|
| **普通模式** | 完整静态部分 + 动态部分 |
| **Proactive 模式** | 自主代理提示词，追加 `getProactiveSection()` |
| **Simple 模式** | 极简版：`You are Claude Code... CWD: xxx Date: xxx` |
| **Agent 模式** | Agent 定义可替换或追加默认提示词 |
| **Coordinator 模式** | 专门的协调器系统提示词 |

**示例 - Proactive 模式**：
```typescript
if (proactiveModule?.isProactiveActive()) {
  return [
    'You are an autonomous agent...',
    getSystemRemindersSection(),
    await loadMemoryPrompt(),
    envInfo,
    getProactiveSection(),  // 自主工作指南
  ]
}
```

### 系统提示词如何利用 Cache？

#### 缓存边界设计

```typescript
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY = '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'
```

边界之前的静态内容可以**跨组织共享缓存**（`cacheScope: 'global'`），边界之后的动态内容是 session-specific。

#### 缓存范围分配

```typescript
// src/utils/api.ts: splitSysPromptPrefix
if (useGlobalCacheFeature && boundaryIndex !== -1) {
  return [
    { text: attributionHeader, cacheScope: null },      // 不缓存
    { text: systemPromptPrefix, cacheScope: null },     // 不缓存
    { text: staticJoined, cacheScope: 'global' },       // 全局缓存（跨组织）
    { text: dynamicJoined, cacheScope: null },          // 不缓存
  ]
}

// 默认模式（3P API）
return [
  { text: attributionHeader, cacheScope: null },
  { text: systemPromptPrefix, cacheScope: 'org' },      // 组织级缓存
  { text: restJoined, cacheScope: 'org' },
]
```

#### 缓存优化策略

1. **Session-stable 状态锁存**：关键值（如 GrowthBook flags）首次评估后锁定，防止 mid-session 变化破坏缓存

2. **DANGEROUS_uncachedSystemPromptSection**：标记会破坏缓存的 section（如 MCP 指令，因为连接可能变化）

3. **1小时 TTL 缓存**：符合条件的用户可使用更长 TTL，减少缓存重建

---

## 3. query() 状态机详解

### 为什么叫做"状态机函数"？

`query()` 使用 **AsyncGenerator + 无限循环 + continue/return** 实现状态机：

```typescript
// src/query.ts
async function* query(params): AsyncGenerator<Message, Terminal> {
  let state: State = { messages: params.messages, ... }

  while (true) {  // 无限循环
    const { messages, toolUseContext, ... } = state

    // ... 执行 API 调用、工具执行等 ...

    // 状态转换：用 continue 跳转到下一迭代
    if (需要重试) {
      state = { messages: newMessages, transition: { reason: 'retry' } }
      continue  // ← 状态转换
    }

    // 终止：用 return 结束
    return { reason: 'completed' }  // ← 终止状态
  }
}
```

**状态机特点**：
- 每次循环迭代是一个"回合"(turn)
- `state` 对象在迭代间传递
- `continue` = 状态转换，`return` = 终止

### AsyncGenerator 返回的是什么？

**yield 的内容**（流式输出）：
```typescript
AsyncGenerator<
  | StreamEvent         // API 流事件（message_start, message_delta, message_stop）
  | RequestStartEvent   // 请求开始事件
  | Message             // assistant/user 消息
  | TombstoneMessage    // 删除标记
  | ToolUseSummaryMessage,  // 工具使用摘要
  Terminal              // 最终返回值
>
```

**最终返回值 (Terminal)**：
```typescript
type Terminal =
  | { reason: 'completed' }           // 正常完成
  | { reason: 'aborted_streaming' }   // 流式中断
  | { reason: 'aborted_tools' }       // 工具执行中断
  | { reason: 'prompt_too_long' }     // 提示过长（无法恢复）
  | { reason: 'model_error', error: Error }  // 模型错误
  | { reason: 'max_turns', turnCount: number }  // 达到最大轮次
  | { reason: 'stop_hook_prevented' } // Stop Hook 阻止
  | { reason: 'hook_stopped' }        // Hook 停止
  // ...
```

### 状态转换原因 (Continue)

```typescript
type Continue =
  | { reason: 'collapse_drain_retry' }      // 上下文坍缩后重试
  | { reason: 'reactive_compact_retry' }    // 响应式压缩后重试
  | { reason: 'max_output_tokens_escalate' } // 输出 Token 升级
  | { reason: 'max_output_tokens_recovery' } // 输出 Token 恢复
  | { reason: 'stop_hook_blocking' }        // Stop Hook 阻塞
  | { reason: 'token_budget_continuation' } // Token 预算继续
  | { reason: 'next_turn' }                 // 下一轮对话
```

---

## 4. State 状态对象详解

### state 中存储的内容

```typescript
type State = {
  // === 核心数据 ===
  messages: Message[]                // 对话历史消息数组

  // === 工具执行 ===
  toolUseContext: ToolUseContext     // 工具执行上下文
  pendingToolUseSummary: Promise<...> | undefined  // Haiku 生成的工具摘要

  // === 压缩控制 ===
  autoCompactTracking: AutoCompactTrackingState | undefined  // 自动压缩跟踪
  hasAttemptedReactiveCompact: boolean  // 是否已尝试响应式压缩

  // === Token 控制 ===
  maxOutputTokensRecoveryCount: number  // max_output_tokens 恢复次数
  maxOutputTokensOverride: number | undefined  // 输出限制覆盖

  // === 流程控制 ===
  stopHookActive: boolean | undefined    // stop hook 是否激活
  turnCount: number                      // 当前回合计数
  transition: Continue | undefined       // 上次迭代为何继续（测试用）
}
```

### 各字段用途详解

| 字段 | 用途 | 典型场景 |
|------|------|----------|
| `messages` | 对话历史 | 每次迭代后追加 assistant 消息和 tool_result |
| `toolUseContext` | 工具上下文 | 包含工具列表、权限、AbortController |
| `autoCompactTracking` | 压缩跟踪 | 防止多次压缩触发无限循环 |
| `hasAttemptedReactiveCompact` | 压缩标记 | 防止 413 错误时重复尝试响应式压缩 |
| `maxOutputTokensRecoveryCount` | 恢复计数 | 超过限制则放弃恢复 |
| `turnCount` | 回合计数 | 用于 maxTurns 限制检查 |

---

## 5. 消息类型与处理流程

### 这些 case 的作用是什么？

```typescript
// src/QueryEngine.ts
switch (message.type) {
  case 'assistant':
    // 助手消息：记录到历史，yield 给 SDK
    this.mutableMessages.push(message)
    yield* normalizeMessage(message)
    break

  case 'user':
    // 用户消息或 tool_result：记录并 yield
    this.mutableMessages.push(message)
    yield* normalizeMessage(message)
    break

  case 'progress':
    // 子代理/技能/bash 进度消息
    // 用于 UI 显示实时进度
    this.mutableMessages.push(message)
    yield* normalizeMessage(message)
    break

  case 'attachment':
    // 特殊信号消息：
    // - structured_output: 结构化输出
    // - max_turns_reached: 达到回合限制
    // - queued_command: 队列命令重放
    if (message.attachment.type === 'max_turns_reached') {
      yield { type: 'result', subtype: 'error_max_turns', ... }
      return
    }
    break

  case 'stream_event':
    // Anthropic API 流事件：
    // - message_start: 新消息开始
    // - message_delta: 消息增量（usage, stop_reason）
    // - message_stop: 消息结束
    if (message.event.type === 'message_delta') {
      currentMessageUsage = updateUsage(...)
      lastStopReason = message.event.delta.stop_reason
    }
    break
}
```

### 消息类型汇总

```
Message Types:
├── UserMessage         - 用户输入
├── AssistantMessage    - Claude 响应
├── ToolResultMessage   - 工具执行结果
├── SystemMessage       - 系统消息（compact_boundary 等）
├── AttachmentMessage   - 特殊信号（max_turns_reached 等）
├── ProgressMessage     - 进度消息（agent_progress, bash_progress）
├── TombstoneMessage    - 删除标记
├── ToolUseSummaryMessage - 工具摘要（Haiku 生成）
└── StreamEvent         - API 流事件
```

### 消息管理与拼接

消息通过 `normalizeMessages()` 函数统一处理：

```typescript
// src/utils/messages.ts
export function normalizeMessages(messages: Message[]): NormalizedMessage[] {
  return messages.flatMap(message => {
    switch (message.type) {
      case 'assistant':
        // 多内容块时派生新 UUID
        return message.message.content.map((_, index) => ({
          type: 'assistant',
          message: { ...message.message, content: [_] },
          uuid: deriveUUID(message.uuid, index),
        }))
      case 'user':
        // 字符串内容转数组
        return [{ type: 'user', message: {...}, uuid: message.uuid }]
      // ...
    }
  })
}
```

---

## 6. 工具执行机制详解

### 循环中如何判断要执行工具？

```typescript
// src/query.ts
const toolUseBlocks: ToolUseBlock[] = []
let needsFollowUp = false

// 在 API 流式响应中收集 tool_use blocks
for await (const message of deps.callModel(...)) {
  if (message.type === 'assistant') {
    const msgToolUseBlocks = message.message.content.filter(
      content => content.type === 'tool_use'
    )
    if (msgToolUseBlocks.length > 0) {
      toolUseBlocks.push(...msgToolUseBlocks)
      needsFollowUp = true  // ← 标记需要执行工具
    }
  }
  yield message
}

// 判断是否需要执行工具
if (!needsFollowUp) {
  // 无工具调用 → 进入结束逻辑
  return { reason: 'completed' }
}

// 有工具调用 → 执行工具
const toolUpdates = streamingToolExecutor
  ? streamingToolExecutor.getRemainingResults()
  : runTools(toolUseBlocks, ...)
```

### 如何实现快速的工具执行？

**关键：流式执行** - 工具在 API 流式过程中就开始执行：

```typescript
// src/query.ts: 在流式响应过程中
if (streamingToolExecutor) {
  for (const toolBlock of msgToolUseBlocks) {
    streamingToolExecutor.addTool(toolBlock, message)  // ← 立即添加到队列
  }
}
// addTool() 内部会调用 void this.processQueue() 开始执行
```

**收益**：不需要等待所有 tool_use blocks 接收完毕才开始执行。

### 为什么使用工具队列？

**设计目的**：
1. **流式执行**：边接收边执行，减少延迟
2. **并发控制**：智能判断哪些工具可以并行
3. **顺序保证**：结果按原始顺序 yield

**队列状态**：
```typescript
type ToolStatus = 'queued' | 'executing' | 'completed' | 'yielded'

type TrackedTool = {
  id: string
  block: ToolUseBlock
  status: ToolStatus
  isConcurrencySafe: boolean  // 并发安全性
  results?: Message[]         // 执行结果缓存
  pendingProgress: Message[]  // 进度消息（立即 yield）
}
```

### 工具执行完如何等待结果？

```typescript
// src/services/tools/StreamingToolExecutor.ts
async *getRemainingResults(): AsyncGenerator<MessageUpdate> {
  while (this.hasUnfinishedTools()) {
    await this.processQueue()  // 确保所有工具开始执行

    // 立即 yield 已完成的结果
    for (const result of this.getCompletedResults()) {
      yield result
    }

    // 如果还有执行中的工具但没有完成结果，等待
    if (this.hasExecutingTools() && !this.hasCompletedResults()) {
      await Promise.race([...executingPromises, progressPromise])
    }
  }
}
```

**进度即时反馈**：进度消息不等待工具完成，立即 yield 给 UI。

### 如何判断工具能否安全并发？

**并发判断逻辑**：

```typescript
private canExecuteTool(isConcurrencySafe: boolean): boolean {
  const executingTools = this.tools.filter(t => t.status === 'executing')
  return (
    executingTools.length === 0 ||  // 无执行中工具
    // 或：新工具是并发安全的，且所有执行中工具也都是并发安全的
    (isConcurrencySafe && executingTools.every(t => t.isConcurrencySafe))
  )
}
```

**各工具的并发安全性**：

| 工具 | isConcurrencySafe | 原因 |
|------|-------------------|------|
| GrepTool | `true` | 只读搜索 |
| GlobTool | `true` | 只读查找 |
| FileReadTool | `true` | 只读 |
| WebFetch/WebSearch | `true` | 只读网络请求 |
| AgentTool | `true` | 独立子代理 |
| BashTool | `this.isReadOnly?.(input)` | 只读命令可并发，写命令串行 |

**保守策略**：默认 `isConcurrencySafe: false`，除非工具明确声明安全。

---

## 7. 嵌套内存路径机制

### 嵌套内存路径是什么意思？

`loadedNestedMemoryPaths` 是一个 **会话级别的去重集合**，防止同一个 `CLAUDE.md` 文件被重复注入。

**设计背景**：

```
问题：readFileState 是 100 条目的 LRU 缓存
     ↓
繁忙会话中旧条目被驱逐
     ↓
下次发现同一路径时，LRU .has() 返回 false
     ↓
同一个 CLAUDE.md 被重新注入（浪费 Token）
     ↓
解决方案：loadedNestedMemoryPaths（不驱逐的 Set）
```

**使用逻辑**：

```typescript
// src/utils/attachments.ts
for (const memoryFile of memoryFiles) {
  // Dedup: 使用不驱逐的 Set 检查
  if (toolUseContext.loadedNestedMemoryPaths?.has(memoryFile.path)) {
    continue  // 已加载过，跳过
  }
  if (!toolUseContext.readFileState.has(memoryFile.path)) {
    attachments.push({
      type: 'nested_memory',
      path: memoryFile.path,
      content: memoryFile,
    })
    toolUseContext.loadedNestedMemoryPaths?.add(memoryFile.path)  // 标记已加载
  }
}
```

**生命周期**：
- 创建：REPL/QueryEngine 初始化时创建空 Set
- 清除：`/clear` 或 `/compact` 时清除
- 子代理：独立创建新集合

---

## 8. 中断控制实现

### 中断控制是怎么实现的？

**多层次 AbortController**：

```
主会话 AbortController (QueryEngine/REPL)
    │
    ├── createChildAbortController() → 子控制器
    │       │
    │       └── 工具级 AbortController
    │               │
    │               └── 组合信号（signal + timeout）
    │
    └── 中断传播：parent → child（单向）
```

**子控制器设计** (`src/utils/abortController.ts`)：

```typescript
export function createChildAbortController(parent: AbortController): AbortController {
  const child = createAbortController()

  // 使用 WeakRef 防止内存泄漏
  const weakChild = new WeakRef(child)
  const handler = () => weakChild.deref()?.abort(parent.signal.reason)

  parent.signal.addEventListener('abort', handler, { once: true })
  return child
}
```

**中断类型**：

| 类型 | 触发条件 | 处理 |
|------|----------|------|
| `user_interrupted` | 用户发送新消息 | 取消可中断工具 |
| `sibling_error` | 并发工具出错 | 取消其他并发工具 |
| `streaming_fallback` | 流式模式废弃 | 丢弃所有结果 |

**工具中断行为**：
- `interruptBehavior: 'cancel'` → 用户输入时停止，丢弃结果
- `interruptBehavior: 'block'` → 继续运行，新消息等待（默认）

---

## 9. 压缩机制详解

### query 预处理做了哪些预处理？

**预处理流程**：

```
1. getMessagesAfterCompactBoundary(messages)
   ↓ 获取压缩边界后的消息
2. applyToolResultBudget()
   ↓ 应用工具结果预算
3. snipCompactIfNeeded()         [feature: HISTORY_SNIP]
   ↓ 快速截断旧消息
4. microcompactMessages()
   ↓ 缓存编辑优化
5. contextCollapse.applyCollapsesIfNeeded()
   ↓ 上下文折叠
6. autoCompactIfNeeded()
   ↓ 自动摘要压缩
```

### 四种压缩机制详解

#### 1. Snip Compact - 快速截断

**特点**：最快的压缩，不生成摘要，直接截断旧消息

```typescript
// src/services/compact/snipCompact.ts
const snipResult = snipCompactIfNeeded(messagesForQuery)
messagesForQuery = snipResult.messages
snipTokensFreed = snipResult.tokensFreed  // 传递给 autocompact 阈值计算
```

**触发**：在 microcompact 和 autocompact 之前运行

---

#### 2. Microcompact - 缓存编辑优化

**两种实现**：

**A. Cached Microcompact**：使用 `cache_edits` API

```typescript
// 不修改本地消息内容，通过 API 删除工具结果
// 优点：不破坏缓存前缀
const cacheEdits = mod.createCacheEditsBlock(state, toolsToDelete)
```

**适用工具**：
```typescript
const COMPACTABLE_TOOLS = new Set([
  FILE_READ_TOOL_NAME,
  SHELL_TOOL_NAMES,
  GREP_TOOL_NAME,
  GLOB_TOOL_NAME,
  WEB_SEARCH_TOOL_NAME,
  WEB_FETCH_TOOL_NAME,
  FILE_EDIT_TOOL_NAME,
  FILE_WRITE_TOOL_NAME,
])
```

**B. Time-Based Microcompact**：时间触发

```typescript
// 距离上次 assistant 消息时间超过阈值
// 暗示服务器缓存已过期
const gapMinutes = (Date.now() - new Date(lastAssistant.timestamp).getTime()) / 60_000
if (gapMinutes >= config.gapThresholdMinutes) {
  // 执行压缩
}
```

---

#### 3. Autocompact - 完整摘要压缩

**阈值判断**：

```typescript
// src/services/compact/autoCompact.ts
export async function shouldAutoCompact(
  messages: Message[],
  model: string,
  snipTokensFreed = 0,  // snip 释放的 token
): Promise<boolean> {
  // 递归保护：session_memory 和 compact 是 forked agents
  if (querySource === 'session_memory' || querySource === 'compact') {
    return false  // 不在压缩代理中再压缩
  }

  const tokenCount = tokenCountWithEstimation(messages) - snipTokensFreed
  const threshold = getAutoCompactThreshold(model)
  return tokenCount > threshold
}
```

**执行优先级**：
1. 首先尝试 **Session Memory Compaction**（预提取的记忆）
2. 失败则调用 **compactConversation**（传统摘要）

---

#### 4. Reactive Compact - 响应式压缩

**触发时机**：收到 413 (prompt_too_long) 错误后

```typescript
// src/query.ts
if (isPromptTooLongMessage(lastMessage)) {
  // 1. 先尝试 context collapse drain
  if (contextCollapse) {
    const drained = contextCollapse.recoverFromOverflow(messages)
    if (drained.committed > 0) {
      state = { messages: drained.messages, transition: { reason: 'collapse_drain_retry' } }
      continue
    }
  }

  // 2. 再尝试 reactive compact
  if (reactiveCompact && !hasAttemptedReactiveCompact) {
    const outcome = await reactiveCompact.reactiveCompactOnPromptTooLong(...)
    if (outcome.success) {
      state = { messages: postCompactMessages, transition: { reason: 'reactive_compact_retry' } }
      continue
    }
  }
}
```

**消息隐藏机制**：错误消息先隐藏，恢复成功后才丢弃，失败则显示错误。

---

## 10. Token 预算与收益递减

### 收益递减检测是什么意思？

**概念**：当模型使用 Token 预算扩展时，如果连续多次扩展但每次产出很少，说明效率下降，应该停止。

**判断逻辑** (`src/query/tokenBudget.ts`)：

```typescript
const COMPLETION_THRESHOLD = 0.9    // 90% 预算使用率触发停止
const DIMINISHING_THRESHOLD = 500  // 收益递减阈值：500 tokens

const isDiminishing =
  tracker.continuationCount >= 3 &&          // 已连续继续 3 次以上
  deltaSinceLastCheck < DIMINISHING_THRESHOLD &&  // 本次新增 < 500 tokens
  tracker.lastDeltaTokens < DIMINISHING_THRESHOLD  // 上次新增也 < 500 tokens
```

**处理**：

```typescript
if (!isDiminishing && turnTokens < budget * COMPLETION_THRESHOLD) {
  // 未收益递减且未达阈值 → 继续
  tracker.continuationCount++
  return { action: 'continue', nudgeMessage: 'Keep working — do not summarize.' }
}

if (isDiminishing) {
  // 收益递减 → 停止
  return { action: 'stop', completionEvent: { diminishingReturns: true } }
}
```

---

## 11. 弹性恢复机制

### 详细介绍弹性回复机制

#### 1. Prompt Too Long (413) 错误处理

**错误识别**：

```typescript
// src/services/api/errors.ts
export const PROMPT_TOO_LONG_ERROR_MESSAGE = 'Prompt is too long'

export function isPromptTooLongMessage(msg: AssistantMessage): boolean {
  return msg.isApiErrorMessage &&
    msg.message.content.some(block =>
      block.type === 'text' && block.text.startsWith(PROMPT_TOO_LONG_ERROR_MESSAGE)
    )
}
```

**Token Gap 解析**（用于精确删除）：

```typescript
export function parsePromptTooLongTokenCounts(rawMessage: string) {
  // 解析 "prompt is too long: 105000 tokens > 100000"
  const match = rawMessage.match(/prompt is too long[^0-9]*(\d+)\s*tokens?\s*>\s*(\d+)/i)
  return {
    actualTokens: match ? parseInt(match[1], 10) : undefined,
    limitTokens: match ? parseInt(match[2], 10) : undefined,
  }
}
```

#### 2. Compaction 本身的 PTL 恢复

**截断重试**：

```typescript
// src/services/compact/compact.ts
const MAX_PTL_RETRIES = 3
let ptlAttempts = 0

for (;;) {
  summaryResponse = await streamCompactSummary(...)

  if (!summaryResponse.startsWith(PROMPT_TOO_LONG_ERROR_MESSAGE)) break

  ptlAttempts++
  if (ptlAttempts <= MAX_PTL_RETRIES) {
    // 按 token gap 精确删除组数
    messagesToSummarize = truncateHeadForPTLRetry(messagesToSummarize, summaryResponse)
  } else {
    throw new Error(ERROR_MESSAGE_PROMPT_TOO_LONG)
  }
}
```

**删除策略**：
- 有 token gap 时：按 gap 累加计算删除组数
- 无 token gap 时：删除 20% 的消息组

#### 3. Media Size 错误恢复

```typescript
export function isMediaSizeError(raw: string): boolean {
  return (
    raw.includes('image exceeds') ||
    raw.includes('image dimensions exceed') ||
    /maximum of \d+ PDF pages/.test(raw)
  )
}
```

处理方式：移除过大的媒体文件后重试。

---

## 关键常量汇总

| 常量 | 值 | 说明 |
|------|-----|------|
| `AUTOCOMPACT_BUFFER_TOKENS` | 13,000 | 自动压缩缓冲区 |
| `WARNING_THRESHOLD_BUFFER_TOKENS` | 20,000 | 警告阈值缓冲区 |
| `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` | 3 | 熔断器阈值 |
| `MAX_PTL_RETRIES` | 3 | PTL 重试次数 |
| `MAX_OUTPUT_TOKENS_FOR_SUMMARY` | 20,000 | 摘要输出上限 |
| `DIMINISHING_THRESHOLD` | 500 | 收益递减阈值 |
| `COMPLETION_THRESHOLD` | 0.9 | 90% 预算使用率 |
| getMaxToolUseConcurrency() | 10 | 最大工具并发数 |

---

## 设计亮点总结

1. **AsyncGenerator 状态机**：清晰的循环结构，可中断，流式输出
2. **流式工具执行**：边接收边执行，减少延迟
3. **智能并发控制**：只读工具并行，写工具串行
4. **分层压缩**：从轻量级到重量级，按需触发
5. **缓存保护**：Cached Microcompact 不破坏缓存前缀
6. **收益递减检测**：防止 Token 预算浪费
7. **弹性恢复**：多层次错误处理，自动重试
8. **嵌套内存去重**：防止 CLAUDE.md 重复注入