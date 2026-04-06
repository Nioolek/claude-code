# Claude Code 自动压缩机制深度分析

## 1. 核心概念与架构

### 1.1 什么是自动压缩 (Auto-Compact)

自动压缩是 Claude Code 的**上下文窗口管理机制**，当对话 token 数接近模型上下文限制时，系统自动将历史对话压缩成摘要，释放上下文空间。

**核心目标：**
- 防止对话超出模型上下文窗口导致 API 错误
- 保持对话连续性，用户无需手动清理
- 在有限的 token 预算内最大化保留有用上下文

### 1.2 两种压缩模式

| 模式 | 触发方式 | 执行时机 | 特点 |
|------|---------|---------|------|
| **Session Memory Compact** | 优先尝试 | 每次应自动压缩时 | 轻量级，直接使用已提取的 session memory，无需调用 API |
| **Full Compact** | Session Memory 失败时 fallback | Session Memory 不可用时 | 重量级，调用 forked agent 生成摘要，消耗 API token |

---

## 2. Token 预算与阈值管理

### 2.1 核心常量定义

```typescript
// src/services/compact/autoCompact.ts

// 为摘要输出预留的 token 数（基于 p99.99 分位数 17,387 tokens）
const MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000

// 自动压缩缓冲区（触发阈值与安全线的距离）
export const AUTOCOMPACT_BUFFER_TOKENS = 13_000

// 警告/错误/手动压缩的缓冲区
export const WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
export const ERROR_THRESHOLD_BUFFER_TOKENS = 20_000
export const MANUAL_COMPACT_BUFFER_TOKENS = 3_000

// 断路器：连续失败超过此次数则停止尝试
const MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
```

### 2.2 有效上下文窗口计算

```typescript
export function getEffectiveContextWindowSize(model: string): number {
  const reservedTokensForSummary = Math.min(
    getMaxOutputTokensForModel(model),
    MAX_OUTPUT_TOKENS_FOR_SUMMARY,  // 20,000
  )
  
  let contextWindow = getContextWindowForModel(model, getSdkBetas())
  
  // 支持环境变量覆盖（用于测试）
  const autoCompactWindow = process.env.CLAUDE_CODE_AUTO_COMPACT_WINDOW
  if (autoCompactWindow) {
    const parsed = parseInt(autoCompactWindow, 10)
    if (!isNaN(parsed) && parsed > 0) {
      contextWindow = Math.min(contextWindow, parsed)
    }
  }
  
  return contextWindow - reservedTokensForSummary
}
```

**计算示例（Claude 3.7 Sonnet，200K 上下文）：**
```
模型上下文窗口：200,000 tokens
预留输出空间：  -20,000 tokens
─────────────────────────────
有效上下文窗口：180,000 tokens
```

### 2.3 自动压缩触发阈值

```typescript
export function getAutoCompactThreshold(model: string): number {
  const effectiveContextWindow = getEffectiveContextWindowSize(model)
  
  const autocompactThreshold = effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS
  
  // 支持测试覆盖（百分比形式）
  const envPercent = process.env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE
  if (envPercent) {
    const parsed = parseFloat(envPercent)
    if (!isNaN(parsed) && parsed > 0 && parsed <= 100) {
      const percentageThreshold = Math.floor(
        effectiveContextWindow * (parsed / 100),
      )
      return Math.min(percentageThreshold, autocompactThreshold)
    }
  }
  
  return autocompactThreshold
}
```

**触发阈值计算示例：**
```
有效上下文窗口：180,000 tokens
缓冲区：        -13,000 tokens
─────────────────────────────
自动压缩触发点：167,000 tokens (约 92.8% 使用率)
```

### 2.4 Token 警告状态系统

```typescript
type TokenWarningState = {
  percentLeft: number              // 剩余百分比
  isAboveWarningThreshold: boolean // 超过警告线 (~88.9%)
  isAboveErrorThreshold: boolean   // 超过错误线 (~88.9%)
  isAboveAutoCompactThreshold: boolean // 超过自动压缩线 (~92.8%)
  isAtBlockingLimit: boolean       // 达到阻塞限制 (~98.3%)
}
```

**各阈值位置（以 180K 有效窗口为例）：**

```
0% ────────────────────────────────────────────────────────────── 100%
│                                                                │
│  自动压缩触发点                                                 │ 阻塞限制
│  ↓ (167K tokens)                                               │ ↓ (177K tokens)
│  ┌──────────────────────────────────────────────────────┐     │
│  │  安全区：可正常对话                                   │     │
│  └──────────────────────────────────────────────────────┘     │
│                                                                │
│                          警告/错误线                            │
│                          ↓ (160K tokens)                       │
```

---

## 3. 自动压缩触发逻辑

### 3.1 shouldAutoCompact 函数详解

```typescript
export async function shouldAutoCompact(
  messages: Message[],
  model: string,
  querySource?: QuerySource,
  snipTokensFreed = 0,  // snip 操作释放的 token 估算值
): Promise<boolean>
```

**触发条件检查（按顺序）：**

```typescript
// 1. 递归保护：防止死循环
if (querySource === 'session_memory' || querySource === 'compact') {
  return false  // session_memory 和 compact 是 forked agents，会死锁
}

// 2. Context Collapse 模式保护
if (feature('CONTEXT_COLLAPSE')) {
  if (querySource === 'marble_origami') {  // context-agent
    return false  // 防止破坏 main thread 的 committed log
  }
}

// 3. 用户配置检查
if (!isAutoCompactEnabled()) {
  return false
}

// 4. Reactive-only 模式（实验性功能）
if (feature('REACTIVE_COMPACT')) {
  if (getFeatureValue_CACHED_MAY_BE_STALE('tengu_cobalt_raccoon', false)) {
    return false  // 仅依赖 API 的 prompt-too-long 错误触发
  }
}

// 5. Context Collapse 模式
if (feature('CONTEXT_COLLAPSE') && isContextCollapseEnabled()) {
  return false  // Collapse 系统自己管理上下文
}

// 6. Token 计数检查
const tokenCount = tokenCountWithEstimation(messages) - snipTokensFreed
const threshold = getAutoCompactThreshold(model)

return tokenCount >= threshold
```

### 3.2 启用状态检查

```typescript
export function isAutoCompactEnabled(): boolean {
  // 环境变量优先级最高
  if (isEnvTruthy(process.env.DISABLE_COMPACT)) {
    return false  // 禁用所有压缩
  }
  if (isEnvTruthy(process.env.DISABLE_AUTO_COMPACT)) {
    return false  // 仅禁用自动压缩，手动 /compact 仍可用
  }
  
  // 用户配置
  const userConfig = getGlobalConfig()
  return userConfig.autoCompactEnabled
}
```

### 3.3 断路器机制

```typescript
type AutoCompactTrackingState = {
  compacted: boolean
  turnCounter: number
  turnId: string  // 每轮唯一 ID
  consecutiveFailures?: number  // 连续失败计数
}

// 在 query.ts 中追踪
if (tracking?.consecutiveFailures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES) {
  return { wasCompacted: false }  // 停止尝试
}

// 成功后重置
if (compactionResult) {
  tracking.consecutiveFailures = 0
}
```

**设计原因：** 数据显示 1,279 个会话在单个会话中有 50+ 次连续失败（最高 3,272 次），每天浪费约 250K API 调用。

---

## 4. Session Memory Compact（轻量级压缩）

### 4.1 什么是 Session Memory

Session Memory 是 Claude Code 的**长期记忆系统**，在对话过程中异步提取关键信息并保存到独立文件。自动压缩优先使用这些已提取的记忆，避免重复调用 API 生成摘要。

### 4.2 触发条件

```typescript
export function shouldUseSessionMemoryCompaction(): boolean {
  // 环境变量覆盖
  if (isEnvTruthy(process.env.ENABLE_CLAUDE_CODE_SM_COMPACT)) {
    return true
  }
  if (isEnvTruthy(process.env.DISABLE_CLAUDE_CODE_SM_COMPACT)) {
    return false
  }
  
  // GrowthBook 特性标志
  const sessionMemoryFlag = getFeatureValue_CACHED_MAY_BE_STALE(
    'tengu_session_memory',
    false,
  )
  const smCompactFlag = getFeatureValue_CACHED_MAY_BE_STALE(
    'tengu_sm_compact',
    false,
  )
  
  return sessionMemoryFlag && smCompactFlag
}
```

### 4.3 Session Memory Compact 配置

```typescript
type SessionMemoryCompactConfig = {
  minTokens: number           // 压缩后最少保留 token 数 (默认 10,000)
  minTextBlockMessages: number // 最少保留文本块消息数 (默认 5)
  maxTokens: number           // 压缩后最大 token 数 (默认 40,000)
}
```

**配置来源：** GrowthBook 远程配置 `tengu_sm_compact_config`，支持动态调整。

### 4.4 压缩流程

```typescript
async function trySessionMemoryCompaction(
  messages: Message[],
  agentId?: AgentId,
  autoCompactThreshold?: number,
): Promise<CompactionResult | null>
```

**步骤：**

```
1. 等待 Session Memory 提取完成（带超时）
   ↓
2. 获取 lastSummarizedMessageId（最后一条已摘要消息的 ID）
   ↓
3. 获取 Session Memory 内容
   ↓
4. 计算保留消息的起始索引
   - 从 lastSummarizedMessageId 之后开始
   - 向后扩展以满足 minTokens 和 minTextBlockMessages
   - 向前不超过 maxTokens
   ↓
5. 调整索引以保持 API 不变量
   - 不拆分 tool_use/tool_result 对
   - 不拆分相同 message.id 的 thinking 块
   ↓
6. 执行 Session Start Hooks
   - 恢复 CLAUDE.md 等上下文
   ↓
7. 构建 CompactionResult
   - 创建 compact boundary marker
   - 生成摘要消息（使用 Session Memory 内容）
   - 附加文件附件
```

### 4.5 索引计算算法

```typescript
export function calculateMessagesToKeepIndex(
  messages: Message[],
  lastSummarizedIndex: number,
): number {
  const config = getSessionMemoryCompactConfig()
  
  // 从已摘要消息之后开始
  let startIndex = lastSummarizedIndex >= 0 ? lastSummarizedIndex + 1 : messages.length
  
  // 计算当前 token 数和文本块消息数
  let totalTokens = 0
  let textBlockMessageCount = 0
  for (let i = startIndex; i < messages.length; i++) {
    totalTokens += estimateMessageTokens(messages[i])
    if (hasTextBlocks(messages[i])) textBlockMessageCount++
  }
  
  // 如果已达上限，直接返回
  if (totalTokens >= config.maxTokens) {
    return adjustIndexToPreserveAPIInvariants(messages, startIndex)
  }
  
  // 如果已满足最小值，直接返回
  if (totalTokens >= config.minTokens && 
      textBlockMessageCount >= config.minTextBlockMessages) {
    return adjustIndexToPreserveAPIInvariants(messages, startIndex)
  }
  
  // 向后扩展直到满足最小值或达到上限
  const floor = messages.findLastIndex(m => isCompactBoundaryMessage(m))
  for (let i = startIndex - 1; i >= floor; i--) {
    totalTokens += estimateMessageTokens(messages[i])
    if (hasTextBlocks(messages[i])) textBlockMessageCount++
    startIndex = i
    
    if (totalTokens >= config.maxTokens) break
    if (totalTokens >= config.minTokens && 
        textBlockMessageCount >= config.minTextBlockMessages) break
  }
  
  return adjustIndexToPreserveAPIInvariants(messages, startIndex)
}
```

### 4.6 API 不变量保护

**问题场景：** 流式响应可能将同一消息分成多个内容块（thinking、tool_use 等），具有相同的 `message.id` 但不同的 `uuid`。

**解决方案：**

```typescript
export function adjustIndexToPreserveAPIInvariants(
  messages: Message[],
  startIndex: number,
): number {
  let adjustedIndex = startIndex
  
  // Step 1: 保护 tool_use/tool_result 对
  // 收集保留范围内所有 tool_result 的 ID
  const allToolResultIds = collectToolResultIds(messages.slice(startIndex))
  
  // 查找需要补充的 tool_use 消息
  for (let i = adjustedIndex - 1; i >= 0; i--) {
    if (hasToolUseWithIds(messages[i], neededToolUseIds)) {
      adjustedIndex = i
    }
  }
  
  // Step 2: 保护 thinking 块
  // 收集保留范围内所有 assistant 消息的 message.id
  const messageIdsInKeptRange = collectMessageIds(messages.slice(adjustedIndex))
  
  // 向后查找相同 message.id 的消息（可能包含 thinking 块）
  for (let i = adjustedIndex - 1; i >= 0; i--) {
    if (messages[i].type === 'assistant' && 
        messages[i].message.id &&
        messageIdsInKeptRange.has(messages[i].message.id)) {
      adjustedIndex = i
    }
  }
  
  return adjustedIndex
}
```

### 4.7 关键区别：最近的消息是否发送给大模型？

**问题场景：** 假设当前已对话 10 轮，需要压缩。是把 10 轮都发给大模型，还是只发前 8 轮，后 2 轮直接保留？

**答案：取决于压缩模式。**

#### Session Memory Compact：只发前 8 轮，后 2 轮直接保留（且不调用大模型）

Session Memory Compact **不会调用大模型**，而是：

1. 使用 `lastSummarizedMessageId` 确定边界（例如第 8 轮结束）
2. **前 8 轮**：使用已有的 session memory 内容作为摘要（不调用大模型）
3. **后 2 轮**：直接保留原样（`messagesToKeep = messages.slice(startIndex)`）

```typescript
// src/services/compact/sessionMemoryCompact.ts:558
const lastSummarizedIndex = messages.findIndex(
  msg => msg.uuid === lastSummarizedMessageId,
)

// src/services/compact/sessionMemoryCompact.ts:578
const startIndex = calculateMessagesToKeepIndex(messages, lastSummarizedIndex)

// src/services/compact/sessionMemoryCompact.ts:585
const messagesToKeep = messages
  .slice(startIndex)
  .filter(m => !isCompactBoundaryMessage(m))
```

**消息流向：**

```
完整 10 轮对话：
├── [第 1-8 轮] ← lastSummarizedMessageId 之前
└── [第 9-10 轮] ← lastSummarizedMessageId 之后（保留）

Session Memory Compact 处理：
├── [第 1-8 轮] → 用 session memory 替换（不调用大模型）
└── [第 9-10 轮] → 直接保留

压缩后上下文：
├── compact_boundary 系统消息
├── summaryMessages（session memory 内容）
└── messagesToKeep（第 9-10 轮原样保留）
```

**关键点：**
- ❌ **不调用大模型**
- ✅ **后 2 轮直接保留**，不经过任何处理
- ✅ **前 8 轮用 session memory 替换**，不是大模型生成的

#### Full Compact：10 轮全部发送给大模型

Full Compact **会调用大模型**，并且：

1. **所有 10 轮**都传递给 `runForkedAgent`
2. 大模型看到完整历史，生成覆盖所有 10 轮的摘要
3. 摘要替换所有历史，不保留任何原始消息

```typescript
// src/services/compact/compact.ts:448
let messagesToSummarize = messages  // 所有消息

// src/utils/forkedAgent.ts:524
const initialMessages: Message[] = [...forkContextMessages, ...promptMessages]
// forkContextMessages = 完整 10 轮对话
```

**消息流向：**

```
完整 10 轮对话：
├── [第 1-8 轮]
└── [第 9-10 轮]

Full Compact 处理：
├── [全部 10 轮] → 发送给大模型
└── 大模型生成摘要 → 替换所有历史

压缩后上下文：
├── compact_boundary 系统消息
├── summaryMessages（大模型生成的摘要，覆盖 10 轮）
└── postCompactFileAttachments（重新读取的最近文件）
```

**关键点：**
- ✅ **调用大模型**
- ✅ **10 轮全部发送**给大模型
- ❌ **不保留任何原始消息**，全部用摘要替换
- ✅ **后压缩文件恢复**：重新读取最近文件（最多 5 个）作为附件

#### 对比总结

| 问题 | Session Memory Compact | Full Compact |
|------|----------------------|--------------|
| 是否调用大模型 | ❌ 不会 | ✅ 会 |
| 10 轮全部发送？ | ❌ 只发送 session memory（前 8 轮的摘要） | ✅ 全部 10 轮 |
| 后 2 轮保留？ | ✅ 直接保留原样 | ❌ 用摘要替换 |
| 前 8 轮处理 | 用 session memory 替换 | 大模型生成摘要覆盖 |
| 隐私性 | 更高（最近消息不发送给大模型） | 较低（所有消息都发送） |
| API 成本 | 零 | 有（尽管有缓存命中） |

---

### 4.8 API 不变量保护

---

## 5. Full Compact（完整压缩）

### 5.1 何时使用 Full Compact

当 Session Memory Compact 不可用时（Session Memory 未启用、为空、或无法确定边界），系统回退到 Full Compact：

```typescript
// 在 autoCompactIfNeeded 中
let compactionResult = await trySessionMemoryCompaction(...)

if (!compactionResult) {
  // Session Memory 不可用，使用完整压缩
  compactionResult = await compactConversation(messages, context, ...)
}
```

### 5.2 是否调用大模型？

**是的，Full Compact 会调用大模型 API 生成摘要。**

**调用方式：** 通过 `runForkedAgent` 启动一个**独立的 forked agent**，使用与主对话相同的 prompt cache 前缀（系统提示词、工具定义、上下文消息），实现 cache hit 降低成本。

```typescript
// src/services/compact/compact.ts:1157
const result = await runForkedAgent({
  promptMessages: [summaryRequest],      // 压缩提示词
  cacheSafeParams,                       // 缓存安全参数（复用主对话缓存）
  canUseTool: createCompactCanUseTool(), // 禁用所有工具
  querySource: 'compact',
  forkLabel: 'compact',
  maxTurns: 1,                           // 仅允许 1 轮响应
  skipCacheWrite: true,                  // 不写入缓存
  overrides: { abortController: context.abortController },
})
```

**关键设计：**
- `maxTurns: 1`：只允许一次响应，防止工具调用循环
- `canUseTool`：返回 `false`，**禁用所有工具**，只允许纯文本输出
- `cacheSafeParams`：复用主对话的 prompt cache，实现 cache hit
- `skipCacheWrite: true`：压缩结果不写入缓存，避免污染

### 5.3 实际使用的提示词

**提示词生成函数：** `getCompactPrompt(customInstructions?: string)`

**完整提示词结构：**

```
┌─────────────────────────────────────────────────────────────┐
│ NO_TOOLS_PREAMBLE（强制禁用工具）                           │
├─────────────────────────────────────────────────────────────┤
│ BASE_COMPACT_PROMPT（核心任务描述 + 输出格式要求）          │
├─────────────────────────────────────────────────────────────┤
│ Additional Instructions（可选，用户自定义指令）             │
├─────────────────────────────────────────────────────────────┤
│ NO_TOOLS_TRAILER（再次强调禁用工具）                        │
└─────────────────────────────────────────────────────────────┘
```

#### 5.3.1 NO_TOOLS_PREAMBLE

```text
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
```

**设计原因：** 在 Sonnet 4.6+ adaptive-thinking 模型上，即使有尾部指令，模型有时仍会尝试工具调用。由于 `maxTurns: 1`，被拒绝的工具调用意味着没有文本输出，导致回退到流式 fallback（2.79% 失败率 vs 4.5 的 0.01%）。因此将禁用工具的警告放在**最前面**。

#### 5.3.2 BASE_COMPACT_PROMPT（核心部分）

```text
Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Pay special attention to the most recent messages and include full code snippets where applicable and include a summary of why this file read or edit is important.
4. Errors and fixes: List all errors that you ran into, and how you fixed them. Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
5. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.
6. All user messages: List ALL user messages that are not tool results. These are critical for understanding the users' feedback and changing intent.
7. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.
8. Current Work: Describe in detail precisely what was being worked on immediately before this summary request, paying special attention to the most recent messages from both user and assistant. Include file names and code snippets where applicable.
9. Optional Next Step: List the next step that you will take that is related to the most recent work you were doing. IMPORTANT: ensure that this step is DIRECTLY in line with the user's most recent explicit requests, and the task you were working on immediately before this summary request. If your last task was concluded, then only list next steps if they are explicitly in line with the users request. Do not start on tangential requests or really old requests that were already completed without confirming with the user first.
                       If there is a next step, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.

Here's an example of how your output should be structured:

<example>
<analysis>
[Your thought process, ensuring all points are covered thoroughly and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Technical Concepts:
   - [Concept 1]
   - [Concept 2]

3. Files and Code Sections:
   - [File Name 1]
      - [Summary of why this file is important]
      - [Important Code Snippet]

4. Errors and fixes:
    - [Error description]:
      - [How you fixed it]

5. Problem Solving:
   [Description]

6. All user messages:
    - [Detailed non tool use user message]

7. Pending Tasks:
   - [Task 1]

8. Current Work:
   [Detailed description]

9. Optional Next Step:
   [Next step with verbatim quotes]

</summary>
</example>

Please provide your summary based on the RECENT messages only (after the retained earlier context), following this structure and ensuring precision and thoroughness in your response.
```

#### 5.3.3 NO_TOOLS_TRAILER

```text

REMINDER: Do NOT call any tools. Respond with plain text only — an <analysis> block followed by a <summary> block. Tool calls will be rejected and you will fail the task.
```

#### 5.3.4 用户自定义指令（可选）

如果用户在设置中配置了自定义压缩指令，会插入到核心提示词和尾部之间：

```text

Additional Instructions:
{customInstructions}
```

### 5.4 提示词变体：Partial Compact

除了完整的 `BASE_COMPACT_PROMPT`，还有一个**部分压缩变体** `PARTIAL_COMPACT_PROMPT`，用于只压缩最近消息的场景：

**关键区别：**
- `BASE_COMPACT_PROMPT`：针对 "RECENT messages only (after the retained earlier context)"
- `PARTIAL_COMPACT_PROMPT`：针对完整对话历史，摘要将放在继续会话的开头

部分压缩的摘要结构略有不同，包含 `Context for Continuing Work` 章节而非 `Current Work` 和 `Optional Next Step`。

### 5.5 响应后处理

模型返回的原始响应包含 `<analysis>` 和 `<summary>` XML 标签，通过 `formatCompactSummary` 函数处理：

```typescript
export function formatCompactSummary(summary: string): string {
  let formattedSummary = summary

  // 1. 移除分析草稿（仅用于提高摘要质量，无信息价值）
  formattedSummary = formattedSummary.replace(
    /<analysis>[\s\S]*?<\/analysis>/,
    '',
  )

  // 2. 提取 summary 内容，替换为可读标题
  const summaryMatch = formattedSummary.match(/<summary>([\s\S]*?)<\/summary>/)
  if (summaryMatch) {
    const content = summaryMatch[1] || ''
    formattedSummary = formattedSummary.replace(
      /<summary>[\s\S]*?<\/summary>/,
      `Summary:\n${content.trim()}`,
    )
  }

  // 3. 清理多余空白
  formattedSummary = formattedSummary.replace(/\n\n+/g, '\n\n')

  return formattedSummary.trim()
}
```

**最终输出示例：**

```markdown
Summary:

1. Primary Request and Intent:
   用户希望构建一个自动压缩机制的深度分析报告...

2. Key Technical Concepts:
   - Session Memory Compact
   - Full Compact
   - Forked Agent
   - Prompt Cache Sharing

3. Files and Code Sections:
   - src/services/compact/autoCompact.ts
      - 自动压缩触发逻辑
   - src/services/compact/compact.ts
      - 完整压缩流程实现

4. Errors and fixes:
   - 无错误

5. Problem Solving:
   分析了自动压缩的双层策略、阈值管理、断路器机制等...

6. All user messages:
   - "G:\code\claude-code\analysis-reports\11-message-streaming.md 中介绍了自动压缩机制，但是不够详细。请详细深入进行解释"

7. Pending Tasks:
   - 无

8. Current Work:
   正在编写深度分析报告...

9. Optional Next Step:
   完成报告并保存...
```

### 5.6 完整压缩流程（更新版）

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 执行 Pre-Compact Hooks                                   │
│    - 运行用户定义的 pre_compact hooks                       │
│    - 合并自定义指令                                         │
│    - 显示进度提示                                           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. 构建压缩提示词                                           │
│    - getCompactPrompt(customInstructions)                   │
│    - NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT + TRAILER      │
│    - 创建 summary request 用户消息                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. 调用 Forked Agent 生成摘要（关键步骤）                   │
│    - runForkedAgent({...cacheSafeParams})                   │
│    - 复用主对话 prompt cache（cache hit）                   │
│    - maxTurns: 1, canUseTool: false                         │
│    - 流式接收响应                                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. 处理 Prompt-Too-Long 错误（最多 3 次重试）               │
│    - 如果摘要请求本身超出上下文限制                         │
│    - truncateHeadForPTLRetry 截断最旧 API round groups      │
│    - 重试直到成功或达到最大重试次数                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. 后处理摘要响应                                           │
│    - formatCompactSummary 移除<analysis>标签               │
│    - 提取<summary>内容并格式化                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. 创建 Compact Boundary Message                            │
│    - 标记压缩边界（system: compact_boundary）               │
│    - 记录压缩前 token 数                                    │
│    - 记录预发现的工具列表                                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. 生成后压缩文件附件                                       │
│    - 从 readFileState 获取最近访问的文件                   │
│    - 使用 FileReadTool 重新读取文件内容                    │
│    - 跳过已在 preservedMessages 中的 Read 结果             │
│    - 受文件数量和 token 预算限制                           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. 执行 Post-Compact Hooks                                  │
│    - 运行用户定义的 post_compact hooks                      │
│    - 生成 hook 结果消息                                     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 9. 执行 Session Start Hooks                                 │
│    - 恢复 CLAUDE.md 等上下文                                │
│    - 重新加载 MCP 服务器配置                                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 10. 构建 CompactionResult                                   │
│    - 创建摘要消息（包含格式化后的摘要）                     │
│    - 附加文件附件、hook 结果、计划附件                     │
│    - 计算压缩后 token 数                                    │
│    - 记录分析事件                                           │
└─────────────────────────────────────────────────────────────┘
```

---

### 5.7 缓存命中机制详解

#### 5.7.1 核心设计原则

**Full Compact 为了缓存命中，保持了所有缓存关键参数不变，只是在消息列表末尾追加了一个压缩请求消息。**

实际发送给 API 的消息结构：

```typescript
// src/utils/forkedAgent.ts:534
const initialMessages: Message[] = [...forkContextMessages, ...promptMessages]
```

**消息序列分解：**

```
┌─────────────────────────────────────────────────────────────┐
│ forkContextMessages（来自主对话，已缓存）                   │
│ ├── Message 1: user "帮我写个 Python 脚本..."                │
│ ├── Message 2: assistant "好的，我来帮你..."                │
│ ├── Message 3: user "运行一下看看..."                       │
│ ├── Message 4: assistant [tool_use] + [tool_result]         │
│ └── ...（完整的历史对话）                                   │
├─────────────────────────────────────────────────────────────┤
│ promptMessages（新增的压缩请求）                            │
│ └── Message N+1: user [BASE_COMPACT_PROMPT]                 │
│         "Your task is to create a detailed summary..."      │
└─────────────────────────────────────────────────────────────┘
```

#### 5.7.2 Anthropic Prompt Cache 缓存键组成

根据 `forkedAgent.ts` 的注释：

> The Anthropic API cache key is composed of: **system prompt**, **tools**, **model**, **messages (prefix)**, and **thinking config**.

**CacheSafeParams 保证缓存命中：**

```typescript
type CacheSafeParams = {
  systemPrompt: SystemPrompt           // ✓ 系统提示词 - 保持不变
  userContext: { [k: string]: string } // ✓ 用户上下文 - 保持不变
  systemContext: { [k: string]: string } // ✓ 系统上下文 - 保持不变
  toolUseContext: ToolUseContext       // ✓ 工具定义 + 模型 + thinking 配置
  forkContextMessages: Message[]       // ✓ 消息前缀 - 完整历史
}
```

#### 5.7.3 缓存命中原理

```
主对话请求时的消息序列：
┌──────────────────────────────────────┐
│ M1, M2, M3, M4, ... M(n-1)          │ → 已缓存
└──────────────────────────────────────┘

压缩时的消息序列：
┌──────────────────────────────────────┬─────────────────┐
│ M1, M2, M3, M4, ... M(n-1)          │ │ M(n): 压缩请求 │
│ ↑                                    │ │               │
│ └────── 完全相同，命中缓存 ──────────┘ └── 新增部分 ───┘
```

**Anthropic 的缓存机制：**
- 缓存键基于**消息前缀**
- 当前缀匹配时，前缀部分的 `cache_read_input_tokens` 命中
- 只有新增的消息部分需要重新计算

#### 5.7.4 成本对比

根据代码中的实验数据：

```typescript
// Experiment (Jan 2026) confirmed:
// false path is 98% cache miss, costs ~0.76% of fleet cache_creation
// (~38B tok/day)
```

| 模式 | 缓存命中率 | 主要支付项 | 成本 |
|------|-----------|-----------|------|
| **启用缓存共享** | ~98% | `cache_read_input_tokens` | 低 |
| **不启用缓存共享** | ~2% | `cache_creation_input_tokens` + `input_tokens` | 高 |

**数据影响：** 不启用缓存共享会消耗约 0.76% 的全队缓存创建量（约 38B tokens/天），主要集中在 ephemeral 环境（CCR/GHA/SDK）中使用冷 GB 缓存和禁用 GB 的第三方提供商。

#### 5.7.5 关键设计细节

```typescript
// src/services/compact/compact.ts:1157
const result = await runForkedAgent({
  promptMessages: [summaryRequest],  // 只传压缩请求
  cacheSafeParams,                   // 继承主对话的完整上下文
  canUseTool: createCompactCanUseTool(), // 禁用工具
  maxTurns: 1,                       // 只允许一轮
  skipCacheWrite: true,              // 不写入新缓存（避免污染）
})
```

**为什么 `skipCacheWrite: true`？**
- 压缩是"一次性"操作，生成的摘要会插入到主对话中
- 如果写入缓存，会污染主对话的缓存前缀
- 未来的主对话请求不需要以压缩请求为前缀

**为什么不能设置 `maxOutputTokens`？**

```typescript
// src/services/compact/compact.ts:1150
// DO NOT set maxOutputTokens here. The fork piggybacks on the main thread's
// prompt cache by sending identical cache-key params (system, tools, model,
// messages prefix, thinking config). Setting maxOutputTokens would clamp
// budget_tokens via Math.min(budget, maxOutputTokens-1) in claude.ts,
// creating a thinking config mismatch that invalidates the cache.
```

设置 `maxOutputTokens` 会通过 `claude.ts` 中的 `Math.min(budget, maxOutputTokens-1)` 影响 `budget_tokens`，导致 thinking 配置不匹配从而使缓存失效。

#### 5.7.6 缓存参数传递流程

```
┌─────────────────────────────────────────────────────────────┐
│ 主对话 Query Loop                                           │
│ - 构建 CacheSafeParams                                      │
│ - systemPrompt, userContext, systemContext                  │
│ - toolUseContext (tools, model, thinking config)            │
│ - forkContextMessages (完整历史)                            │
└─────────────────────────────────────────────────────────────┘
                            ↓ saveCacheSafeParams()
┌─────────────────────────────────────────────────────────────┐
│ CompactConversation                                         │
│ - 接收 cacheSafeParams 参数                                 │
│ - 传递给 streamCompactSummary()                             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ runForkedAgent                                              │
│ - 使用 cacheSafeParams 构建 initialMessages                 │
│ - initialMessages = [...forkContextMessages, ...prompt]     │
│ - 调用 query() 执行                                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Anthropic API                                               │
│ - 消息前缀匹配 → cache hit                                  │
│ - 仅压缩请求部分需要新计算                                  │
└─────────────────────────────────────────────────────────────┘
```

#### 5.7.7 总结：缓存命中设计要点

| 组件 | 是否改变 | 说明 |
|------|---------|------|
| 系统提示词 | ❌ 不变 | 直接继承 |
| 工具定义 | ❌ 不变 | 从 toolUseContext 继承 |
| 模型 | ❌ 不变 | 从 toolUseContext 继承 |
| 消息前缀 | ❌ 不变 | forkContextMessages 是完整历史 |
| Thinking 配置 | ❌ 不变 | 从 toolUseContext 继承 |
| 最新消息 | ✅ 新增 | 压缩请求提示词 |

**本质：** Full Compact 是在主对话的**完整历史副本**上，追加一条"请总结上述对话"的指令，然后调用模型。由于前缀完全相同，所以能实现 ~98% 的缓存命中率。

---

## 6. 压缩结果与后续处理

### 6.1 CompactionResult 结构

```typescript
type CompactionResult = {
  boundaryMarker: SystemCompactBoundaryMessage  // 压缩边界标记
  summaryMessages: UserMessage[]                // 摘要消息
  attachments: AttachmentMessage[]              // 附件（文件、hook 结果等）
  hookResults: HookResultMessage[]              // Hook 执行结果
  messagesToKeep: Message[]                     // 保留的原始消息（SM Compact）
  preCompactTokenCount: number                  // 压缩前 token 数
  postCompactTokenCount: number                 // 压缩 API 调用的总用量
  truePostCompactTokenCount: number             // 压缩后实际上下文大小
}
```

### 6.2 压缩后消息构建

```typescript
export function buildPostCompactMessages(
  result: CompactionResult,
): Message[] {
  return [
    result.boundaryMarker,      // compact_boundary 系统消息
    ...result.summaryMessages,  // 摘要内容
    ...result.attachments,      // 文件附件、hook 结果
    ...result.messagesToKeep,   // 保留的原始消息（仅 SM Compact）
  ]
}
```

### 6.3 重触发检测

```typescript
// 在 query.ts 中
const willRetriggerNextTurn =
  recompactionInfo !== undefined &&
  truePostCompactTokenCount >= recompactionInfo.autoCompactThreshold

logEvent('tengu_compact', {
  willRetriggerNextTurn,
  truePostCompactTokenCount,
  autoCompactThreshold,
  // ...
})

// 如果 willRetriggerNextTurn 为 true，下一轮查询会立即再次触发压缩
```

---

## 7. 分析事件追踪

### 7.1 关键事件

| 事件名 | 触发时机 | 关键字段 |
|--------|---------|---------|
| `tengu_compact` | 压缩成功 | pre/post token 数、是否自动、querySource |
| `tengu_compact_failed` | 压缩失败 | 失败原因、重试次数 |
| `tengu_sm_compact_flag_check` | SM Compact 标志检查 | 特性标志状态 |
| `tengu_sm_compact_no_session_memory` | 无 Session Memory | - |
| `tengu_sm_compact_empty_template` | Session Memory 为空 | - |
| `tengu_sm_compact_threshold_exceeded` | SM Compact 后仍超阈值 | postCompactTokenCount |

### 7.2 tengu_compact 事件字段

```typescript
logEvent('tengu_compact', {
  preCompactTokenCount,           // 压缩前 token 数
  postCompactTokenCount,          // 压缩 API 调用总用量
  truePostCompactTokenCount,      // 压缩后实际上下文大小
  autoCompactThreshold,           // 自动压缩触发阈值
  willRetriggerNextTurn,          // 是否会立即重触发
  isAutoCompact,                  // 是否自动压缩
  querySource,                    // 查询来源
  queryChainId,                   // 查询链 ID
  queryDepth,                     // 查询深度
  isRecompactionInChain,          // 是否是链中重压缩
  turnsSincePreviousCompact,      // 距上次压缩的轮数
  previousCompactTurnId,          // 上次压缩的 turn ID
  compactionUsage,                // 压缩 API 用量详情
  // ...
})
```

---

## 8. 环境变量与配置

### 8.1 环境变量

| 变量名 | 作用 | 默认值 |
|--------|------|--------|
| `DISABLE_COMPACT` | 禁用所有压缩 | false |
| `DISABLE_AUTO_COMPACT` | 仅禁用自动压缩 | false |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | 覆盖上下文窗口大小 | 模型默认值 |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | 覆盖触发阈值百分比 | 计算值 |
| `CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE` | 覆盖阻塞限制 | 计算值 |
| `ENABLE_CLAUDE_CODE_SM_COMPACT` | 强制启用 SM Compact | false |
| `DISABLE_CLAUDE_CODE_SM_COMPACT` | 强制禁用 SM Compact | false |

### 8.2 用户配置

```typescript
// 在 Settings/Config.tsx 中
{
  id: 'autoCompactEnabled',
  value: globalConfig.autoCompactEnabled,
  onChange: (enabled: boolean) => {
    updateGlobalConfig({ autoCompactEnabled: enabled })
  }
}
```

---

## 9. 设计亮点与权衡

### 9.1 双层压缩策略

**优势：**
- Session Memory Compact 零 API 成本，速度快
- Full Compact 作为 fallback，保证可靠性
- 渐进式 token 释放，避免过度压缩

**权衡：**
- Session Memory 需要异步提取，存在时间窗口
- 需要维护两套逻辑，代码复杂度增加

### 9.2 断路器机制

**问题：** 某些场景下压缩会连续失败（如 irrecoverably over the limit）

**解决：** 连续 3 次失败后停止尝试，避免浪费 API 调用

**数据支持：** 1,279 个会话有 50+ 次连续失败，每天浪费 ~250K API 调用

### 9.3 API 不变量保护

**问题：** 流式响应可能拆分消息，导致 tool_use/tool_result 不匹配或 thinking 块丢失

**解决：** `adjustIndexToPreserveAPIInvariants` 向后扩展索引，确保完整性

### 9.4 Prompt-Too-Long 重试

**问题：** 压缩请求本身可能触发 prompt-too-long 错误

**解决：** 
1. 截断最旧的 API round groups
2. 最多重试 3 次
3. 每次重试丢弃更多历史

### 9.5 后压缩文件恢复

**问题：** 压缩后模型失去最近访问文件的上下文

**解决：** 
1. 跟踪 readFileState
2. 重新读取最近文件（最多 5 个）
3. 跳过 preservedMessages 中已有的内容
4. 受 token 预算限制

### 9.6 压缩后内容保护机制（核心）

**用户关心的问题：** 压缩后，之前读取的文件内容会不会丢失？如果丢失了，后面再问这个文件的内容，模型还能回答吗？

**答案：** Claude Code 通过多层机制确保核心内容不丢失。

#### 9.6.1 保护机制总览

| 机制 | 保护内容 | 保护方式 | 局限性 |
|------|---------|---------|--------|
| **压缩提示词要求** | 文件名、关键代码片段 | 要求模型在摘要中记录 | 有损压缩，不完整 |
| **后压缩文件恢复** | 最近访问的文件内容 | 重新读取文件（最多 5 个，50K tokens） | 受数量和 token 限制 |
| **保留最近消息** | 最近的对话内容 | Session Memory Compact 保留 10K-40K tokens | 仅 SM Compact 有效 |
| **API 不变量保护** | tool_use/tool_result 对 | 不拆分相关消息对 | - |
| **技能附件恢复** | 已激活的技能内容 | 重新附加技能文件（25K tokens） | 仅适用于 skills |

#### 9.6.2 后压缩文件恢复（核心机制）

**这是最关键的保护机制。**

```typescript
// src/services/compact/compact.ts:122-124
export const POST_COMPACT_MAX_FILES_TO_RESTORE = 5      // 最多恢复 5 个文件
export const POST_COMPACT_TOKEN_BUDGET = 50_000         // 总 token 预算 50K
export const POST_COMPACT_MAX_TOKENS_PER_FILE = 5_000   // 每文件最多 5K tokens
```

**工作流程：**

```
┌─────────────────────────────────────────────────────────────┐
│ 压缩前                                                       │
│ - readFileState 追踪最近访问的文件                          │
│   { "src/main.py": { content: "...", timestamp: 123456 } }  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 压缩执行                                                     │
│ - 生成摘要（包含文件名的文字描述）                          │
│ - 丢弃原始 tool_result 中的文件内容                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 后压缩文件恢复（关键步骤）                                   │
│ - 从 readFileState 获取最近 5 个文件                        │
│ - 使用 FileReadTool 重新读取实际内容                        │
│ - 创建 attachment 消息附加到压缩后上下文                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 压缩后上下文                                                 │
│ - compact_boundary 系统消息                                 │
│ - 摘要内容（包含文件名的文字描述）                          │
│ - [附件] src/main.py (重新读取的完整内容，最多 5K tokens)   │
│ - [附件] src/utils/helper.py (重新读取的完整内容)           │
│ - ...最多 5 个文件                                          │
└─────────────────────────────────────────────────────────────┘
```

**关键点：**
- 文件内容是**重新读取**的，不是从摘要中"恢复"的
- 保证了内容的**完整性和准确性**
- 受 token 预算限制（50K 总预算，每文件最多 5K）

#### 9.6.3 压缩提示词要求

**BASE_COMPACT_PROMPT 明确要求：**

```text
3. Files and Code Sections: Enumerate specific files and code sections examined, 
   modified, or created. Pay special attention to the most recent messages and 
   include full code snippets where applicable and include a summary of why this 
   file read or edit is important.
```

**示例输出格式：**

```text
3. Files and Code Sections:
   - src/main.py
      - [Summary of why this file is important]
      - [Summary of the changes made to this file, if any]
      - [Important Code Snippet]
```

**局限性：** 摘要中的代码片段是**有损压缩**，不可能保留完整文件内容。

#### 9.6.4 Session Memory Compact 保留最近消息

Session Memory Compact 不会压缩所有消息，而是**保留最近的消息原样**：

```typescript
// src/services/compact/sessionMemoryCompact.ts
export const DEFAULT_SM_COMPACT_CONFIG: SessionMemoryCompactConfig = {
  minTokens: 10_000,      // 压缩后最少保留 10K tokens 的最近消息
  minTextBlockMessages: 5, // 最少保留 5 条带文本块的消息
  maxTokens: 40_000,      // 压缩后最多保留 40K tokens
}
```

**这意味着：**
- 最近的对话（包括最近的文件读取）**不会被压缩**
- 只有较早的历史会被摘要替换
- 保证了短期上下文的完整性

#### 9.6.5 实际效果示例

**压缩前的上下文：**

```
User: 帮我读取 src/main.py
Assistant: [tool_use: Read src/main.py]
User: [tool_result: <file_content>...]
User: 现在帮我修改这个文件...
Assistant: [tool_use: Edit src/main.py]
...（多轮对话后，token 接近限制）
```

**压缩后的上下文：**

```
System: [compact_boundary]
User: Summary:
      1. Primary Request and Intent: 用户希望修改 src/main.py...
      2. Key Technical Concepts: Python, FastAPI...
      3. Files and Code Sections:
         - src/main.py: 实现了主要的 API 端点...
         [注意：这里只有文字描述，没有完整内容]
      ...
      
Attachment: [Read: src/main.py]  ← 重新读取的完整内容
            <actual file content here>

Attachment: [Read: src/utils/helper.py]  ← 另一个最近文件
            <actual file content here>

User: 继续对话的最近消息...
Assistant: ...
```

#### 9.6.6 局限性

| 限制 | 说明 | 影响 |
|------|------|------|
| **文件数量限制** | 最多恢复 5 个文件 | 如果读了 10 个文件，只有最近 5 个会被恢复 |
| **Token 预算限制** | 总共 50K tokens，每文件 5K | 大文件可能被截断或无法全部恢复 |
| **时间窗口** | 按 timestamp 排序 | 早期读取但重要的文件可能被丢弃 |
| **摘要有损** | 提示词要求记录代码片段 | 但摘要是文字描述，不是完整代码 |

---

## 10. 常见问题与调试

### 10.1 自动压缩不触发

**检查清单：**
1. `userConfig.autoCompactEnabled` 是否为 true
2. `DISABLE_AUTO_COMPACT` 环境变量是否设置
3. Token 数是否达到阈值（有效窗口 - 13,000）
4. querySource 是否为 'session_memory' 或 'compact'（递归保护）
5. 是否启用了 Context Collapse 或 Reactive Compact

### 10.2 压缩连续失败

**可能原因：**
1. 上下文确实无法压缩（单条消息过大）
2. Session Memory 提取失败
3. Forked Agent 调用失败

**调试方法：**
1. 查看 `tengu_compact_failed` 事件日志
2. 检查 `consecutiveFailures` 计数
3. 尝试手动 `/compact` 命令

### 10.3 压缩后立即重触发

**原因：** 压缩后 token 数仍超过阈值

**解决：**
1. 调整 `AUTOCOMPACT_BUFFER_TOKENS`（增加缓冲区）
2. 调整 Session Memory Compact 的 `maxTokens`
3. 检查是否有大型文件附件

### 10.4 最近的消息是否发送给大模型？

**问题：** 假设当前已对话 10 轮，需要压缩。是把 10 轮都发给大模型，还是只发前 8 轮，后 2 轮直接保留？

**答案：取决于压缩模式。**

| 问题 | Session Memory Compact | Full Compact |
|------|----------------------|--------------|
| 是否调用大模型 | ❌ 不会 | ✅ 会 |
| 10 轮全部发送？ | ❌ 只发送 session memory（前 8 轮的摘要） | ✅ 全部 10 轮 |
| 后 2 轮保留？ | ✅ 直接保留原样 | ❌ 用摘要替换 |
| 前 8 轮处理 | 用 session memory 替换 | 大模型生成摘要覆盖 |
| 隐私性 | 更高（最近消息不发送给大模型） | 较低（所有消息都发送） |
| API 成本 | 零 | 有（尽管有缓存命中） |

**Session Memory Compact 消息流向：**

```
完整 10 轮对话：
├── [第 1-8 轮] ← lastSummarizedMessageId 之前
└── [第 9-10 轮] ← lastSummarizedMessageId 之后（保留）

Session Memory Compact 处理：
├── [第 1-8 轮] → 用 session memory 替换（不调用大模型）
└── [第 9-10 轮] → 直接保留

压缩后上下文：
├── compact_boundary 系统消息
├── summaryMessages（session memory 内容）
└── messagesToKeep（第 9-10 轮原样保留）
```

**Full Compact 消息流向：**

```
完整 10 轮对话：
├── [第 1-8 轮]
└── [第 9-10 轮]

Full Compact 处理：
├── [全部 10 轮] → 发送给大模型
└── 大模型生成摘要 → 替换所有历史

压缩后上下文：
├── compact_boundary 系统消息
├── summaryMessages（大模型生成的摘要，覆盖 10 轮）
└── postCompactFileAttachments（重新读取的最近文件）
```

**这意味着：**

1. **Session Memory Compact**：
   - ❌ 不调用大模型
   - ✅ 后 2 轮直接保留原样
   - ✅ 前 8 轮用 session memory 替换
   - ✅ 更隐私、零 API 成本

2. **Full Compact**：
   - ✅ 调用大模型
   - ✅ 10 轮全部发送给大模型
   - ❌ 所有消息都用摘要替换
   - ✅ 后压缩文件恢复重新读取最近文件
   - ❌ 隐私性较低、有 API 成本（尽管有缓存命中）

---

## 12. 文件路径索引

| 文件 | 职责 |
|------|------|
| `src/services/compact/autoCompact.ts` | 自动压缩触发逻辑、阈值计算、启用状态 |
| `src/services/compact/compact.ts` | 完整压缩流程、流式摘要生成、后处理 |
| `src/services/compact/sessionMemoryCompact.ts` | Session Memory 压缩逻辑 |
| `src/services/compact/prompt.ts` | 压缩提示词模板 |
| `src/services/compact/microCompact.ts` | Token 估算工具 |
| `src/services/compact/postCompactCleanup.ts` | 压缩后清理 |
| `src/utils/messages.ts` | 消息创建、规范化、边界标记 |
| `src/utils/tokens.ts` | Token 计数和估算 |
| `src/utils/forkedAgent.ts` | Forked Agent 调用 |
| `src/query.ts` | 主查询循环中的压缩集成 |

---

## 13. 总结

Claude Code 的自动压缩机制是一个**多层、渐进、带保护**的上下文管理系统：

1. **双层策略**：优先使用 Session Memory（零成本），回退到 Full Compact（可靠）
2. **精确定量**：基于模型上下文窗口动态计算阈值，支持环境变量覆盖
3. **多重保护**：递归保护、断路器、API 不变量保护
4. **智能恢复**：后压缩文件恢复、Session Start Hooks 恢复上下文
5. **完整追踪**：详细的分析事件，支持调试和优化

核心设计哲学：**在可靠性优先的前提下，尽可能降低成本和延迟**。
