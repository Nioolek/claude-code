# GacUI Prompt 系统解读报告

**仓库**: https://github.com/vczh-libraries/GacUI  
**解读日期**: 2026-04-12  
**文件位置**: `.github/prompts/`

---

## 1. 系统概述

GacUI 仓库实现了一套**高度结构化的 AI 协作开发系统**，通过 12 个 prompt 文件定义了完整的软件开发工作流。这套系统专为大型 C++ 项目设计，支持多轮迭代、多 Agent 协作和知识沉淀。

### 1.1 核心设计理念

```
┌─────────────────────────────────────────────────────────────┐
│              GacUI AI 协作系统设计哲学                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 文档驱动开发 (Document-Driven Development)               │
│     • 所有工作必须记录在结构化文档中                          │
│     • 代码变更前先完成设计/规划文档                           │
│     • 文档是唯一的真相来源 (Single Source of Truth)          │
│                                                             │
│  2. 分阶段工作流 (Phased Workflow)                           │
│     • Scrum → Design → Planning → Execution → Verify        │
│     • 每个阶段有独立的 prompt 和文档格式                       │
│     • 阶段间有明确的输入/输出契约                            │
│                                                             │
│  3. 多 Agent 协作 (Multi-Agent Collaboration)                │
│     • 主 Agent 负责协调和决策                                 │
│     • 子 Agent 负责构建、测试等具体任务                       │
│     • Review Board 多模型评审机制                            │
│                                                             │
│  4. 知识沉淀 (Knowledge Capturing)                           │
│     • 每个任务完成后提取学习点                               │
│     • 知识库持续更新和演进                                   │
│     • 避免重复错误，积累最佳实践                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Prompt 文件清单

| 文件 | 触发词 | 用途 | 输出文档 |
|------|--------|------|----------|
| `0-scrum.prompt.md` | `scrum` | 需求分析和任务拆解 | `Copilot_Scrum.md` |
| `1-design.prompt.md` | `design` | 技术方案设计 | `Copilot_Task.md` |
| `2-planning.prompt.md` | `plan` | 执行计划制定 | `Copilot_Planning.md` |
| `3-summarizing.prompt.md` | `summarize` | 执行文档生成 | `Copilot_Execution.md` |
| `4-execution.prompt.md` | `execute` | 代码实现 | 源代码 + `Copilot_Execution.md` |
| `5-verifying.prompt.md` | `verify` | 验证和测试 | `Copilot_Execution.md` |
| `ask.prompt.md` | `ask` | 问题分析 | 分析结果 |
| `investigate.prompt.md` | `investigate` | 问题调查 | `Copilot_Investigate.md` |
| `code.prompt.md` | `code` | 快速编码 | 源代码 |
| `kb.prompt.md` | `kb` | 知识库更新 | `Copilot_KB.md` |
| `refine.prompt.md` | `refine` | 学习提炼 | `Learning_*.md` |
| `review.prompt.md` | `review` | 文档评审 | `Copilot_Review_*.md` |

---

## 3. 核心工作流详解

### 3.1 完整工作流图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        GacUI AI 协作开发完整流程                          │
└─────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐
  │  用户提出需求  │
  └──────┬───────┘
         │
         ▼
  ┌──────────────────┐     ┌──────────────────┐
  │  scrum           │────►│ Copilot_Scrum.md │
  │  (需求分析)       │     │ • DESIGN REQUEST │
  │                  │     │ • TASKS          │
  └──────────────────┘     └──────────────────┘
         │
         ▼
  ┌──────────────────┐     ┌──────────────────┐
  │  design          │────►│ Copilot_Task.md  │
  │  (方案设计)       │     │ • PROBLEM        │
  │                  │     │ • INSIGHTS       │
  └──────────────────┘     └──────────────────┘
         │
         ▼
  ┌──────────────────┐     ┌──────────────────┐
  │  planning        │────►│ Copilot_Planning │
  │  (执行计划)       │     │ • EXECUTION PLAN │
  │                  │     │ • STEPS          │
  └──────────────────┘     └──────────────────┘
         │
         ▼
  ┌──────────────────┐     ┌──────────────────┐
  │  summarizing     │────►│ Copilot_Exec     │
  │  (执行文档)       │     │ • PLAN           │
  │                  │     │ • FIXING ATTEMPTS│
  └──────────────────┘     └──────────────────┘
         │
         ▼
  ┌──────────────────┐
  │  execute         │────► 源代码修改
  │  (代码实现)       │     编译 + 测试
  └──────────────────┘
         │
         ▼
  ┌──────────────────┐
  │  verify          │────► # !!!VERIFIED!!!
  │  (验证)           │     确保编译通过
  │                  │     确保测试通过
  └──────────────────┘
         │
         ▼
  ┌──────────────────┐
  │  refine          │────► Learning_*.md
  │  (学习提炼)       │     知识沉淀
  └──────────────────┘
```

---

## 4. 各 Prompt 详细解读

### 4.1 0-scrum.prompt.md — 需求分析

**触发词**: `scrum`  
**输出文档**: `Copilot_Scrum.md`  
**核心目标**: 将模糊的需求转化为结构化的任务列表

#### 文档结构

```markdown
# !!!SCRUM!!!

# DESIGN REQUEST
<用户问题描述的精确副本>

# UPDATES
## UPDATE
<每次更新的精确副本>

# TASKS
- [ ] TASK No.1: 任务标题
- [ ] TASK No.2: 任务标题

## TASK No.1: 任务标题
### what to be done
<任务的清晰定义>

### rationale
<任务必要性和优先级理由>

# Impact to the Knowledge Base
## ProjectName
<需要更新的知识库内容>
```

#### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Scrum 工作流程                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 识别问题                                            │
│  • 查找 LATEST chat message 中的 # Problem / # Update / # Learn │
│  • 忽略聊天记录历史中的标题                                   │
│                                                             │
│  Step 2: 创建/更新文档                                        │
│  • 新请求 (# Problem): 覆盖 Copilot_Scrum.md                  │
│  • 更新请求 (# Update): 追加到 # UPDATES                     │
│  • 继续请求 (无标题): 继续未完成的工作                        │
│                                                             │
│  Step 3: 任务拆解                                            │
│  • 将问题拆解为可执行的原子任务                               │
│  • 每个任务有明确的目标和理由                                 │
│  • 任务按优先级排序                                           │
│                                                             │
│  Step 4: 知识库影响分析                                       │
│  • 识别需要更新的知识库条目                                   │
│  • 记录在 # Impact to the Knowledge Base                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 关键约束

| 约束 | 说明 |
|------|------|
| **只允许修改** | `Copilot_Scrum.md` |
| **禁止修改** | 其他任何文件 |
| **任务格式** | `- [ ] TASK No.X: The Task Title` |
| **更新记录** | 每次用户更新必须精确复制到 `# UPDATES` |

---

### 4.2 1-design.prompt.md — 方案设计

**触发词**: `design`  
**输出文档**: `Copilot_Task.md`  
**核心目标**: 为选定的任务制定完整的技术方案

#### 文档结构

```markdown
# !!!TASK!!!

# PROBLEM DESCRIPTION
<问题描述的精确副本>

# UPDATES
## UPDATE
<每次更新的精确副本>

# INSIGHTS AND REASONING
<技术洞察和推理过程>

# AFFECTED PROJECTS
<受影响的项目列表>
```

#### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                   Design 工作流程                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  输入来源：                                                  │
│  • Copilot_Scrum.md 中的任务                                 │
│  • 用户直接提出的 # Problem                                  │
│                                                             │
│  任务标记：                                                  │
│  • "Next": 找到 Copilot_Scrum.md 中第一个未完成的任务          │
│  • "Complete task No.X": 定位特定任务                        │
│  • 在 Copilot_Scrum.md 中标记任务为进行中                      │
│                                                             │
│  准备工作：                                                  │
│  • 执行 copilotPrepare.ps1 清理上次运行的内容                 │
│  • 清理 Copilot_Task.md, Copilot_Planning.md,                │
│    Copilot_Execution.md                                     │
│                                                             │
│  方案设计：                                                  │
│  • 阅读相关知识库文档                                         │
│  • 分析受影响的项目和模块                                     │
│  • 编写 INSIGHTS AND REASONING                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 关键约束

| 约束 | 说明 |
|------|------|
| **只允许修改** | `Copilot_Task.md` (+ 在 `Copilot_Scrum.md` 标记任务) |
| **禁止修改** | 其他任何文件 |
| **准备脚本** | 必须先执行 `copilotPrepare.ps1` |
| **知识库查阅** | 必须查阅 `KnowledgeBase/Index.md` |

---

### 4.3 2-planning.prompt.md — 执行计划

**触发词**: `plan`  
**输出文档**: `Copilot_Planning.md`  
**核心目标**: 将设计方案转化为具体的执行步骤

#### 文档结构

```markdown
# !!!PLANNING!!!

# UPDATES
## UPDATE
<每次更新的精确副本>

# AFFECTED PROJECTS
<受影响的项目列表>

# EXECUTION PLAN
## STEP 1: 步骤标题
<详细的代码变更描述>
<变更必要性的解释>

## STEP 2: ...
```

#### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                  Planning 工作流程                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  输入：Copilot_Task.md (设计文档)                            │
│                                                             │
│  Step 1: 阅读设计文档                                         │
│  • 理解整体方案和目标                                         │
│  • 识别受影响的项目和模块                                     │
│  • 忽略知识库更新部分 (后续处理)                              │
│                                                             │
│  Step 2: 制定执行计划                                         │
│  • 将设计拆解为原子步骤                                       │
│  • 每个步骤包含：                                             │
│    - 清晰的代码变更描述                                       │
│    - 变更必要性的解释                                         │
│  • 步骤按依赖关系排序                                         │
│                                                             │
│  Step 3: 识别受影响项目                                       │
│  • 列出所有需要修改的项目                                     │
│  • 记录在 # AFFECTED PROJECTS                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.4 3-summarizing.prompt.md — 执行文档

**触发词**: `summarize`  
**输出文档**: `Copilot_Execution.md`  
**核心目标**: 生成最终的执行文档，准备代码实现

#### 文档结构

```markdown
# !!!EXECUTION!!!

# UPDATES
## UPDATE
<每次更新的精确副本>

# AFFECTED PROJECTS
<受影响的项目列表>

# EXECUTION PLAN
<详细的执行步骤>

# FIXING ATTEMPTS
<修复尝试记录>
```

---

### 4.5 4-execution.prompt.md — 代码实现

**触发词**: `execute`  
**输出**: 源代码修改 + `Copilot_Execution.md` 更新  
**核心目标**: 按照执行文档实现代码变更

#### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                 Execution 工作流程                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 应用代码变更                                         │
│  • 按照 Copilot_Execution.md 中的步骤执行                     │
│  • 每完成一步，在步骤标题后标记 [DONE]                         │
│  • 确保缩进和换行符合目标文件的风格                           │
│                                                             │
│  Step 2: 编译验证 (子 Agent 执行)                             │
│  • 主 Agent 调用子 Agent 进行构建                              │
│  • 每个 build-fix 过程由不同的子 Agent 执行                    │
│  • 主 Agent 不直接执行构建和获取结果                          │
│                                                             │
│  Step 3: 修复编译错误                                         │
│  • 识别错误来源 (callee side vs caller side)                 │
│  • 参考类似代码的写法                                         │
│  • 记录每次修复尝试到 Copilot_Execution.md                    │
│                                                             │
│  Step 4: 代码生成 (如需要)                                    │
│  • 检查 Code Generation Projects                            │
│  • 执行必要的代码生成项目                                     │
│  • 可能需要多次执行不同配置                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 关键约束

| 约束 | 说明 |
|------|------|
| **编译必须通过** | 所有代码变更必须编译通过 |
| **测试必须通过** | 所有单元测试必须通过 |
| **子 Agent 构建** | 每次构建 - 修复过程由不同子 Agent 执行 |
| **进度标记** | 每步完成后标记 `[DONE]` |
| **修复记录** | 每次修复尝试记录到 `# FIXING ATTEMPTS` |

---

### 4.6 5-verifying.prompt.md — 验证

**触发词**: `verify`  
**输出**: `Copilot_Execution.md` 添加 `# !!!VERIFIED!!!` 标记  
**核心目标**: 确保代码变更正确且测试通过

#### 验证流程

```
┌─────────────────────────────────────────────────────────────┐
│                  Verifying 工作流程                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 检查用户代码变更                                     │
│  • 对比 Copilot_Execution.md 和源代码                        │
│  • 发现差异时：                                              │
│    - 记录到 # UPDATES / ## User Update Spotted              │
│    - 不修改代码以匹配文档 (尊重用户修改)                      │
│                                                             │
│  Step 2: 编译验证 (子 Agent 执行)                             │
│  • 检查 # AFFECTED PROJECTS 确定构建目标                      │
│  • 识别编译警告和错误                                         │
│  • 只修复由代码变更引起的警告                                 │
│                                                             │
│  Step 3: 修复编译错误                                         │
│  • 每次修复尝试记录到 # FIXING ATTEMPTS                      │
│  • 包含：原因分析、修复方案、预期效果                         │
│                                                             │
│  Step 4: 测试验证                                            │
│  • 运行所有单元测试                                           │
│  • 确保所有测试通过                                           │
│                                                             │
│  Step 5: 添加验证标记                                         │
│  • 编译通过 + 测试通过后                                      │
│  • 在 Copilot_Execution.md 末尾添加 # !!!VERIFIED!!!          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.7 ask.prompt.md — 问题分析

**触发词**: `ask`  
**用途**: 纯分析问题，不修改代码

```markdown
# Analysis
- 这是分析工作，禁止修改源代码
- 查阅知识库了解组织结构
- 尽可能阅读相关源代码
- 尽力回答分析问题
```

---

### 4.8 investigate.prompt.md — 问题调查

**触发词**: `investigate`  
**输出文档**: `Copilot_Investigate.md`  
**核心目标**: 调查和定位 Bug 根因

#### 文档结构

```markdown
# !!!INVESTIGATE!!!

# PROBLEM DESCRIPTION
<问题描述的精确副本>

# UPDATES

# (CONTINUE|REPORT)

# TEST
<确认或定义问题的测试用例>

# PROPOSALS
- No.1 提案标题 [CONFIRMED|DENIED]
- No.2 提案标题

## No.1 提案标题
### CODE CHANGE
<实现的代码变更>

### (CONFIRMED|DENIED|DENIED BY USER)
<测试结果的详细解释>
```

#### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                 Investigate 工作流程                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 复现问题                                            │
│  • 编写测试用例定义/确认问题                                  │
│  • 记录测试步骤和预期结果                                     │
│                                                             │
│  Step 2: 提出假设                                            │
│  • 列出可能的根因假设                                         │
│  • 按可能性排序                                               │
│                                                             │
│  Step 3: 验证假设                                            │
│  • 实现代码变更验证假设                                       │
│  • 记录结果：CONFIRMED / DENIED / DENIED BY USER             │
│  • 详细解释判断依据                                           │
│                                                             │
│  Step 4: 确定根因                                            │
│  • 综合所有验证结果                                           │
│  • 确定根本原因                                               │
│  • 提出修复方案                                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.9 code.prompt.md — 快速编码

**触发词**: `code` (或首词不在列表中时的默认)  
**用途**: 快速实现代码变更，跳过完整文档流程

#### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Code 工作流程                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 实现需求                                            │
│  • 按照聊天消息实现任务                                       │
│  • 直接修改源代码                                             │
│                                                             │
│  Step 2: 编译验证 (子 Agent 执行)                             │
│  • 构建解决方案                                               │
│  • 检查编译警告和错误                                         │
│                                                             │
│  Step 3: 修复编译错误                                         │
│  • 识别错误来源                                               │
│  • 参考类似代码                                               │
│  • 子 Agent 执行修复                                          │
│                                                             │
│  Step 4: 代码生成 (如需要)                                    │
│  • 检查 Code Generation Projects                            │
│  • 执行必要的生成项目                                         │
│                                                             │
│  Step 5: 完成变更                                            │
│  • 确保编译通过                                               │
│  • 确保测试通过                                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.10 kb.prompt.md — 知识库更新

**触发词**: `kb`  
**输出文档**: `Copilot_KB.md`  
**核心目标**: 创建或更新知识库文档

#### 文档结构

```markdown
# !!!KNOWLEDGE BASE!!!

# DESIGN REQUEST
<问题描述的精确副本>

# INSIGHT
<深入研究后的洞察>

# ASKS
## QUESTION
<问题的精确副本>

### ANSWER
<研究后的答案>

# DRAFT
## DRAFT REQUEST
<草稿请求的精确副本>

## IMPROVEMENTS
### IMPROVEMENT
<改进请求的精确副本>

## (API|DESIGN) EXPLANATION
<文档标题和在 Index.md 中的位置>

## DOCUMENT
<草稿知识库文档>
```

#### 工作模式

| 模式 | 触发词 | 说明 |
|------|--------|------|
| **研究主题** | `# Topic` | 研究特定主题并撰写 KB 文档 |
| **回答问题** | `# Ask` | 回答具体问题 |
| **创建草稿** | `# Draft` | 创建 KB 文档草稿 |
| **改进文档** | `# Improve` | 改进现有 KB 文档 |
| **执行更新** | `# Execute` | 执行 KB 更新 |

---

### 4.11 refine.prompt.md — 学习提炼

**触发词**: `refine`  
**输出文档**: `Learning_*.md`  
**核心目标**: 从已完成的任务日志中提取学习点

#### 学习文件结构

```markdown
# !!!LEARNING!!!

# Orders
- 学习标题 [计数器]

# Refinements
## 标题
<学习内容和详细说明>
```

#### 学习文件分类

| 文件 | 位置 | 内容 |
|------|------|------|
| `Learning.md` | `KnowledgeBase/` | 跨项目通用学习 (C++、库使用、最佳实践) |
| `Learning_Coding.md` | `Learning/` | 本项目特定的编码学习 |
| `Learning_Testing.md` | `Learning/` | 本项目特定的测试学习 |

#### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                   Refine 工作流程                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 找到最早的备份文件夹                                 │
│  • 执行 copilotPrepare.ps1 -Earliest                        │
│  • 获取 Learning 中最早备份文件夹的绝对路径                    │
│                                                             │
│  Step 2: 阅读所有文档                                         │
│  • Copilot_Task.md                                          │
│  • Copilot_Planning.md                                      │
│  • Copilot_Execution.md                                     │
│  • Copilot_Execution_Finding.md                             │
│                                                             │
│  Step 3: 提取发现                                            │
│  • 关注所有 ## UPDATE 章节                                   │
│  • 关注 # Comparing to User Edit                            │
│  • 识别：                                                    │
│    - 最佳实践和编码偏好                                       │
│    - 犯过的错误和修正                                         │
│    - 用户偏好或厌恶的模式                                     │
│    - 用户对代码质量的理念                                     │
│                                                             │
│  Step 4: 撰写学习                                            │
│  • 确定合适的学习文件                                         │
│  • 每个发现要有简短但信息丰富的标题                           │
│  • 包含足够的约束条件以便未来理解                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.12 review.prompt.md — 文档评审

**触发词**: `review`  
**输出文档**: `Copilot_Review_*_*.md`  
**核心目标**: 多模型评审文档质量

#### 评审委员会机制

```
┌─────────────────────────────────────────────────────────────┐
│                   Review Board 机制                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  多模型评审：                                                │
│  • 每个模型独立撰写评审意见                                   │
│  • 评审意见保存到独立文件                                     │
│  • 文件名格式：Copilot_Review_{Finished|Writing}_{Name}.md  │
│                                                             │
│  评审轮次：                                                  │
│  • PREVIOUS ROUND: Copilot_Review_Finished_*.md             │
│  • CURRENT ROUND: Copilot_Review_Writing_*.md               │
│                                                             │
│  评审意见类型：                                              │
│  • ## Opinion: 对目标文档的意见                              │
│  • ### AGREE with {ModelName}: 同意其他模型                  │
│  • ### DISAGREE with {ModelName}: 不同意并说明理由           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 评审目标

| 评审类型 | 目标文档 | 评审范围 |
|----------|----------|----------|
| `# Scrum` | `Copilot_Scrum.md` | 从 `# TASKS` 到结尾，仅关注未完成任务 |
| `# Design` | `Copilot_Task.md` | 从 `# INSIGHTS AND REASONING` 到结尾 |
| `# Plan` | `Copilot_Planning.md` | 从 `# EXECUTION PLAN` 到结尾 |
| `# Summary` | `Copilot_Execution.md` | 从 `# EXECUTION PLAN` 到结尾 |
| `# Final` | - | 最终评审 |
| `# Apply` | - | 应用评审 |

---

## 5. AGENTS.md — AI 行为指南

`AGENTS.md` 是 AI Agent 的**入口指令**，定义了如何解释用户请求并路由到对应的 prompt 文件。

### 5.1 请求解释流程

```
┌─────────────────────────────────────────────────────────────┐
│                  AGENTS.md 请求解释流程                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 读取首词                                            │
│  • scrum → 0-scrum.prompt.md                                │
│  • design → 1-design.prompt.md                              │
│  • plan → 2-planning.prompt.md                              │
│  • summarize → 3-summarizing.prompt.md                      │
│  • execute → 4-execution.prompt.md                          │
│  • verify → 5-verifying.prompt.md                           │
│  • ask → ask.prompt.md                                      │
│  • investigate → investigate.prompt.md                      │
│  • code → code.prompt.md                                    │
│  • kb → kb.prompt.md                                        │
│  • refine → refine.prompt.md                                │
│  • review → review.prompt.md                                │
│  • 其他 → 默认 code.prompt.md，跳过 Step 2                   │
│                                                             │
│  Step 2: 读取第二词 (仅适用于特定首词)                         │
│  • 适用于：scrum, design, plan, summary, execute,            │
│           investigate, review, kb                           │
│  • 转换为标题格式：# THE-WORD                                │
│                                                             │
│  Step 3: 保留剩余内容                                         │
│  • 将处理后的请求视为 "the LATEST chat message"              │
│  • 按照选定的 prompt 文件开始工作                             │
│                                                             │
│  特殊处理：                                                  │
│  • "execute and verify" → 先 execute 后 verify               │
│  • 语音输入 (几乎无换行/标点) → 仔细考虑同音词                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 示例

| 用户请求 | 路由文件 | LATEST chat message |
|----------|----------|---------------------|
| `scrum` | `0-scrum.prompt.md` | (空) |
| `scrum learn` | `0-scrum.prompt.md` | `# Learn` |
| `design problem next` | `1-design.prompt.md` | `# Problem next` |
| `do this and do that` | `code.prompt.md` | `do this and do that` |

---

## 6. copilot-instructions.md — 通用指令

### 6.1 核心规则

| 规则 | 说明 |
|------|------|
| **REPO-ROOT** | 仓库根目录 |
| **SOLUTION-ROOT** | 解决方案根目录 (`*.sln` 或 `*.slnx`) |
| **禁止直接调用** | `msbuild`, `cmake`, `make`, `clang++`, `g++` |
| **PowerShell 格式** | `& absolute-path.ps1 parameters...` |
| **禁止创建/删除文件** | 除非明确指示 |
| **尊重并行编辑** | 写入前重新读取文件 |

### 6.2 C++ 编码规范

```cpp
// 推荐写法
auto&& collection = GetLargeCollection();  // 大类型用 auto&&
vint count = 10;                            // 用 vint 而非 int
const wchar_t* text = L"hello";             // 用 wchar_t 和 L""
vl::WString str = L"world";                 // 用 vl::WString 而非 std::string

// 集合类型
vl::collections::List<T>    // 而非 std::vector
vl::collections::Dictionary<K,V>  // 而非 std::map

// 正则表达式
// "." 表示点字符，"/." 或 "\\." 表示任意字符
// "/" 和 "\\" 都用于转义，推荐用 "/"
"// " 表示 "/" 字符
"/\\\\" 或 "/\\\\\\\\" 表示 "\\" 字符

// 头文件规范
#ifndef GUARD_MACRO
#define GUARD_MACRO
// ...
#endif

// 类成员对齐
class MyClass
{
public:
    int     member1;
    WString member2;
    bool    member3;
};

// 缩进
// C++ 源码：用 Tab
// JSON/XML: 用双空格
```

### 6.3 文件组织

| 目录 | 说明 |
|------|------|
| `Source/` | 可修改的源代码 |
| `Test/` | 可修改的测试代码 |
| `Import/` | 依赖项，禁止修改 |
| `Release/` | 生成的发布文件，禁止修改 |
| `.github/TaskLogs/` | 任务文档 |
| `.github/KnowledgeBase/` | 知识库 |
| `.github/Learning/` | 学习文档 |
| `.github/Scripts/` | 脚本文件 |

---

## 7. 文档文件清单

### 7.1 任务文档 (TaskLogs)

| 文件 | 阶段 | 用途 |
|------|------|------|
| `Copilot_Scrum.md` | Scrum | 需求分析和任务拆解 |
| `Copilot_Task.md` | Design | 技术方案设计 |
| `Copilot_Planning.md` | Planning | 执行计划 |
| `Copilot_Execution.md` | Execution/Verify | 执行记录和验证 |
| `Copilot_KB.md` | KB | 知识库草稿 |
| `Copilot_Investigate.md` | Investigate | 问题调查 |
| `Copilot_Review_*.md` | Review | 评审意见 |

### 7.2 学习文档 (Learning)

| 文件 | 位置 | 用途 |
|------|------|------|
| `Learning.md` | `KnowledgeBase/` | 跨项目通用学习 |
| `Learning_Coding.md` | `Learning/` | 本项目编码学习 |
| `Learning_Testing.md` | `Learning/` | 本项目测试学习 |

### 7.3 脚本文件 (Scripts)

| 文件 | 用途 |
|------|------|
| `copilotPrepare.ps1` | 准备环境，清理上次运行 |
| `copilotPrepareReview.ps1` | 准备评审环境 |
| `copilotBuild.ps1` | 构建脚本 |
| `copilotExecute.ps1` | 执行脚本 |
| `copilotDebug_Start.ps1` | 启动调试 |
| `copilotDebug_Stop.ps1` | 停止调试 |
| `copilotDebug_RunCommand.ps1` | 运行调试命令 |

---

## 8. 系统设计亮点

### 8.1 文档驱动开发

```
┌─────────────────────────────────────────────────────────────┐
│              文档驱动开发 (Document-Driven)                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  优势：                                                      │
│  • 可追溯性：所有决策和变更都有记录                          │
│  • 可恢复性：中断后可从文档恢复上下文                        │
│  • 可审计性：完整的开发历史和理由                            │
│  • 知识沉淀：避免重复错误，积累最佳实践                      │
│                                                             │
│  实现机制：                                                  │
│  • 每个阶段有独立的文档格式                                  │
│  • 文档必须精确复制用户输入                                  │
│  • 更新必须追加到 # UPDATES                                  │
│  • 进度标记 ([DONE], [CONFIRMED], etc.)                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 多 Agent 协作

```
┌─────────────────────────────────────────────────────────────┐
│                  多 Agent 协作架构                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  主 Agent 职责：                                             │
│  • 协调和决策                                                │
│  • 文档维护                                                  │
│  • 调用子 Agent                                              │
│                                                             │
│  子 Agent 职责：                                             │
│  • 构建解决方案                                              │
│  • 获取编译结果                                              │
│  • 修复编译错误                                              │
│  • 每次 build-fix 由不同子 Agent 执行                         │
│                                                             │
│  设计理由：                                                  │
│  • 隔离风险：构建失败不影响主 Agent 上下文                     │
│  • 并行处理：多个子 Agent 可同时处理不同任务                  │
│  • 资源管理：避免单个 Agent 上下文爆炸                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 评审委员会机制

```
┌─────────────────────────────────────────────────────────────┐
│                Review Board 多模型评审                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  参与者：多个 AI 模型 (Claude, GPT, Gemini 等)                 │
│                                                             │
│  流程：                                                      │
│  1. 每个模型独立阅读目标文档                                  │
│  2. 每个模型撰写评审意见                                      │
│  3. 模型间互相回复 (AGREE/DISAGREE)                          │
│  4. 多轮迭代直到达成共识                                      │
│                                                             │
│  优势：                                                      │
│  • 多视角：不同模型有不同专长                                 │
│  • 纠错：模型间可以互相纠正错误                               │
│  • 共识：最终决策更可靠                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.4 知识沉淀闭环

```
┌─────────────────────────────────────────────────────────────┐
│                  知识沉淀闭环                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  任务执行 → 文档记录 → 学习提炼 → 知识库更新 → 指导未来任务   │
│     │                                              │        │
│     └──────────────────────────────────────────────┘        │
│                        闭环反馈                               │
│                                                             │
│  refine prompt 的作用：                                      │
│  • 定期回顾已完成的任务日志                                   │
│  • 提取最佳实践和教训                                         │
│  • 识别用户偏好和模式                                         │
│  • 更新学习文档供未来参考                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. 与 CoPaw/其他 Agent 框架对比

| 特性 | GacUI Prompt 系统 | CoPaw | LangGraph |
|------|------------------|-------|-----------|
| **工作流定义** | Prompt 文件 + 文档格式 | Skill 系统 | Graph 状态机 |
| **文档驱动** | ✅ 强 (必须维护文档) | ⚠️ 中 (可选记忆) | ❌ 弱 |
| **多 Agent 协作** | ✅ 主/子 Agent + Review Board | ✅ 多 Agent 协作 | ✅ 多 Agent |
| **知识沉淀** | ✅ 自动提炼 (refine) | ✅ 记忆系统 | ⚠️ 手动 |
| **评审机制** | ✅ 多模型评审 | ❌ 无 | ❌ 无 |
| **适用场景** | 大型 C++ 项目开发 | 通用 Agent 任务 | LLM 应用编排 |

---

## 10. 总结

### 10.1 核心创新点

| 创新 | 说明 |
|------|------|
| **Prompt 路由系统** | 根据首词自动路由到对应工作流 |
| **文档格式标准化** | 每个阶段有严格的文档结构 |
| **多 Agent 构建隔离** | 子 Agent 负责构建，主 Agent 负责协调 |
| **评审委员会机制** | 多模型独立评审 + 互相回复 |
| **学习提炼闭环** | 定期从任务日志提取学习点 |
| **语音输入容错** | 自动识别并修正语音转写错误 |

### 10.2 适用场景

✅ **推荐使用**:
- 大型 C++ 项目开发
- 需要严格文档追溯的项目
- 多轮迭代的复杂任务
- 团队协作 (人类+AI)

⚠️ **谨慎考虑**:
- 快速原型开发 (文档开销较大)
- 简单任务 (可能过度设计)
- 非 C++ 项目 (需要适配构建系统)

### 10.3 可借鉴的设计

```
┌─────────────────────────────────────────────────────────────┐
│              可借鉴到其他 Agent 系统的设计                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Prompt 路由机制                                          │
│     • 根据请求首词自动选择工作流                              │
│     • 简单直观，易于扩展                                      │
│                                                             │
│  2. 文档格式标准化                                           │
│     • 每个阶段有明确的输入/输出契约                           │
│     • 便于中断恢复和上下文传递                                │
│                                                             │
│  3. 子 Agent 隔离                                            │
│     • 将耗时/易失败任务交给子 Agent                           │
│     • 保护主 Agent 上下文                                     │
│                                                             │
│  4. 多模型评审                                               │
│     • 关键决策前进行多模型评审                                │
│     • 提高决策质量                                            │
│                                                             │
│  5. 学习提炼机制                                             │
│     • 定期回顾和提取学习点                                    │
│     • 持续改进 Agent 表现                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 参考文献

1. GacUI GitHub: https://github.com/vczh-libraries/GacUI
2. AGENTS.md: https://raw.githubusercontent.com/vczh-libraries/GacUI/master/AGENTS.md
3. copilot-instructions.md: https://raw.githubusercontent.com/vczh-libraries/GacUI/master/.github/copilot-instructions.md
4. Prompt 目录：https://github.com/vczh-libraries/GacUI/tree/master/.github/prompts
