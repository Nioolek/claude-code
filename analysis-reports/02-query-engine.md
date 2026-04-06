# Claude Code Query Engine 深度分析报告

## 模块概述

QueryEngine 是 Claude Code 的「心脏引擎」，就像**一个智能对话管家**——管理对话生命周期、执行 API 调用、编排工具执行、处理消息流以及管理 Token 预算。

### 核心职责

1. **对话生命周期管理**：维护消息历史，支持中断和恢复
2. **API 调用编排**：流式调用 Anthropic API，处理重试和错误
3. **工具执行调度**：并发/串行执行工具，管理权限检查
4. **Token 预算控制**：多层次压缩，智能预算管理
5. **消息流处理**：AsyncGenerator 模式实现流式输出

### 生活化类比

| 概念 | 类比 | 说明 |
|------|------|------|
| `QueryEngine` | 对话管家 | 管理整个对话会话 |
| `query()` | 状态机循环 | 像电话交换机处理各种状态 |
| `StreamingToolExecutor` | 并发调度员 | 同时处理多个工具请求 |
| `QueryGuard` | 熔断器 | 防止多个查询同时执行 |
| `Continue` 类型 | 继续令牌 | 记录为什么继续循环 |
| `Terminal` 类型 | 终止令牌 | 记录为什么结束循环 |

---

## 核心组件详解

### 1. QueryEngine 类（src/QueryEngine.ts）

**设计模式**：会话状态持有者

QueryEngine 就像**一个对话管家**，持有整个会话的状态：

```typescript
export class QueryEngine {
  // 会话状态
  private config: QueryEngineConfig           // 配置快照
  private mutableMessages: Message[]          // 可变消息历史
  private abortController: AbortController    // 中断控制
  private permissionDenials: SDKPermissionDenial[]  // 权限拒绝记录
  private totalUsage: NonNullableUsage        // 累计使用量

  // 缓存状态
  private readFileState: FileStateCache       // 文件状态缓存
  private discoveredSkillNames: Set<string>   // 已发现技能
  private loadedNestedMemoryPaths: Set<string> // 嵌套内存路径
}
```

**关键方法职责**：

| 方法 | 职责 | 生活类比 |
|------|------|----------|
| `submitMessage()` | 处理用户输入，驱动查询循环 | 接听电话并转接 |
| `interrupt()` | 中断当前查询 | 挂断电话 |
| `getMessages()` | 获取消息历史 | 查看通话记录 |
| `getReadFileState()` | 获取文件读取状态缓存 | 查看书签 |
| `setModel()` | 动态切换模型 | 更换翻译官 |

### 2. query() 状态机（src/query.ts）

**设计模式**：AsyncGenerator 状态机

query() 函数是一个复杂的**状态机循环**，就像一个电话交换机，不断处理各种状态转换：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    query() 状态机循环                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                        ┌─────────────────┐                                  │
│                        │    开始状态      │                                  │
│                        │  messages: []   │                                  │
│                        │  turnCount: 0   │                                  │
│                        └────────┬────────┘                                  │
│                                 │                                            │
│                                 ▼                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                          主循环开始                                    │  │
│  │                                                                       │  │
│  │   ┌─────────────────────────────────────────────────────────────┐    │  │
│  │   │ Step 1: 消息预处理                                          │    │  │
│  │   │                                                             │    │  │
│  │   │ • getMessagesAfterCompactBoundary() - 获取压缩边界后消息   │    │  │
│  │   │ • snipCompactIfNeeded() - Snip 压缩（快速截断）            │    │  │
│  │   │ • microcompact() - 微压缩（缓存编辑优化）                  │    │  │
│  │   │ • autocompact() - 自动压缩（完整摘要）                     │    │  │
│  │   └─────────────────────────────────────────────────────────────┘    │  │
│  │                                 │                                     │  │
│  │                                 ▼                                     │  │
│  │   ┌─────────────────────────────────────────────────────────────┐    │  │
│  │   │ Step 2: API 调用                                           │    │  │
│  │   │                                                             │    │  │
│  │   │ callModel() → Anthropic API 流式响应                       │    │  │
│  │   │                                                             │    │  │
│  │   │ • message_start - 消息开始                                  │    │  │
│  │   │ • content_block_start - 内容块开始                         │    │  │
│  │   │ • content_block_delta - 内容块增量                         │    │  │
│  │   │ • content_block_stop - 内容块结束                          │    │  │
│  │   │ • message_delta - 消息增量                                  │    │  │
│  │   │ • message_stop - 消息结束                                   │    │  │
│  │   └─────────────────────────────────────────────────────────────┘    │  │
│  │                                 │                                     │  │
│  │                                 ▼                                     │  │
│  │   ┌─────────────────────────────────────────────────────────────┐    │  │
│  │   │ Step 3: 工具执行判断                                        │    │  │
│  │   │                                                             │    │  │
│  │   │ if (toolUseBlocks.length > 0) {                            │    │  │
│  │   │   needsFollowUp = true                                      │    │  │
│  │   │ }                                                           │    │  │
│  │   └─────────────────────────────────────────────────────────────┘    │  │
│  │                                 │                                     │  │
│  │                    ┌────────────┴────────────┐                       │  │
│  │                    │                         │                       │  │
│  │                    ▼                         ▼                       │  │
│  │   ┌─────────────────────┐    ┌─────────────────────┐               │  │
│  │   │  有工具调用          │    │  无工具调用          │               │  │
│  │   │  needsFollowUp=true │    │  needsFollowUp=false│               │  │
│  │   └──────────┬──────────┘    └──────────┬──────────┘               │  │
│  │              │                          │                          │  │
│  │              ▼                          │                          │  │
│  │   ┌─────────────────────┐               │                          │  │
│  │   │ Step 4: 工具执行     │               │                          │  │
│  │   │                     │               │                          │  │
│  │   │ runTools()          │               │                          │  │
│  │   │ ├─ 并发安全：并行    │               │                          │  │
│  │   │ └─ 非安全：串行      │               │                          │  │
│  │   └──────────┬──────────┘               │                          │  │
│  │              │                          │                          │  │
│  │              └────────────┬─────────────┘                          │  │
│  │                           │                                        │  │
│  │                           ▼                                        │  │
│  │   ┌─────────────────────────────────────────────────────────────┐  │  │
│  │   │ Step 5: Stop Hooks 处理                                     │  │  │
│  │   │                                                             │  │  │
│  │   │ handleStopHooks()                                           │  │  │
│  │   │ • 执行 PostToolUse hooks                                    │  │  │
│  │   │ • 执行 Stop hooks                                           │  │  │
│  │   │ • 决定是否继续                                              │  │  │
│  │   └─────────────────────────────────────────────────────────────┘  │  │
│  │                           │                                        │  │
│  │              ┌────────────┴────────────┐                          │  │
│  │              │                         │                          │  │
│  │              ▼                         ▼                          │  │
│  │   ┌─────────────────────┐    ┌─────────────────────┐             │  │
│  │   │  阻止继续            │    │  允许继续            │             │  │
│  │   │  preventContinuation │    │  继续下一轮          │             │  │
│  │   └──────────┬──────────┘    └──────────┬──────────┘             │  │
│  │              │                          │                        │  │
│  │              ▼                          ▼                        │  │
│  │   ┌─────────────────────┐    ┌─────────────────────┐             │  │
│  │   │  终止状态            │    │  状态更新            │             │  │
│  │   │  Terminal           │    │  transition:        │             │  │
│  │   │  reason: 'stopped'  │    │    'next_turn'      │             │  │
│  │   └─────────────────────┘    │  turnCount++        │             │  │
│  │                              └──────────┬──────────┘             │  │
│  │                                         │                        │  │
│  │                                         └──────► 返回循环顶部    │  │
│  │                                                                  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. 状态转换详解

**Continue 类型（继续循环的原因）**：

```typescript
type Continue = {
  reason:
    | 'collapse_drain_retry'       // 上下文坍缩后重试
    | 'reactive_compact_retry'     // 响应式压缩后重试
    | 'max_output_tokens_escalate' // 输出 Token 升级
    | 'max_output_tokens_recovery' // 输出 Token 恢复
    | 'stop_hook_blocking'         // Stop Hook 阻塞
    | 'token_budget_continuation'  // Token 预算继续
    | 'next_turn'                  // 下一轮对话
}
```

**Terminal 类型（终止循环的原因）**：

```typescript
type Terminal = {
  reason:
    | 'completed'                  // 正常完成
    | 'aborted_streaming'          // 流式中断
    | 'aborted_tools'              // 工具执行中断
    | 'blocking_limit'             // 阻塞限制
    | 'prompt_too_long'            // 提示过长
    | 'image_error'                // 图像错误
    | 'model_error'                // 模型错误
    | 'stop_hook_prevented'        // Stop Hook 阻止
    | 'hook_stopped'               // Hook 停止
    | 'max_turns'                  // 达到最大轮次
}
```

### 4. QueryGuard 熔断器

**生活类比**：电路熔断器，防止过载

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    QueryGuard 三态模型                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│         ┌─────────────────────────────────────────────────────────────┐     │
│         │                                                             │     │
│         │                      ┌───────────┐                          │     │
│         │                      │   idle    │                          │     │
│         │                      │  (空闲)   │                          │     │
│         │                      └─────┬─────┘                          │     │
│         │                            │                                │     │
│         │          reserve()         │                                │     │
│         │          预定成功          ▼                                │     │
│         │                      ┌───────────┐                          │     │
│         │                      │dispatching│                          │     │
│         │                      │  (调度中)  │                          │     │
│         │                      └─────┬─────┘                          │     │
│         │                            │                                │     │
│         │          tryStart()        │                                │     │
│         │          开始成功          ▼                                │     │
│         │                      ┌───────────┐                          │     │
│         │                      │  running  │                          │     │
│         │                      │  (运行中)  │                          │     │
│         │                      └─────┬─────┘                          │     │
│         │                            │                                │     │
│         │          end()             │                                │     │
│         │          结束              ▼                                │     │
│         │                      ┌───────────┐                          │     │
│         │                      │   idle    │◄─────────────────────────┤     │
│         │                      │  (空闲)   │   forceEnd() 强制终止    │     │
│         │                      └───────────┘                          │     │
│         │                                                             │     │
│         └─────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  关键方法：                                                                  │
│  • reserve(): boolean      - idle → dispatching                            │
│  • cancelReservation(): void - dispatching → idle                          │
│  • tryStart(): number | null - idle/dispatching → running                  │
│  • end(generation): boolean - running → idle                               │
│  • forceEnd(): void        - 强制终止（用于取消）                           │
│  • get isActive: boolean   - 是否活跃                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 关键代码解读

### 1. submitMessage() 核心流程

```typescript
// src/QueryEngine.ts

async *submitMessage(prompt, options): AsyncGenerator<SDKMessage> {
  // Step 1: 系统提示词构建
  const { defaultSystemPrompt, userContext, systemContext } =
    await fetchSystemPromptParts({
      tools: this.config.tools,
      mainLoopModel: this.config.userSpecifiedModel,
      // ...
    });

  const systemPrompt = [
    defaultSystemPrompt,
    userContext && `<user_context>${userContext}</user_context>`,
    systemContext && `<system_context>${systemContext}</system_context>`,
  ].filter(Boolean).join('\n\n');

  // Step 2: 用户输入处理
  const { messages: messagesFromUserInput, shouldQuery } =
    await processUserInput({
      input: prompt,
      mode: 'prompt',
      readFileState: this.readFileState,
      // ...
    });

  // Step 3: 消息持久化
  this.mutableMessages.push(...messagesFromUserInput);
  await recordTranscript(this.mutableMessages);

  // Step 4: 驱动查询循环
  for await (const message of query({
    messages: this.mutableMessages,
    systemPrompt,
    tools: this.config.tools,
    abortController: this.abortController,
    // ...
  })) {
    // 消息类型分发
    switch (message.type) {
      case 'assistant':
        yield* normalizeMessage(message);
        break;
      case 'user':
        yield* normalizeMessage(message);
        break;
      case 'progress':
        yield* normalizeMessage(message);
        break;
      case 'attachment':
        // 处理附件（如编辑后的文件）
        break;
      case 'stream_event':
        // 处理流事件（SDK 模式）
        break;
    }
  }

  // Step 5: 返回最终结果
  yield {
    type: 'result',
    subtype: 'success',
    totalCostUsd: this.totalUsage.cost,
    // ...
  };
}
```

### 2. 状态机主循环

```typescript
// src/query.ts

async function* queryLoop(params, consumedCommandUuids) {
  let state: State = {
    messages: params.messages,
    turnCount: 0,
    transition: undefined,
    // ...
  };

  // 主循环
  while (true) {
    const { messages, toolUseContext, turnCount } = state;

    // ─────────────────────────────────────────────────────────────────
    // Phase 1: 消息预处理
    // ─────────────────────────────────────────────────────────────────
    let messagesForQuery = [...getMessagesAfterCompactBoundary(messages)];

    // Snip 压缩（快速截断旧消息）
    if (feature('HISTORY_SNIP')) {
      const snipResult = snipModule!.snipCompactIfNeeded(messagesForQuery);
      messagesForQuery = snipResult.messages;
    }

    // 微压缩（缓存编辑优化）
    const microcompactResult = await deps.microcompact(messagesForQuery, ...);

    // 自动压缩（完整摘要）
    const { compactionResult } = await deps.autocompact(messagesForQuery, ...);

    // ─────────────────────────────────────────────────────────────────
    // Phase 2: API 调用
    // ─────────────────────────────────────────────────────────────────
    const assistantMessages: AssistantMessage[] = [];
    const toolUseBlocks: ToolUseBlock[] = [];
    let needsFollowUp = false;

    for await (const message of deps.callModel({ messages: messagesForQuery, ... })) {
      yield message;  // 流式输出

      if (message.type === 'assistant') {
        assistantMessages.push(message);
        const msgToolUseBlocks = message.content.filter(c => c.type === 'tool_use');
        if (msgToolUseBlocks.length > 0) {
          toolUseBlocks.push(...msgToolUseBlocks);
          needsFollowUp = true;
        }
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Phase 3: 工具执行
    // ─────────────────────────────────────────────────────────────────
    if (needsFollowUp) {
      const toolUpdates = streamingToolExecutor
        ? streamingToolExecutor.getRemainingResults()
        : runTools(toolUseBlocks, assistantMessages, toolUseContext);

      for await (const update of toolUpdates) {
        yield update.message;
      }
    }

    // ─────────────────────────────────────────────────────────────────
    // Phase 4: Stop Hooks
    // ─────────────────────────────────────────────────────────────────
    const stopHookResult = yield* handleStopHooks(...);
    if (stopHookResult.preventContinuation) {
      return { reason: 'stop_hook_prevented' };
    }

    // ─────────────────────────────────────────────────────────────────
    // Phase 5: 状态更新
    // ─────────────────────────────────────────────────────────────────
    state = {
      messages: [...messagesForQuery, ...assistantMessages, ...toolResults],
      turnCount: turnCount + 1,
      transition: { reason: 'next_turn' },
    };
  }
}
```

### 3. StreamingToolExecutor 并发控制

```typescript
// src/services/tools/StreamingToolExecutor.ts

class StreamingToolExecutor {
  private tools: TrackedTool[] = [];

  // 添加工具到执行队列
  addTool(block: ToolUseBlock, assistantMessage: AssistantMessage): void {
    const toolDefinition = findToolByName(this.tools, block.name);
    const parsedInput = toolDefinition.inputSchema.safeParse(block.input);
    const isConcurrencySafe = toolDefinition.isConcurrencySafe(parsedInput);

    this.tools.push({
      id: block.id,
      block,
      status: 'queued',
      isConcurrencySafe,
    });

    // 异步处理队列
    void this.processQueue();
  }

  // 并发控制决策
  private canExecuteTool(isConcurrencySafe: boolean): boolean {
    const executingTools = this.tools.filter(t => t.status === 'executing');

    // 规则 1: 没有执行中的工具 → 可以执行
    if (executingTools.length === 0) return true;

    // 规则 2: 当前工具并发安全 + 所有执行中的工具并发安全 → 可以执行
    if (isConcurrencySafe && executingTools.every(t => t.isConcurrencySafe)) {
      return true;
    }

    // 否则等待
    return false;
  }

  // 获取剩余结果
  async *getRemainingResults(): AsyncGenerator<MessageUpdate> {
    while (this.hasUnfinishedTools()) {
      await this.processQueue();
      for (const result of this.getCompletedResults()) {
        yield result;
      }
    }
  }
}
```

### 4. Token 预算检查

```typescript
// src/query/tokenBudget.ts

type BudgetTracker = {
  continuationCount: number      // 继续计数
  lastDeltaTokens: number        // 上次增量
  lastGlobalTurnTokens: number   // 上次全局轮次 Token
  startedAt: number              // 开始时间
};

function checkTokenBudget(
  tracker: BudgetTracker,
  agentId: string | undefined,
  budget: number | null,
  globalTurnTokens: number
): TokenBudgetDecision {

  // 子代理或无预算 → 停止
  if (agentId || budget === null) {
    return { action: 'stop' };
  }

  // 收益递减检测
  const deltaSinceLastCheck = globalTurnTokens - tracker.lastGlobalTurnTokens;
  const isDiminishing =
    tracker.continuationCount >= 3 &&
    deltaSinceLastCheck < DIMINISHING_THRESHOLD;

  // 继续条件：未达到 90% 且无收益递减
  if (!isDiminishing && globalTurnTokens < budget * 0.9) {
    return {
      action: 'continue',
      nudgeMessage: getBudgetContinuationMessage(tracker, budget, globalTurnTokens),
    };
  }

  // 达到限制 → 停止
  return {
    action: 'stop',
    completionEvent: {
      reason: 'token_budget',
      totalTokens: globalTurnTokens,
      budgetUsed: globalTurnTokens / budget,
    },
  };
}
```

---

## 设计亮点

### 1. AsyncGenerator 模式

**生活类比**：流水线传送带

AsyncGenerator 模式就像**流水线传送带**——产品（消息）一个接一个地生产出来，消费者可以边生产边消费，不需要等待整批完成。

```
优势：
1. 流式输出 - 边产生边消费，减少内存占用
2. 可中断 - 支持用户取消操作
3. 状态传递 - 通过 yield* 委托子生成器
```

### 2. 多层次压缩机制

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    四层压缩策略                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Layer 1: Snip Compact（快速截断）                                      │  │
│  │                                                                        │  │
│  │ • 速度：最快                                                           │  │
│  │ • 策略：直接截断旧消息                                                 │  │
│  │ • 场景：上下文接近限制时的快速响应                                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Layer 2: Microcompact（微压缩）                                        │  │
│  │                                                                        │  │
│  │ • 速度：快                                                             │  │
│  │ • 策略：缓存编辑优化，合并重复操作                                     │  │
│  │ • 场景：编辑密集型对话                                                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Layer 3: Autocompact（自动压缩）                                       │  │
│  │                                                                        │  │
│  │ • 速度：中等                                                           │  │
│  │ • 策略：LLM 生成摘要                                                   │  │
│  │ • 场景：上下文超过阈值时自动触发                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Layer 4: Reactive Compact（响应式压缩）                                │  │
│  │                                                                        │  │
│  │ • 速度：慢（需要额外 API 调用）                                        │  │
│  │ • 策略：413 错误后的恢复压缩                                           │  │
│  │ • 场景：API 返回 prompt_too_long 错误                                  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. 错误恢复机制

```typescript
// Prompt-too-long 恢复流程
if (isWithheld413) {
  // 尝试 1: collapse drain（排空上下文）
  if (contextCollapse && state.transition?.reason !== 'collapse_drain_retry') {
    const drained = contextCollapse.recoverFromOverflow(messagesForQuery, querySource);
    if (drained.committed > 0) {
      state = {
        messages: drained.messages,
        transition: { reason: 'collapse_drain_retry' }
      };
      continue;  // 重试
    }
  }

  // 尝试 2: reactive compact（响应式压缩）
  if (reactiveCompact) {
    const compacted = await reactiveCompact.tryReactiveCompact({ ... });
    if (compacted) {
      state = {
        messages: postCompactMessages,
        transition: { reason: 'reactive_compact_retry' }
      };
      continue;  // 重试
    }
  }

  // 恢复失败 → 终止
  return { reason: 'prompt_too_long' };
}
```

### 4. 依赖注入模式

**生活类比**：可更换零件的设计

```typescript
// 依赖类型定义
type QueryDeps = {
  callModel: typeof queryModelWithStreaming
  microcompact: typeof microcompactMessages
  autocompact: typeof autoCompactIfNeeded
  uuid: () => string
};

// 生产环境依赖
function productionDeps(): QueryDeps {
  return {
    callModel: queryModelWithStreaming,
    microcompact: microcompactMessages,
    autocompact: autoCompactIfNeeded,
    uuid: randomUUID,
  };
}

// 测试环境依赖
function testDeps(overrides: Partial<QueryDeps>): QueryDeps {
  return {
    ...productionDeps(),
    ...overrides,
  };
}
```

---

## 模块交互图

```
                    ┌─────────────────────────────────────────────────────────────┐
                    │                       QueryEngine                           │
                    │                      (会话状态持有者)                        │
                    └───────────────────────────────┬─────────────────────────────┘
                                                    │
                                                    ▼
                    ┌─────────────────────────────────────────────────────────────┐
                    │                        query()                              │
                    │                    (状态机循环)                              │
                    │                                                             │
                    │   ┌─────────────────────────────────────────────────────┐  │
                    │   │  消息预处理                                          │  │
                    │   │  ├─ snipCompact()                                    │  │
                    │   │  ├─ microcompact()                                   │  │
                    │   │  └─ autocompact()                                    │  │
                    │   └─────────────────────────────────────────────────────┘  │
                    │                           │                                │
                    │                           ▼                                │
                    │   ┌─────────────────────────────────────────────────────┐  │
                    │   │  API 调用                                            │  │
                    │   │  └─ queryModelWithStreaming()                        │  │
                    │   │       └─ Anthropic SDK                               │  │
                    │   └─────────────────────────────────────────────────────┘  │
                    │                           │                                │
                    │                           ▼                                │
                    │   ┌─────────────────────────────────────────────────────┐  │
                    │   │  工具执行                                            │  │
                    │   │  └─ runTools()                                       │  │
                    │   │       ├─ StreamingToolExecutor (并发)               │  │
                    │   │       └─ runToolsSerially (串行)                     │  │
                    │   └─────────────────────────────────────────────────────┘  │
                    │                           │                                │
                    │                           ▼                                │
                    │   ┌─────────────────────────────────────────────────────┐  │
                    │   │  Stop Hooks                                          │  │
                    │   │  └─ handleStopHooks()                                │  │
                    │   └─────────────────────────────────────────────────────┘  │
                    │                                                             │
                    └─────────────────────────────────────────────────────────────┘
                                                    │
                     ┌──────────────────────────────┼──────────────────────────────┐
                     │                              │                              │
                     ▼                              ▼                              ▼
        ┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
        │     工具系统         │      │     消息系统         │      │     API 客户端       │
        │                     │      │                     │      │                     │
        │ • ToolDefinition    │      │ • UserMessage       │      │ • Anthropic SDK    │
        │ • runToolUse()      │      │ • AssistantMessage  │      │ • 重试机制          │
        │ • 权限检查          │      │ • ProgressMessage   │      │ • VCR 录制/回放     │
        └─────────────────────┘      └─────────────────────┘      └─────────────────────┘
```

---

## 文件路径索引

| 分类 | 文件 | 行数 | 职责说明 |
|------|------|------|----------|
| **核心** | `src/QueryEngine.ts` | ~1300 | 查询引擎类，会话状态管理 |
| **核心** | `src/query.ts` | ~1730 | 查询状态机循环 |
| **配置** | `src/query/config.ts` | ~47 | 配置快照构建 |
| **依赖** | `src/query/deps.ts` | ~41 | 依赖注入类型和工厂 |
| **Hooks** | `src/query/stopHooks.ts` | ~474 | Stop Hooks 处理 |
| **预算** | `src/query/tokenBudget.ts` | ~94 | Token 预算检查 |
| **熔断** | `src/utils/QueryGuard.ts` | ~122 | 查询熔断器 |
| **辅助** | `src/utils/queryContext.ts` | ~180 | 系统提示词构建辅助 |
| **辅助** | `src/utils/queryHelpers.ts` | ~553 | 查询辅助函数 |
| **工具** | `src/services/tools/toolOrchestration.ts` | ~189 | 工具编排 |
| **流式** | `src/services/tools/StreamingToolExecutor.ts` | ~531 | 流式工具执行器 |
| **API** | `src/services/api/claude.ts` | ~2500+ | API 客户端封装 |

---

## 总结

QueryEngine 是 Claude Code 的核心引擎，采用了多项现代软件工程最佳实践：

1. **AsyncGenerator 模式** - 实现流式输出和可中断操作，就像流水线传送带
2. **状态机设计** - 清晰的状态转换（Continue）和终止条件（Terminal）
3. **依赖注入** - 便于测试和模块解耦，就像可更换零件的设计
4. **熔断器模式** - 防止并发查询冲突，就像电路保险丝
5. **多层次压缩** - 四层压缩策略智能管理上下文窗口
6. **弹性恢复** - 自动处理 Token 限制和 API 错误

这种架构设计使得 Claude Code 能够处理长时间运行的对话会话，同时保持响应性和可维护性