# Claude Code 消息系统与流式处理机制深度分析

## 1. 消息类型定义

### 1.1 核心消息类型

**AssistantMessage** - 助手响应消息
- 包含完整的API响应结构
- 支持虚拟消息 (`isVirtual`) 和API错误消息

**UserMessage** - 用户输入消息
- 支持字符串内容或 `ContentBlockParam[]` 数组
- `isMeta` 标记系统生成的隐藏消息

**SystemMessage** - 系统级消息
- 子类型: `compact_boundary`, `api_error`, `informational`

**ProgressMessage** - 进度追踪消息
- 用于工具执行进度更新

**AttachmentMessage** - 附件消息
- 包含 hook 结果、内存更新等附件

### 1.2 ContentBlockParam 结构

```typescript
type ContentBlockParam =
  | { type: 'text'; text: string }
  | { type: 'image'; source: { type: 'base64'; media_type: string; data: string } }
  | { type: 'tool_use'; id: string; name: string; input: object }
  | { type: 'tool_result'; tool_use_id: string; content: string | ContentBlockParam[] }
  | { type: 'thinking'; thinking: string; signature?: string }
```

## 2. 流式事件处理

### 2.1 流式事件类型

| 事件类型 | 用途 |
|---------|------|
| `message_start` | 初始化部分消息,捕获TTFT |
| `content_block_start` | 创建新的内容块 |
| `content_block_delta` | 增量更新内容 |
| `content_block_stop` | 完成内容块 |
| `message_delta` | 更新usage和stop_reason |
| `message_stop` | 流结束信号 |

### 2.2 Delta 类型处理

```typescript
case 'text_delta':
  contentBlock.text += delta.text

case 'input_json_delta':
  contentBlock.input += delta.partial_json

case 'thinking_delta':
  contentBlock.thinking += delta.thinking
```

### 2.3 流式工具执行

`StreamingToolExecutor` 实现并发工具执行:
- **并发安全工具**: 可并行执行
- **非并发工具**: 需要独占执行
- 结果按接收顺序缓冲和输出

## 3. Token 预算管理

### 3.1 核心计数函数

```typescript
function tokenCountWithEstimation(messages): number {
  // 1. 从后向前查找最后一条带usage的assistant消息
  // 2. 加上后续消息的估算值
  return getTokenCountFromUsage(usage) +
         roughTokenCountEstimationForMessages(messages.slice(i + 1))
}
```

### 3.2 上下文窗口管理

```typescript
// 有效上下文窗口 = 模型窗口 - 输出保留
function getEffectiveContextWindowSize(model): number {
  return contextWindow - reservedTokensForSummary  // 20,000
}

// 自动压缩阈值
function getAutoCompactThreshold(model): number {
  return effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS  // 13,000
}
```

### 3.3 Token警告状态

```typescript
type TokenWarningState = {
  percentLeft: number
  isAboveWarningThreshold: boolean
  isAboveErrorThreshold: boolean
  isAboveAutoCompactThreshold: boolean
  isAtBlockingLimit: boolean
}
```

## 4. 自动压缩机制

### 4.1 压缩触发条件

```typescript
function shouldAutoCompact(messages, model, querySource): boolean {
  if (querySource === 'session_memory' || querySource === 'compact') return false
  if (!isAutoCompactEnabled()) return false

  const tokenCount = tokenCountWithEstimation(messages)
  const threshold = getAutoCompactThreshold(model)

  return tokenCount >= threshold
}
```

### 4.2 压缩流程

```typescript
async function compactConversation(messages, context, ...): CompactionResult {
  // 1. 执行PreCompact hooks
  // 2. 生成摘要
  // 3. 清理缓存
  // 4. 创建后压缩附件
  // 5. 执行SessionStart hooks
  // 6. 返回压缩结果
}
```

### 4.3 断路器机制

```typescript
const MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3

if (tracking?.consecutiveFailures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES) {
  return { wasCompacted: false }
}
```

## 5. 消息规范化流程

### 5.1 normalizeMessages()

将多内容块消息分割为单块消息

### 5.2 normalizeMessagesForAPI()

1. 移除进度/系统消息
2. 重新排序附件
3. 合并相邻用户消息
4. 提升工具结果到内容块开头
5. 过滤尾随thinking

### 5.3 消息ID派生

```typescript
// 确定性UUID派生
function deriveUUID(parentUUID, index): UUID {
  const hex = index.toString(16).padStart(12, '0')
  return `${parentUUID.slice(0, 24)}${hex}`
}
```

## 6. 文件路径索引

| 文件 | 职责 |
|------|------|
| `src/utils/messages.ts` | 消息创建、规范化 |
| `src/services/api/claude.ts` | 流式API处理 |
| `src/services/compact/compact.ts` | 对话压缩逻辑 |
| `src/services/compact/autoCompact.ts` | 自动压缩触发 |
| `src/utils/tokens.ts` | Token计数和估算 |
| `src/services/tools/StreamingToolExecutor.ts` | 流式工具执行 |

## 7. 前端展示控制机制

### 7.1 四层可见性标记

```
┌─────────────────────────────────────────────────────────────────────┐
│                    消息可见性标记对照表                               │
├──────────────────────┬────────────┬─────────────┬───────────────────┤
│        标记          │ 显示在 UI?  │ 发送给 API? │      主要用途     │
├──────────────────────┼────────────┼─────────────┼───────────────────┤
│ isMeta               │ 否         │ 是          │ 系统提示、技能内容 │
│ isVirtual            │ 是         │ 否          │ REPL 内部工具调用  │
│ isVisibleInTranscriptOnly │ 仅 Ctrl+O │ 是      │ 压缩摘要          │
│ isCompactSummary     │ 否(默认)/是 │ 是          │ Memory 压缩摘要   │
└──────────────────────┴────────────┴─────────────┴───────────────────┘
```

### 7.2 isMeta：隐藏消息标记

**核心过滤逻辑**：

```typescript
// src/utils/messages.ts:4658-4677
export function shouldShowUserMessage(
  message: NormalizedMessage,
  isTranscriptMode: boolean,
): boolean {
  if (message.type !== 'user') return true
  if (message.isMeta) {
    // Channel 消息例外：KAIROS 功能下需要显示
    if (message.origin?.kind === 'channel') return true
    return false  // 隐藏！
  }
  if (message.isVisibleInTranscriptOnly && !isTranscriptMode) return false
  return true
}
```

**isMeta 消息来源**：

| 来源 | 文件 | 用途 |
|-----|-----|-----|
| SkillTool | `SkillTool.ts:1104` | 技能内容注入 |
| processSlashCommand | `processSlashCommand.tsx` | Plan 模式指令 |
| getAttachmentMessages | `attachments.ts` | 文件元数据、附件 |
| queued_command | `messages.ts:3754` | 系统生成的命令 |

### 7.3 isVirtual：仅显示标记

用于 REPL 内部工具调用——显示在 UI 但不发送给 API：

```typescript
// src/utils/messages.ts:1997-2001
// 虚拟消息是仅显示用的（如 REPL 内部工具调用）
// 必须永远不发送到 API
const reorderedMessages = reorderAttachmentsForAPI(messages).filter(
  m => !((m.type === 'user' || m.type === 'assistant') && m.isVirtual),
)
```

### 7.4 Null-Rendering Attachment 类型

这些 attachment 类型在 UI 中不渲染：

```typescript
// src/components/messages/nullRenderingAttachments.ts
const NULL_RENDERING_TYPES = [
  'hook_success',
  'hook_additional_context',
  'hook_cancelled',
  'command_permissions',
  'agent_mention',
  'budget_usd',
  'critical_system_reminder',
  'edited_image_file',
  'edited_text_file',
  'opened_file_in_ide',
  'output_style',
  'plan_mode',
  'plan_mode_exit',
  'plan_mode_reentry',
  'structured_output',
  'team_context',
  'todo_reminder',
  'context_efficiency',
  'deferred_tools_delta',
  'mcp_instructions_delta',
  'companion_intro',
  'token_usage',
  'ultrathink_effort',
  'max_turns_reached',
  'task_reminder',
  'auto_mode',
  'auto_mode_exit',
  'output_token_usage',
  'pen_mode_enter',
  'pen_mode_exit',
  'verify_plan_reminder',
  'current_session_memory',
  'compaction_reminder',
  'date_change',
]
```

**目的**：避免不可见消息占用 200 条消息渲染预算。

### 7.5 前端过滤流水线

```typescript
// src/components/Messages.tsx:499-514
const messagesToShowNotTruncated = reorderMessagesInUI(compactAwareMessages
  .filter(msg => msg.type !== 'progress')              // 1. 移除进度消息
  .filter(msg => !isNullRenderingAttachment(msg))      // 2. 移除 null 渲染
  .filter(msg => shouldShowUserMessage(msg, isTranscriptMode))  // 3. isMeta 过滤
, syntheticStreamingToolUseMessages);

// Brief 模式三层过滤
const briefFiltered = briefToolNames.length > 0 && !isTranscriptMode
  ? isBriefOnly
    ? filterForBriefTool(messages, briefToolNames)    // 仅保留 Brief 工具
    : dropTextInBriefTurns(messages, dropTextToolNames) // 移除 Brief 回合中的文本
    : messages;
```

---

## 8. 文件路径索引

| 文件 | 职责 |
|------|------|
| `src/utils/messages.ts` | 消息创建、规范化、isMeta/isVirtual 过滤 |
| `src/services/api/claude.ts` | 流式API处理 |
| `src/services/compact/compact.ts` | 对话压缩逻辑 |
| `src/services/compact/autoCompact.ts` | 自动压缩触发 |
| `src/utils/tokens.ts` | Token计数和估算 |
| `src/services/tools/StreamingToolExecutor.ts` | 流式工具执行 |
| `src/components/Messages.tsx` | 前端消息过滤流水线 |
| `src/components/messages/nullRenderingAttachments.ts` | Null 渲染 attachment 类型列表 |
| `src/components/VirtualMessageList.tsx` | Sticky prompt 过滤 |

---

## 9. 设计模式亮点

1. **并行预取**: 启动时并行执行MDM、钥匙串、API预连接
2. **懒加载**: 重模块延迟加载
3. **确定性ID派生**: 确保规范化后UUID稳定
4. **流式工具执行**: 工具在流式接收时就开始执行
5. **多层压缩策略**: Session Memory优先，完整压缩作为fallback