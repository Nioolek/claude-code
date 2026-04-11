# Claude Code 的"记忆压缩术"：当 AI 聊天也要清理内存条

> 一个关于上下文窗口管理的幽默技术解读

---

## 引言：你的大脑"内存条"满了吗？

想象一下这个场景：你正在和一个朋友热火朝天地聊天，从天气聊到股市，从股市聊到Python代码，从Python代码聊到你今天吃了什么...

突然，你的大脑发出了一个警告：**"内存不足，请清理历史记录"**。

听起来很荒谬？但对 Claude 来说，这恰恰是真实发生的"危机"。

Claude 的上下文窗口就像一个固定大小的"聊天内存条"——200K tokens（大约相当于一本小小说的字数）。当你们聊得太久、太多，这个内存条就会被塞满。这时候，Claude Code 就会悄悄启动它的"记忆压缩术"，把历史对话打包成一份精简的摘要，为新的聊天腾出空间。

今天，我们就来揭秘这个神奇的"压缩术"背后的技术原理。别担心，我会用最通俗的语言，让你笑着读完这篇技术博客。

---

## 两种压缩模式：整理房间有"快省力"和"请外援"

Claude Code 的压缩机制有两个"版本"，就像整理房间有两种策略：

### 模式一：Session Memory Compact（"预习笔记模式"）

想象你是个好学生，每节课结束后都会整理一份笔记。期末复习时，你不需要重新翻阅所有课本，直接看笔记就行了。

Session Memory Compact 就是这个思路：**Claude Code 在聊天过程中，会偷偷"整理笔记"（提取 Session Memory）。当需要压缩时，直接拿出这份预先整理好的笔记，替换掉历史对话。**

特点：
- 🚀 **零成本**：不需要额外调用大模型
- ⚡ **速度快**：直接用现成的笔记
- 🔒 **隐私好**：最近的对话不会被发送给大模型处理

### 模式二：Full Compact（"请整理师模式"）

如果预习笔记没准备好（Session Memory 为空或不可用），那就只能"请外援"了。

Full Compact 会启动一个独立的"整理师 Agent"，让它阅读完整的历史对话，然后生成一份专业的摘要。虽然要花钱（API 调用），但保证能把任何杂乱的对话整理得井井有条。

特点：
- 💰 **有成本**：需要调用大模型 API
- 📊 **覆盖全**：所有历史都会被摘要覆盖
- 🔄 **智能恢复**：压缩后会重新读取最近访问的文件

| 模式 | 是否调用大模型 | 成本 | 隐私性 | 覆盖范围 |
|------|:---:|:---:|:---:|:---:|
| Session Memory Compact | ❌ | 零 | 高 | 只替换早期对话 |
| Full Compact | ✅ | 有（有缓存） | 中 | 替换所有对话 |

---

## Token 预算管理：像管理手机电池一样管理上下文

如果 Claude 的上下文窗口是"电池"，那 Claude Code 就是个精明的"电量管理器"。

### 有效容量计算

Claude 的"电池"虽然标称 200K tokens，但实际可用容量要打个折：

```
标称容量：        200,000 tokens
预留输出空间：    -20,000 tokens (为 Claude 的回复预留)
─────────────────────────────────
有效上下文窗口：  180,000 tokens
```

为什么要预留 20K？因为 Claude 回复时也需要"内存空间"——你不能把电池用光，总得留点电让手机还能开机。

### 那个神秘的 92.8%

Claude Code 不会等到电池耗尽才压缩，而是在电量到达 **92.8%** 左右就提前行动：

```
有效上下文窗口：  180,000 tokens
缓冲区：          -13,000 tokens (安全缓冲)
─────────────────────────────────
自动压缩触发点：  167,000 tokens ≈ 92.8%
```

这就像你的手机电量到 20% 就提醒充电——预防性管理，永远不掉链子。

### 那条"红线"

如果用户无视一切警告，继续疯狂聊天，Claude Code 会有一条最终红线：

```
阻塞限制：约 98.3% (177K tokens)
```

到了这条红线，系统会拒绝继续对话，直到用户同意压缩或清理消息。这就像手机电量 0% 时的强制关机——没办法，真的没办法。

---

## 触发机制：不是每次都"打扫卫生"

你可能好奇：是不是每次对话 Claude Code 都要检查要不要压缩？那岂不是很累？

答案是：**智能触发，不是每秒都在打扫**。

### 什么时候检查？

Claude Code 只在 **每轮对话结束后** 检查一次：

1. 用户发送消息
2. Claude 回复
3. 回复完成后，悄悄检查 token 数
4. 如果超过阈值 → 启动压缩
5. 继续下一轮对话

就像你只在吃完饭后洗碗，而不是每吃一口就刷一次碗。

### 递归保护：防止"压缩死循环"

这里有个有趣的问题：Session Memory Compact 和 Full Compact 都是通过启动子 Agent 来工作的。那如果子 Agent 自己的对话也超出了上下文限制怎么办？

Claude Code 的解决方案是：**递归保护**。

```typescript
// 如果是子 Agent 的查询，直接跳过自动压缩检查
if (querySource === 'session_memory' || querySource === 'compact') {
  return false  // 防止子 Agent 嵌套调用自己
}
```

就像你不能让洗碗机自己洗自己——那样会无限循环，最后把洗碗机洗坏了。

### 断路器机制：连续失败就放弃

这里有个真实的工程故事。Anthropic 的工程师发现了一个惊人的数据：

> 1,279 个会话中有 50+ 次连续压缩失败（最高 3,272 次），每天浪费约 250,000 次 API 调用。

有些用户的对话实在太长太复杂，压缩就是不可能成功。但系统一直在尝试、失败、尝试、失败...像个执念深重的强迫症患者。

于是工程师加了断路器：

```typescript
const MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3

// 连续失败 3 次后，停止尝试
if (tracking?.consecutiveFailures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES) {
  return { wasCompacted: false }
}
```

就像你家灯泡连续闪烁 3 次，电工就会说"算了，换条线吧"，而不是继续折腾。

---

## Session Memory Compact：不花钱的压缩术

让我们深入看看 Session Memory Compact 是怎么做到"零成本"的。

### 预提取机制

Session Memory 系统会在对话过程中**异步提取关键信息**：

- 用户的需求和意图
- 关键技术决策
- 涉及的文件路径
- 错误和修复过程

这些信息被保存到一个独立的"记忆文件"中。当压缩需要时，直接读取这个文件，不需要再调用大模型。

### 留一手：保留最近的对话

Session Memory Compact 有个有趣的设计：**它不会把所有对话都压缩**。

```
压缩前：
├── 第 1-8 轮对话 ← 这些会被 Session Memory 替换
└── 第 9-10 轮对话 ← 这些直接保留原样！

压缩后：
├── Session Memory 摘要
└── 第 9-10 轮对话 (原样保留)
```

为什么要保留最近的对话？因为：
1. 最近的信息最可能被后续对话引用
2. 最近的对话包含最新的上下文
3. 避免把用户"刚说的话"也压缩掉

默认配置：
- 最少保留 10,000 tokens 的最近消息
- 最少保留 5 条带文本的消息
- 最多保留 40,000 tokens

这就像整理房间时，你不会把今天刚放的东西也打包进柜子——万一一会儿还要用呢？

---

## Full Compact：请整理师的艺术

当 Session Memory Compact 不能用时，Full Compact 就出场了。

### 调用大模型，但不"乱花钱"

Full Compact 会调用大模型 API 来生成摘要，但它有个省钱秘籍：**缓存命中**。

```typescript
const result = await runForkedAgent({
  promptMessages: [summaryRequest],  // 压缩请求
  cacheSafeParams,                   // 继承主对话的缓存参数
  maxTurns: 1,                       // 只允许一轮
  canUseTool: false,                 // 禁用所有工具
})
```

关键设计：
- `cacheSafeParams`：继承主对话的系统提示词、工具定义、模型配置
- Anthropic API 的缓存基于"消息前缀"——如果前缀相同，就能命中缓存
- 实测数据：**98% 的缓存命中率**

这意味着 Full Compact 的 API 成本其实很低——大部分 tokens 都是从缓存读取的（便宜），只有新增的压缩请求部分需要新计算。

### 压缩提示词的"三段式结构"

Full Compact 发送给大模型的提示词结构很有趣：

```
┌─────────────────────────────────────────────────────────────┐
│ 第一段：NO_TOOLS_PREAMBLE                                    │
│ "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools."  │
│ （开头就警告：别调用工具！）                                  │
├─────────────────────────────────────────────────────────────┤
│ 第二段：BASE_COMPACT_PROMPT                                  │
│ "Your task is to create a detailed summary..."              │
│ （详细的摘要任务说明）                                        │
├─────────────────────────────────────────────────────────────┤
│ 第三段：NO_TOOLS_TRAILER                                     │
│ "REMINDER: Do NOT call any tools..."                        │
│ （结尾再警告一次）                                            │
└─────────────────────────────────────────────────────────────┘
```

为什么要在开头和结尾都警告"不要调用工具"？因为工程师发现：

> 在 Sonnet 4.6+ 的 adaptive-thinking 模型上，即使有尾部指令，模型有时仍会尝试工具调用。由于 maxTurns=1，被拒绝的工具调用意味着没有文本输出，导致失败。

这就像你请整理师来家里，在门口就告诉他"不要翻我的抽屉"，进门后再强调一次，临走时再提醒一次——因为有些整理师实在太好动了。

### 禁止设置 maxOutputTokens 的有趣原因

代码注释里有个特别的说明：

```typescript
// DO NOT set maxOutputTokens here. The fork piggybacks on the main thread's
// prompt cache by sending identical cache-key params. Setting maxOutputTokens
// would clamp budget_tokens via Math.min(budget, maxOutputTokens-1),
// creating a thinking config mismatch that invalidates the cache.
```

翻译：如果设置 maxOutputTokens，会影响 thinking 配置中的 budget_tokens，导致缓存失效。

这就像你为了省钱用优惠券，但优惠券有个奇怪的条件"不能用塑料袋"，结果你带了个布袋子，店员说"抱歉，这个布袋子看起来和塑料袋材质不同，优惠券无效"。

---

## 关键问题解答：压缩后内容会不会丢失？

这是用户最关心的问题：**之前读取的文件内容，压缩后还在吗？**

答案是：**有保护机制，但有边界限制**。

### 搬家打包的艺术

压缩就像搬家打包：

1. **摘要中的文字描述**（有损）
   - 大模型会在摘要中写下："用户阅读了 src/main.py，这是主入口文件..."
   - 但这只是文字描述，不是完整文件内容

2. **后压缩文件恢复**（无损）
   - Claude Code 会重新读取最近访问的文件，附加到压缩后的上下文中
   - 这就是真正的内容恢复！

### 后压缩文件恢复的参数

```typescript
POST_COMPACT_MAX_FILES_TO_RESTORE = 5   // 最多恢复 5 个文件
POST_COMPACT_TOKEN_BUDGET = 50_000      // 总 token 预算 50K
POST_COMPACT_MAX_TOKENS_PER_FILE = 5_000 // 每文件最多 5K tokens
```

这意味着：
- 你读了 10 个文件 → 只有最近 5 个会被恢复
- 每个文件最多保留 5K tokens（大文件会被截断）
- 总预算 50K tokens

### 工作流程图

```
压缩前：
├── 用户消息："读取 src/main.py"
├── Claude 调用 Read 工具
├── tool_result: <完整的 main.py 内容，50K tokens>
├── ...继续对话...

压缩后：
├── compact_boundary 系统消息
├── 摘要："用户曾读取 src/main.py..."
├── Attachment: [Read: src/main.py] ← 重新读取，最多 5K tokens
└── 继续对话...
```

### 局限性总结

| 限制 | 说明 | 对用户的影响 |
|------|------|-------------|
| 文件数量限制 | 最多 5 个 | 读了很多文件时，较早的文件内容会丢失 |
| Token 截断 | 每文件最多 5K | 大文件可能只保留开头部分 |
| 时间排序 | 按最近访问排序 | 早期重要但未再访问的文件可能丢失 |

---

## 代码亮点解读：工程师的智慧

让我们从源码中找几个有趣的工程智慧。

### API 不变量保护：工具调用不能"拆散"

流式响应可能把一条消息分成多个块（thinking、tool_use等），但 API 有个严格要求：**tool_use 和 tool_result 必须配对**。

Claude Code 有个函数专门处理这个问题：

```typescript
export function adjustIndexToPreserveAPIInvariants(
  messages: Message[],
  startIndex: number,
): number {
  // 收集保留范围内所有 tool_result 的 ID
  const allToolResultIds = collectToolResultIds(messages.slice(startIndex))

  // 向后查找匹配的 tool_use 消息，确保不拆散对
  for (let i = startIndex - 1; i >= 0; i--) {
    if (hasToolUseWithIds(messages[i], neededToolUseIds)) {
      startIndex = i  // 扩展索引
    }
  }
}
```

这就像你不能只打包"锅盖"不打包"锅"——它们必须一起带走。

### Prompt-Too-Long 重试：最后的挣扎

压缩请求本身也可能超出上下文限制！这听起来有点讽刺：你要压缩，但压缩请求自己太长了。

Claude Code 的处理：

```typescript
for (;;) {
  summaryResponse = await streamCompactSummary(...)

  if (!summary?.startsWith(PROMPT_TOO_LONG_ERROR_MESSAGE)) break

  // 截断最旧的对话，重试
  ptlAttempts++
  const truncated = truncateHeadForPTLRetry(messagesToSummarize, summaryResponse)

  if (!truncated || ptlAttempts > MAX_PTL_RETRIES) {
    throw new Error(ERROR_MESSAGE_PROMPT_TOO_LONG)
  }

  messagesToSummarize = truncated  // 用截断后的消息重试
}
```

最多重试 3 次，每次丢弃更多的旧对话。这就像你试图把所有行李装进箱子，箱子太小，就只能扔掉最旧的东西。

---

## 总结：设计哲学

Claude Code 的自动压缩机制体现了几个重要的设计哲学：

### 1. 可靠性优先

不管用什么策略，**保证对话能继续**是第一位的。双层策略（Session Memory + Full Compact）确保总有 fallback。

### 2. 成本优化

- Session Memory Compact 零成本
- Full Compact 98% 缓存命中
- 断路器避免无效重复

### 3. 用户友好

自动触发、无感知、保持上下文连续性。用户不需要知道什么是 token、什么是上下文窗口——聊天自然流畅。

### 4. 精确量化

不是凭感觉，而是精确计算：
- 200K - 20K = 180K 有效窗口
- 180K - 13K = 167K 触发阈值
- 连续失败 3 次 = 断路器触发

---

## 结语

下次当你和 Claude 聊了很久很久，突然看到一行提示"Compacting conversation..."，你知道发生了什么吗？

Claude Code 正在悄悄地帮你"整理房间"——把旧对话打包成摘要，给新的聊天腾出空间。它可能用的是预先准备的笔记（Session Memory），也可能请了个整理师（Full Compact），但不管用什么方法，它都在尽力保证：

1. 你的对话不会突然中断
2. 最近的内容不会丢失
3. 你甚至不知道它刚刚帮你"打扫了卫生"

这就是 Claude Code 的"记忆压缩术"——一个默默工作、可靠高效、用户无感知的上下文管理大师。

下次聊天时，不妨在心里对它说一声："辛苦了，小管家！"

---

**参考资料**：
- 分析报告：`analysis-reports/11-auto-compact-deep-dive.md`
- 源码：`src/services/compact/autoCompact.ts`, `src/services/compact/compact.ts`, `src/services/compact/sessionMemoryCompact.ts`