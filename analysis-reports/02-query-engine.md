# Claude Code Query Engine 深度分析报告

## 1. 模块概述

**核心定位**: QueryEngine 是 Claude Code 的核心 LLM 查询引擎，负责管理对话生命周期、执行 API 调用、编排工具执行、处理消息流以及管理 Token 预算。

**关键文件**:
- `src/QueryEngine.ts` - 查询引擎类（约 1300 行）
- `src/query.ts` - 查询状态机循环（约 1730 行）
- `src/query/config.ts` - 配置快照
- `src/query/deps.ts` - 依赖注入
- `src/query/stopHooks.ts` - Stop Hooks 处理
- `src/query/tokenBudget.ts` - Token 预算管理

---

## 2. 核心组件分析

### 2.1 QueryEngine 类 (`QueryEngine.ts`)

**设计模式**: 会话状态持有者

**核心职责**:
```typescript
export class QueryEngine {
  private config: QueryEngineConfig
  private mutableMessages: Message[]        // 可变消息历史
  private abortController: AbortController   // 中断控制
  private permissionDenials: SDKPermissionDenial[]  // 权限拒绝记录
  private totalUsage: NonNullableUsage       // 累计使用量
  private readFileState: FileStateCache      // 文件状态缓存
  private discoveredSkillNames: Set<string>  // 已发现技能
  private loadedNestedMemoryPaths: Set<string> // 嵌套内存路径
}
```

**关键方法**:

| 方法 | 职责 |
|------|------|
| `submitMessage()` | 异步生成器，处理用户输入并驱动查询循环 |
| `interrupt()` | 中断当前查询 |
| `getMessages()` | 获取消息历史 |
| `getReadFileState()` | 获取文件读取状态缓存 |
| `setModel()` | 动态切换模型 |

**配置结构** (`QueryEngineConfig`):
```typescript
type QueryEngineConfig = {
  cwd: string
  tools: Tools
  commands: Command[]
  mcpClients: MCPServerConnection[]
  agents: AgentDefinition[]
  canUseTool: CanUseToolFn
  getAppState: () => AppState
  setAppState: (f: (prev: AppState) => AppState) => void
  initialMessages?: Message[]
  readFileCache: FileStateCache
  customSystemPrompt?: string
  appendSystemPrompt?: string
  userSpecifiedModel?: string
  fallbackModel?: string
  thinkingConfig?: ThinkingConfig
  maxTurns?: number
  maxBudgetUsd?: number
  taskBudget?: { total: number }
  jsonSchema?: Record<string, unknown>
  // ... 更多配置项
}
```

### 2.2 query() 状态机函数 (`query.ts`)

**设计模式**: AsyncGenerator 状态机

**状态定义**:
```typescript
type State = {
  messages: Message[]
  toolUseContext: ToolUseContext
  autoCompactTracking: AutoCompactTrackingState | undefined
  maxOutputTokensRecoveryCount: number
  hasAttemptedReactiveCompact: boolean
  maxOutputTokensOverride: number | undefined
  pendingToolUseSummary: Promise<ToolUseSummaryMessage | null> | undefined
  stopHookActive: boolean | undefined
  turnCount: number
  transition: Continue | undefined  // 上一次迭代为何继续
}
```

**状态转换** (`Continue` 类型):
```typescript
type Continue = {
  reason:
    | 'collapse_drain_retry'      // 上下文坍缩后重试
    | 'reactive_compact_retry'    // 响应式压缩后重试
    | 'max_output_tokens_escalate' // 输出Token升级
    | 'max_output_tokens_recovery' // 输出Token恢复
    | 'stop_hook_blocking'        // Stop Hook阻塞
    | 'token_budget_continuation' // Token预算继续
    | 'next_turn'                 // 下一轮对话
}
```

**终止状态** (`Terminal` 类型):
```typescript
type Terminal = {
  reason:
    | 'completed'                 // 正常完成
    | 'aborted_streaming'         // 流式中断
    | 'aborted_tools'             // 工具执行中断
    | 'blocking_limit'            // 阻塞限制
    | 'prompt_too_long'           // 提示过长
    | 'image_error'               // 图像错误
    | 'model_error'               // 模型错误
    | 'stop_hook_prevented'       // Stop Hook阻止
    | 'hook_stopped'              // Hook停止
    | 'max_turns'                 // 达到最大轮次
}
```

### 2.3 QueryGuard 熔断器 (`utils/QueryGuard.ts`)

**设计模式**: 同步状态机 + React useSyncExternalStore

**三态模型**:
```
idle → dispatching → running → idle
```

**关键方法**:
```typescript
class QueryGuard {
  reserve(): boolean        // idle → dispatching
  cancelReservation(): void // dispatching → idle
  tryStart(): number | null // idle/dispatching → running
  end(generation): boolean  // running → idle
  forceEnd(): void          // 强制终止（用于取消）
  get isActive(): boolean   // 是否活跃
}
```

---

## 3. 关键代码解读

### 3.1 AsyncGenerator 模式

**设计优势**:
1. **流式输出**: 边产生边消费，减少内存占用
2. **可中断**: 支持用户取消操作
3. **状态传递**: 通过 `yield*` 委托子生成器

**submitMessage() 核心流程**:
```typescript
async *submitMessage(prompt, options): AsyncGenerator<SDKMessage> {
  // 1. 系统提示词构建
  const { defaultSystemPrompt, userContext, systemContext } =
    await fetchSystemPromptParts({ tools, mainLoopModel, ... })

  // 2. 用户输入处理
  const { messages: messagesFromUserInput, shouldQuery, ... } =
    await processUserInput({ input: prompt, mode: 'prompt', ... })

  // 3. 消息持久化
  this.mutableMessages.push(...messagesFromUserInput)
  await recordTranscript(messages)

  // 4. 驱动查询循环
  for await (const message of query({ messages, systemPrompt, ... })) {
    // 消息类型分发
    switch (message.type) {
      case 'assistant': yield* normalizeMessage(message); break
      case 'user': yield* normalizeMessage(message); break
      case 'progress': yield* normalizeMessage(message); break
      case 'attachment': /* 处理附件 */ break
      case 'stream_event': /* 处理流事件 */ break
    }
  }

  // 5. 返回最终结果
  yield { type: 'result', subtype: 'success', ... }
}
```

### 3.2 状态机循环

**主循环结构**:
```typescript
async function* queryLoop(params, consumedCommandUuids) {
  let state: State = { messages: params.messages, ... }

  while (true) {
    const { messages, toolUseContext, ... } = state

    // 1. 消息预处理
    let messagesForQuery = [...getMessagesAfterCompactBoundary(messages)]

    // 2. 应用 Snip 压缩
    if (feature('HISTORY_SNIP')) {
      const snipResult = snipModule!.snipCompactIfNeeded(messagesForQuery)
      messagesForQuery = snipResult.messages
    }

    // 3. 微压缩
    const microcompactResult = await deps.microcompact(messagesForQuery, ...)

    // 4. 自动压缩
    const { compactionResult } = await deps.autocompact(messagesForQuery, ...)

    // 5. API 调用
    for await (const message of deps.callModel({ messages, ... })) {
      // 处理流式响应
      if (message.type === 'assistant') {
        assistantMessages.push(message)
        if (msgToolUseBlocks.length > 0) {
          toolUseBlocks.push(...msgToolUseBlocks)
          needsFollowUp = true
        }
      }
      yield message
    }

    // 6. 工具执行
    if (needsFollowUp) {
      const toolUpdates = streamingToolExecutor
        ? streamingToolExecutor.getRemainingResults()
        : runTools(toolUseBlocks, assistantMessages, ...)

      for await (const update of toolUpdates) {
        yield update.message
      }
    }

    // 7. Stop Hooks
    const stopHookResult = yield* handleStopHooks(...)
    if (stopHookResult.preventContinuation) {
      return { reason: 'stop_hook_prevented' }
    }

    // 8. 状态更新并继续循环
    state = {
      messages: [...messagesForQuery, ...assistantMessages, ...toolResults],
      turnCount: nextTurnCount,
      transition: { reason: 'next_turn' },
      ...
    }
  }
}
```

### 3.3 流式 API 调用处理

**StreamingToolExecutor 核心机制**:
```typescript
class StreamingToolExecutor {
  private tools: TrackedTool[] = []

  // 添加工具到执行队列
  addTool(block: ToolUseBlock, assistantMessage: AssistantMessage): void {
    const isConcurrencySafe = toolDefinition.isConcurrencySafe(parsedInput)
    this.tools.push({ id: block.id, block, status: 'queued', isConcurrencySafe })
    void this.processQueue()
  }

  // 并发控制
  private canExecuteTool(isConcurrencySafe: boolean): boolean {
    const executingTools = this.tools.filter(t => t.status === 'executing')
    return executingTools.length === 0 ||
      (isConcurrencySafe && executingTools.every(t => t.isConcurrencySafe))
  }

  // 获取剩余结果
  async *getRemainingResults(): AsyncGenerator<MessageUpdate> {
    while (this.hasUnfinishedTools()) {
      await this.processQueue()
      for (const result of this.getCompletedResults()) {
        yield result
      }
    }
  }
}
```

### 3.4 工具编排

**并发策略**:
```typescript
async function* runTools(toolUseMessages, assistantMessages, ...) {
  for (const { isConcurrencySafe, blocks } of partitionToolCalls(toolUseMessages)) {
    if (isConcurrencySafe) {
      // 并发安全工具：并行执行
      yield* runToolsConcurrently(blocks, ...)
    } else {
      // 非并发安全工具：串行执行
      yield* runToolsSerially(blocks, ...)
    }
  }
}
```

---

## 4. 设计亮点

### 4.1 状态机设计

**优势**:
- 清晰的转换路径（`transition.reason` 记录每次继续的原因）
- 可预测的终止条件（`Terminal` 类型）
- 易于测试和调试

### 4.2 Token 预算管理

**预算追踪器**:
```typescript
type BudgetTracker = {
  continuationCount: number      // 继续计数
  lastDeltaTokens: number        // 上次增量
  lastGlobalTurnTokens: number   // 上次全局轮次Token
  startedAt: number              // 开始时间
}

function checkTokenBudget(tracker, agentId, budget, globalTurnTokens): TokenBudgetDecision {
  // 子代理或无预算 → 停止
  if (agentId || budget === null) return { action: 'stop' }

  // 收益递减检测
  const isDiminishing =
    tracker.continuationCount >= 3 &&
    deltaSinceLastCheck < DIMINISHING_THRESHOLD

  // 继续条件：未达到90%且无收益递减
  if (!isDiminishing && turnTokens < budget * 0.9) {
    return { action: 'continue', nudgeMessage: getBudgetContinuationMessage(...) }
  }

  return { action: 'stop', completionEvent: { ... } }
}
```

### 4.3 自动压缩机制

**多层次压缩**:
1. **Snip Compact** - 快速截断旧消息
2. **Microcompact** - 缓存编辑优化
3. **Autocompact** - 完整摘要压缩
4. **Reactive Compact** - 响应式压缩（413错误后）

### 4.4 恢复机制

**错误恢复路径**:
```typescript
// Prompt-too-long 恢复
if (isWithheld413) {
  // 1. 先尝试 collapse drain
  if (contextCollapse && state.transition?.reason !== 'collapse_drain_retry') {
    const drained = contextCollapse.recoverFromOverflow(messagesForQuery, querySource)
    if (drained.committed > 0) {
      state = { messages: drained.messages, transition: { reason: 'collapse_drain_retry' } }
      continue
    }
  }

  // 2. 再尝试 reactive compact
  if (reactiveCompact) {
    const compacted = await reactiveCompact.tryReactiveCompact({ ... })
    if (compacted) {
      state = { messages: postCompactMessages, transition: { reason: 'reactive_compact_retry' } }
      continue
    }
  }
}
```

### 4.5 依赖注入模式

**测试友好设计**:
```typescript
type QueryDeps = {
  callModel: typeof queryModelWithStreaming
  microcompact: typeof microcompactMessages
  autocompact: typeof autoCompactIfNeeded
  uuid: () => string
}

function productionDeps(): QueryDeps {
  return {
    callModel: queryModelWithStreaming,
    microcompact: microcompactMessages,
    autocompact: autoCompactIfNeeded,
    uuid: randomUUID,
  }
}
```

---

## 5. 与其他模块交互

### 5.1 工具系统

```
QueryEngine
    │
    ├── toolOrchestration.ts ── runTools()
    │       │
    │       ├── StreamingToolExecutor (并发执行)
    │       │       └── runToolUse() → ToolDefinition.run()
    │       │
    │       └── runToolsSerially (串行执行)
    │               └── runToolUse() → ToolDefinition.run()
    │
    └── ToolUseContext (上下文传递)
            ├── options.tools (工具定义)
            ├── abortController (中断控制)
            └── readFileState (文件状态)
```

### 5.2 消息系统

```
Message Types:
├── UserMessage         - 用户消息
├── AssistantMessage    - 助手消息
├── SystemMessage       - 系统消息 (compact_boundary, api_error, ...)
├── AttachmentMessage   - 附件消息 (edited_text_file, ...)
├── ProgressMessage     - 进度消息
├── ToolUseSummaryMessage - 工具使用摘要
├── TombstoneMessage    - 墓碑消息 (删除标记)
└── StreamEvent         - 流事件 (message_start, message_delta, message_stop)
```

### 5.3 API 客户端

```
query()
    │
    └── queryModelWithStreaming() (services/api/claude.ts)
            │
            ├── client.beta.messages.create() (Anthropic SDK)
            │
            ├── withRetry() (重试机制)
            │
            └── VCR (录制/回放)
```

---

## 6. 文件路径索引

| 文件 | 行数 | 职责 |
|------|------|------|
| `src/QueryEngine.ts` | ~1300 | 查询引擎类，会话状态管理 |
| `src/query.ts` | ~1730 | 查询状态机循环 |
| `src/query/config.ts` | ~47 | 配置快照构建 |
| `src/query/deps.ts` | ~41 | 依赖注入类型和工厂 |
| `src/query/stopHooks.ts` | ~474 | Stop Hooks 处理 |
| `src/query/tokenBudget.ts` | ~94 | Token 预算检查 |
| `src/utils/QueryGuard.ts` | ~122 | 查询熔断器 |
| `src/utils/queryContext.ts` | ~180 | 系统提示词构建辅助 |
| `src/utils/queryHelpers.ts` | ~553 | 查询辅助函数 |
| `src/services/tools/toolOrchestration.ts` | ~189 | 工具编排 |
| `src/services/tools/StreamingToolExecutor.ts` | ~531 | 流式工具执行器 |
| `src/services/api/claude.ts` | ~2500+ | API 客户端封装 |

---

## 7. 总结

QueryEngine 是 Claude Code 的核心引擎，采用了多项现代软件工程最佳实践：

1. **AsyncGenerator 模式** - 实现流式输出和可中断操作
2. **状态机设计** - 清晰的状态转换和终止条件
3. **依赖注入** - 便于测试和模块解耦
4. **熔断器模式** - 防止并发查询冲突
5. **多层次压缩** - 智能管理上下文窗口
6. **弹性恢复** - 自动处理 Token 限制和 API 错误

这种架构设计使得 Claude Code 能够处理长时间运行的对话会话，同时保持响应性和可维护性。