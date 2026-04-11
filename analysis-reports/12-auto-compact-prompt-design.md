# Claude Code 记忆压缩提示词设计深度解析

> 为什么一个压缩提示词需要 300+ 行？每一个设计选择背后都有故事。

---

## 引言：压缩提示词的"三明治"结构

Claude Code 的压缩提示词不是简单的"请总结一下对话"，而是一个精心设计的"三明治"：

```
┌─────────────────────────────────────────────────────────────┐
│ 第一层：NO_TOOLS_PREAMBLE（禁用工具的前菜）                   │
│ "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools."  │
├─────────────────────────────────────────────────────────────┤
│ 第二层：核心压缩指令（主菜）                                  │
│ ├── 分析指令（<analysis> 草稿区）                           │
│ ├── 摘要结构（9 个章节）                                    │
│ └── 示例模板                                                │
├─────────────────────────────────────────────────────────────┤
│ 第三层：自定义指令（可选配菜）                                │
│ "Additional Instructions: ..."                              │
├─────────────────────────────────────────────────────────────┤
│ 第四层：NO_TOOLS_TRAILER（禁用工具的后甜点）                  │
│ "REMINDER: Do NOT call any tools..."                        │
└─────────────────────────────────────────────────────────────┘
```

为什么这样设计？让我们一层层拆解。

---

## 第一层：NO_TOOLS_PREAMBLE —— 为什么"禁用工具"要放在最前面？

### 提示词内容

```text
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
```

### 设计原因：一个真实的失败案例

源码注释揭示了真相：

```typescript
// Aggressive no-tools preamble. The cache-sharing fork path inherits the
// parent's full tool set (required for cache-key match), and on Sonnet 4.6+
// adaptive-thinking models the model sometimes attempts a tool call despite
// the weaker trailer instruction. With maxTurns: 1, a denied tool call means
// no text output → falls through to the streaming fallback (2.79% on 4.6 vs
// 0.01% on 4.5). Putting this FIRST and making it explicit about rejection
// consequences prevents the wasted turn.
```

**问题场景**：

1. Full Compact 通过 `runForkedAgent` 启动子 Agent
2. 为了实现缓存命中，子 Agent **继承了父对话的所有工具定义**（否则缓存键不匹配）
3. Sonnet 4.6+ 的 adaptive-thinking 模型有时会"冲动地"调用工具
4. 但 `maxTurns: 1`，意味着只有一次机会
5. 如果工具调用被拒绝 → **没有任何文本输出** → 压缩失败

**失败率对比**：

| 模型 | 工具调用失败率 |
|------|---------------|
| Claude 4.5 | 0.01% |
| Claude 4.6+ | 2.79% |

### 为什么"后果警告"如此严厉？

```text
Tool calls will be REJECTED and will waste your only turn — you will fail the task.
```

这不是吓唬模型，而是**真实的后果**：

- `maxTurns: 1` = 只有一次回复机会
- 工具调用被拒绝 = 这一轮没有文本输出
- 没有文本输出 = 压缩失败

### 设计哲学

**把最重要的约束放在最前面**。LLM 对提示词开头的注意力最高，这是"首因效应"在提示词工程中的应用。

---

## 第二层：分析指令 —— 为什么要一个"草稿区"？

### 提示词内容

```text
Before providing your final summary, wrap your analysis in <analysis> tags to
organize your thoughts and ensure you've covered all necessary points.
In your analysis process:

1. Chronologically analyze each message and section of the conversation.
   For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like: file names, full code snippets, function signatures, file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback...

2. Double-check for technical accuracy and completeness...
```

### 设计原因：思维链（Chain-of-Thought）的显式化

这是一个经典的**思维链设计**：

1. **先思考（<analysis>）**：让模型"写下"思考过程
2. **再输出（<summary>）**：基于思考结果生成最终摘要

### 为什么"分析过程"最后会被删除？

```typescript
// src/services/compact/prompt.ts:314-319

// Strip analysis section — it's a drafting scratchpad that improves summary
// quality but has no informational value once the summary is written.
formattedSummary = formattedSummary.replace(
  /<analysis>[\s\S]*?<\/analysis>/,
  '',
)
```

**设计哲学**：

- 分析过程是"草稿纸"，帮助模型理清思路
- 草稿纸不需要保存到最终上下文中（浪费 tokens）
- 但草稿纸的存在**显著提高了摘要质量**

这就像考试时：
- 草稿纸上的演算过程帮助你得出正确答案
- 最终答题卡只需要答案，不需要演算过程
- 但没有草稿纸，答案质量会下降

### 分析指令的具体要求

| 要求 | 为什么重要？ |
|------|-------------|
| "Chronologically analyze" | 防止遗漏，保证时间线完整 |
| "user's explicit requests and intents" | 用户意图是最重要的上下文 |
| "full code snippets" | 代码是开发对话的核心资产 |
| "Errors that you ran into" | 错误历史避免重复犯错 |
| "user feedback" | 用户的纠正是关键约束 |

---

## 第三层：摘要结构 —— 为什么是这 9 个章节？

### 完整的 9 个章节

```text
1. Primary Request and Intent      # 用户想要什么
2. Key Technical Concepts          # 技术术语和框架
3. Files and Code Sections         # 涉及的文件和代码
4. Errors and fixes                # 错误和修复
5. Problem Solving                 # 问题解决过程
6. All user messages               # 所有用户消息
7. Pending Tasks                   # 待办任务
8. Current Work                    # 当前工作
9. Optional Next Step              # 下一步
```

### 设计原因：覆盖"上下文连续性"的所有要素

#### 章节 1-2：用户意图层

```
1. Primary Request and Intent
2. Key Technical Concepts
```

**设计目的**：让模型知道"用户想要什么"和"用什么技术"。

如果丢失这些信息，压缩后的模型可能会：
- 偏离用户原始目标
- 使用错误的技术栈
- 重复讨论已经确定的技术选型

#### 章节 3-5：执行历史层

```
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
```

**设计目的**：保留"做了什么"和"踩过什么坑"。

关键设计细节：
- "Pay special attention to the most recent messages" — 最近的最重要
- "include full code snippets where applicable" — 代码要完整，不要省略
- "summary of why this file read or edit is important" — 文件的**重要性**，不是内容

#### 章节 6：用户反馈层

```
6. All user messages: List ALL user messages that are not tool results.
```

**设计目的**：保留用户的完整反馈轨迹。

为什么强调 "ALL"？
- 用户可能在第 5 轮说了"不要用 TypeScript"
- 如果摘要遗漏这条，模型可能会在压缩后继续用 TypeScript
- 用户的所有反馈构成了"约束集合"

#### 章节 7-9：状态恢复层

```
7. Pending Tasks
8. Current Work
9. Optional Next Step
```

**设计目的**：让压缩后的模型能够"无缝继续"。

这是最关键的设计：

- `Current Work`：描述"正在做什么"
- `Optional Next Step`：描述"下一步做什么"
- `verbatim quotes`：**原文引用**，防止任务理解漂移

```text
If there is a next step, include direct quotes from the most recent conversation
showing exactly what task you were working on and where you left off.
This should be verbatim to ensure there's no drift in task interpretation.
```

**verbatium（逐字）** 这个词非常重要：
- 不是"大概意思"
- 不是"类似的话"
- 而是**原封不动地引用**

---

## 第四层：NO_TOOLS_TRAILER —— 为什么还要再提醒一次？

### 提示词内容

```text
REMINDER: Do NOT call any tools. Respond with plain text only —
an <analysis> block followed by a <summary> block.
Tool calls will be rejected and you will fail the task.
```

### 设计原因：近因效应 + 双重约束

**近因效应**：LLM 对提示词结尾的注意力也很高。

**双重约束**：
- 开头警告（首因效应）
- 结尾警告（近因效应）

这是提示词工程中的"三明治技巧"：
- 重要的约束放在开头和结尾
- 中间放详细内容
- 确保 LLM 不会"忘记"关键约束

### 为什么不是"三重约束"？

也许你会问：为什么不在中间也加一个警告？

**原因**：
- 过多的重复警告可能触发"忽略模式"
- 中间内容太长，中间位置的警告效果有限
- 开头 + 结尾的"三明治"已经足够有效

---

## 第五层：自定义指令 —— 用户如何影响压缩？

### 注入点

```typescript
// src/services/compact/prompt.ts:284-286

if (customInstructions && customInstructions.trim() !== '') {
  prompt += `\n\nAdditional Instructions:\n${customInstructions}`
}
```

自定义指令被注入在"主菜"和"后甜点"之间。

### 自定义指令从哪里来？

```typescript
// src/services/compact/compact.ts:420-424

customInstructions = mergeHookInstructions(
  customInstructions,           // 用户配置的自定义指令
  hookResult.newCustomInstructions,  // Hook 返回的指令
)
```

两个来源：
1. **用户配置**：设置中的 `compactInstructions`
2. **Hook 返回**：`pre_compact` hook 可以动态注入指令

### 自定义指令示例

提示词中给出了示例：

```text
<example>
## Compact Instructions
When summarizing the conversation focus on typescript code changes
and also remember the mistakes you made and how you fixed them.
</example>

<example>
# Summary instructions
When you are using compact - please focus on test output and code changes.
Include file reads verbatim.
</example>
```

这允许用户：
- 强调关注某类信息（如测试输出）
- 要求保留特定格式（如完整文件内容）
- 添加领域特定的摘要要求

---

## 第六层：后处理 —— 为什么分析块要被删除？

### formatCompactSummary 函数

```typescript
export function formatCompactSummary(summary: string): string {
  let formattedSummary = summary

  // 1. 删除分析块
  formattedSummary = formattedSummary.replace(
    /<analysis>[\s\S]*?<\/analysis>/,
    '',
  )

  // 2. 提取摘要内容
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

### 设计原因

1. **删除分析块**：
   - 分析是"思维过程"，不是"信息"
   - 保留会浪费上下文空间
   - 但分析的存在提高了摘要质量

2. **转换 XML 标签**：
   - `<summary>` → `Summary:`
   - 更易读，更简洁

3. **清理空白**：
   - 删除多余的换行
   - 保证格式整洁

---

## 三种提示词变体：不同场景的不同策略

Claude Code 定义了三种压缩提示词：

### 1. BASE_COMPACT_PROMPT（完整压缩）

```text
Your task is to create a detailed summary of the conversation so far...
```

用于：**Full Compact**，所有历史都需要压缩。

### 2. PARTIAL_COMPACT_PROMPT（部分压缩 - from）

```text
Your task is to create a detailed summary of the RECENT portion of the conversation —
the messages that follow earlier retained context...
```

用于：部分压缩，保留早期上下文，只压缩最近部分。

### 3. PARTIAL_COMPACT_UP_TO_PROMPT（部分压缩 - up_to）

```text
Your task is to create a detailed summary of this conversation.
This summary will be placed at the start of a continuing session;
newer messages that build on this context will follow after your summary...
```

用于：缓存命中场景，摘要会放在保留消息之前。

**关键区别**：章节 9 的变化

| 变体 | 章节 9 内容 |
|------|-----------|
| BASE | Optional Next Step |
| PARTIAL (from) | Optional Next Step |
| PARTIAL (up_to) | Context for Continuing Work |

因为 `up_to` 模式下，摘要后还有保留的消息，所以需要"上下文衔接"而不是"下一步"。

---

## 压缩后消息构建：无缝衔接的艺术

### getCompactUserSummaryMessage 函数

```typescript
let baseSummary = `This session is being continued from a previous conversation
that ran out of context. The summary below covers the earlier portion of the conversation.

${formattedSummary}`

if (transcriptPath) {
  baseSummary += `\n\nIf you need specific details from before compaction (like exact
code snippets, error messages, or content you generated), read the full transcript at:
${transcriptPath}`
}

if (recentMessagesPreserved) {
  baseSummary += `\n\nRecent messages are preserved verbatim.`
}

if (suppressFollowUpQuestions) {
  baseSummary += `\nContinue the conversation from where it left off without asking the
user any further questions. Resume directly — do not acknowledge the summary, do not
recap what was happening, do not preface with "I'll continue" or similar. Pick up the
last task as if the break never happened.`
}
```

### 设计亮点

1. **上下文说明**：
   - 告诉模型"这是压缩后的对话"
   - 解释"为什么有这个摘要"

2. **逃生通道**：
   - 提供完整的 transcript 路径
   - 如果摘要不够详细，可以去查原文

3. **状态提示**：
   - "Recent messages are preserved verbatim"
   - 告诉模型最近的消息是原始的，不是摘要

4. **行为约束**：
   - "Resume directly"
   - "do not acknowledge the summary"
   - "as if the break never happened"
   - 防止模型说"好的，让我继续之前的工作"这类废话

---

## 总结：提示词设计的核心原则

### 1. 约束优先

- 关键约束（禁用工具）放在开头和结尾
- 使用"CRITICAL"、"REMINDER"等强调词
- 明确后果（"you will fail the task"）

### 2. 思维链显式化

- 分析块作为"草稿纸"
- 提高输出质量
- 后处理删除以节省空间

### 3. 结构化输出

- 9 个章节覆盖所有关键信息
- 示例模板确保格式一致
- 明确要求（"verbatim"、"ALL"）

### 4. 无缝衔接

- 当前工作 + 下一步
- 原文引用防止理解漂移
- 行为约束避免冗余回复

### 5. 可扩展性

- 自定义指令注入点
- Hook 支持动态修改
- 三种变体适应不同场景

---

## 附录：完整提示词结构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│ NO_TOOLS_PREAMBLE                                                        │
│ ├── 禁用工具声明                                                          │
│ ├── 工具列表（Read, Bash, Grep...）                                      │
│ ├── 后果警告（"waste your only turn"）                                   │
│ └── 输出格式要求（<analysis> + <summary>）                               │
├─────────────────────────────────────────────────────────────────────────┤
│ BASE_COMPACT_PROMPT                                                      │
│ ├── 任务声明（"create a detailed summary"）                              │
│ ├── DETAILED_ANALYSIS_INSTRUCTION                                        │
│ │   ├── 分析方法（"Chronologically analyze"）                            │
│ │   ├── 关注点列表（requests, code, errors...）                          │
│ │   └── 检查要求（"Double-check"）                                       │
│ ├── 摘要结构要求（9 个章节）                                              │
│ ├── 示例模板（<example>）                                                │
│ └── 自定义指令提示（"There may be additional instructions"）             │
├─────────────────────────────────────────────────────────────────────────┤
│ Additional Instructions（可选）                                           │
│ └── 用户自定义或 Hook 注入的指令                                          │
├─────────────────────────────────────────────────────────────────────────┤
│ NO_TOOLS_TRAILER                                                         │
│ └── 再次提醒禁用工具                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

**参考资料**：
- 源码：`src/services/compact/prompt.ts`
- 压缩流程：`src/services/compact/compact.ts`
- 后处理：`formatCompactSummary()` 函数