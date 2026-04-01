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

## 7. 设计模式亮点

1. **并行预取**: 启动时并行执行MDM、钥匙串、API预连接
2. **懒加载**: 重模块延迟加载
3. **确定性ID派生**: 确保规范化后UUID稳定
4. **流式工具执行**: 工具在流式接收时就开始执行
5. **多层压缩策略**: Session Memory优先，完整压缩作为fallback