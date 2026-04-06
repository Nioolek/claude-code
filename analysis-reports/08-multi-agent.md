# Claude Code 多代理协调系统深度分析报告

## 一、模块概述

Claude Code 的多代理协调系统是一个分层架构的 Agent 编排框架，支持三种核心模式：

1. **Coordinator 模式**：Leader-Worker 架构，Leader 负责任务分发和结果综合
2. **AgentTool 子代理**：同步/异步 Agent 派发，支持后台执行
3. **Fork 子代理**：子代理继承父代理完整上下文，实现提示缓存共享

### 核心架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      Leader Agent                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │AgentTool     │  │SendMessage   │  │TaskStop      │       │
│  │(spawn)       │  │(continue)    │  │(kill)        │       │
│  └──────┬───────┘  └──────────────┘  └──────────────┘       │
└─────────┼───────────────────────────────────────────────────┘
          │ spawn
          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Swarm Backend Layer                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │TmuxBackend  │  │InProcess    │  │ITermBackend │          │
│  │(pane-based) │  │Backend      │  │(pane-based) │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Teammate Execution                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │TeammateContext│ │ Mailbox      │  │PermissionSync│       │
│  │(AsyncLocal)  │  │(Message Pass)│  │(Cross-Agent) │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、核心组件分析

### 2.1 Coordinator 模式

**核心特性**:
- **Leader 职责**: 任务分解、Worker 派发、结果综合
- **Worker 工具集**: 受限的工具列表（`ASYNC_AGENT_ALLOWED_TOOLS`）
- **通知机制**: Worker 结果通过 `<task-notification>` XML 格式回传

**Worker 提示词综合规则**（关键设计亮点）:
- Leader 必须"理解"Worker 的研究发现，然后编写具体实现规范
- 禁止 "based on your findings" 这类懒惰委派语句
- 必须包含具体文件路径、行号、修改内容

### 2.2 AgentTool 子代理系统

**输入 Schema**:
```typescript
z.object({
  description: z.string().describe('A short (3-5 word) description'),
  prompt: z.string().describe('The task for the agent to perform'),
  subagent_type: z.string().optional(),
  model: z.enum(['sonnet', 'opus', 'haiku']).optional(),
  run_in_background: z.boolean().optional()
})
```

**派发决策逻辑**:
```typescript
const shouldRunAsync = (run_in_background === true ||
                         selectedAgent.background === true ||
                         isCoordinator ||
                         forceAsync)
                       && !isBackgroundTasksDisabled;
```

### 2.3 createSubagentContext 上下文隔离

**设计哲学**：默认隔离，显式共享——所有可变状态默认被隔离，只有通过显式 opt-in 才能共享。这防止了子代理意外污染父代理状态，同时允许交互式代理选择共享。

#### 完整实现代码

```typescript
export function createSubagentContext(
  parentContext: ToolUseContext,
  overrides?: SubagentContextOverrides,
): ToolUseContext {
  // AbortController 分级决策
  const abortController =
    overrides?.abortController ??
    (overrides?.shareAbortController
      ? parentContext.abortController
      : createChildAbortController(parentContext.abortController))

  // 权限上下文封装
  const getAppState: ToolUseContext['getAppState'] = overrides?.getAppState
    ? overrides.getAppState
    : overrides?.shareAbortController
      ? parentContext.getAppState
      : () => {
          const state = parentContext.getAppState()
          if (state.toolPermissionContext.shouldAvoidPermissionPrompts) {
            return state
          }
          return {
            ...state,
            toolPermissionContext: {
              ...state.toolPermissionContext,
              shouldAvoidPermissionPrompts: true,
            },
          }
        }

  return {
    // Mutable state - cloned by default to maintain isolation
    readFileState: cloneFileStateCache(
      overrides?.readFileState ?? parentContext.readFileState,
    ),
    nestedMemoryAttachmentTriggers: new Set<string>(),
    loadedNestedMemoryPaths: new Set<string>(),
    dynamicSkillDirTriggers: new Set<string>(),
    discoveredSkillNames: new Set<string>(),
    toolDecisions: undefined,
    contentReplacementState:
      overrides?.contentReplacementState ??
      (parentContext.contentReplacementState
        ? cloneContentReplacementState(parentContext.contentReplacementState)
        : undefined),

    // AbortController
    abortController,

    // AppState access
    getAppState,
    setAppState: overrides?.shareSetAppState
      ? parentContext.setAppState
      : () => {},
    setAppStateForTasks:
      parentContext.setAppStateForTasks ?? parentContext.setAppState,
    localDenialTracking: overrides?.shareSetAppState
      ? parentContext.localDenialTracking
      : createDenialTrackingState(),

    // Mutation callbacks - no-op by default
    setInProgressToolUseIDs: () => {},
    setResponseLength: overrides?.shareSetResponseLength
      ? parentContext.setResponseLength
      : () => {},
    pushApiMetricsEntry: overrides?.shareSetResponseLength
      ? parentContext.pushApiMetricsEntry
      : undefined,
    updateFileHistoryState: () => {},
    updateAttributionState: parentContext.updateAttributionState,

    // UI callbacks - undefined for subagents
    addNotification: undefined,
    setToolJSX: undefined,
    setStreamMode: undefined,
    setSDKStatus: undefined,
    openMessageSelector: undefined,

    // Inherited or overridden fields
    options: overrides?.options ?? parentContext.options,
    messages: overrides?.messages ?? parentContext.messages,
    agentId: overrides?.agentId ?? createAgentId(),
    agentType: overrides?.agentType,

    // Query tracking chain
    queryTracking: {
      chainId: randomUUID(),
      depth: (parentContext.queryTracking?.depth ?? -1) + 1,
    },
    fileReadingLimits: parentContext.fileReadingLimits,
    userModified: parentContext.userModified,
    criticalSystemReminder_EXPERIMENTAL:
      overrides?.criticalSystemReminder_EXPERIMENTAL,
    requireCanUseTool: overrides?.requireCanUseTool,
  }
}
```

#### 可变状态隔离详解

**1. readFileState（文件状态缓存）**

```typescript
readFileState: cloneFileStateCache(
  overrides?.readFileState ?? parentContext.readFileState,
)
```

- **隔离原因**：子代理有自己的文件读取历史，不应影响父代理缓存决策
- **克隆而非新建**：继承父代理已读取信息，有助于提示缓存命中——相同前缀消息+相同文件状态=缓存命中

**2. contentReplacementState（工具结果替换状态）**

```typescript
contentReplacementState:
  overrides?.contentReplacementState ??
  (parentContext.contentReplacementState
    ? cloneContentReplacementState(parentContext.contentReplacementState)
    : undefined)
```

**关键注释解读**（源码第 388-403 行）：

> Clone by default (not fresh): cache-sharing forks process parent messages containing parent tool_use_ids. A fresh state would see them as unseen and make divergent replacement decisions → wire prefix differs → cache miss. A clone makes identical decisions → cache hit.

**翻译**：新建空状态时，子代理看到父代理的 `tool_use_ids` 为"未知"，做出不同替换决策 → 消息前缀变化 → **缓存失效**。克隆后决策一致 → **缓存命中**。

**3. 五个新建空集合——子代理的"私人笔记本"**

```typescript
nestedMemoryAttachmentTriggers: new Set<string>(),
loadedNestedMemoryPaths: new Set<string>(),
dynamicSkillDirTriggers: new Set<string>(),
discoveredSkillNames: new Set<string>(),
toolDecisions: undefined,
```

这五个字段就像子代理随身携带的"私人笔记本"，用来记录工作过程中的临时信息。为什么子代理要新建空集合而不是继承父代理的？因为每个子代理是独立工作者，有自己的任务轨迹。

**通俗类比**：

| 字段 | 生活类比 | 实际用途 |
|------|----------|----------|
| `nestedMemoryAttachmentTriggers` | **待处理清单** | 当你读一个文件（比如 `Button.tsx`），顺便记下"可能要检查有没有配套的说明书（CLAUDE.md）" |
| `loadedNestedMemoryPaths` | **已读名单** | 防止重复读同一份说明书。就像你看过一本书后记在"已读书单"里，下次不会再看一遍 |
| `dynamicSkillDirTriggers` | **新技能发现清单** | 你在工作中发现了一个新技能目录，记下来等着去加载这些技能 |
| `discoveredSkillNames` | **技能来源统计** | 统计哪些技能是"自己发现的"而不是"别人告诉你的"，用于数据分析 |
| `toolDecisions` | **审批记录本** | 每次工具调用需要权限审批时，记下审批结果（批准/拒绝、审批来源、时间） |

**举个具体的例子**：

假设子代理被派去研究一个 React 组件：
```
1. 子代理读取 src/components/Button.tsx
   → nestedMemoryAttachmentTriggers 记录 "src/components/Button.tsx"
   → 系统顺便检查是否存在 src/components/CLAUDE.md

2. 如果发现并加载了 src/components/CLAUDE.md
   → loadedNestedMemoryPaths 记录 "src/components/CLAUDE.md"
   → 下次读取其他组件时，不会再重复加载这份说明书

3. 如果子代理在 .claude/skills/ 发现了新技能文件
   → dynamicSkillDirTriggers 记录这个目录
   → 系统会加载这些新技能供子代理使用

4. 子代理调用某个 skill
   → discoveredSkillNames 记录这个 skill 名称
   → 用于统计分析"这个 skill 是通过自动发现得到的"

5. 子代理要执行 Bash 命令，需要权限审批
   → toolDecisions 记录 {toolUseID: "批准, 来源:hook, 时间:..."}
   → 审批结果用于日志和调试
```

**为什么子代理要新建空集合而不是继承父代理的？**

就像你派一个新员工去独立完成任务：
- 给他新的笔记本（空集合），让他自己记录工作轨迹
- 不要把你的笔记本给他（继承父集合），否则他会看到你之前的记录，可能混淆他的工作
- 他完成后，笔记本可以丢弃（临时状态清理）

#### AbortController 分层控制

```typescript
const abortController =
  overrides?.abortController ??                       // 1. 显式覆盖
  (overrides?.shareAbortController                    // 2. 显式共享
    ? parentContext.abortController
    : createChildAbortController(parentContext.abortController))  // 3. 默认子控制器
```

| 优先级 | 条件 | 结果 | 用途 |
|--------|------|------|------|
| 1 | `overrides.abortController` | 使用显式提供的控制器 | 自定义场景 |
| 2 | `shareAbortController: true` | 共享父级控制器 | **交互式子代理** |
| 3 | 默认 | 新建子控制器 | **后台代理** |

**`createChildAbortController` 的魔法**：
- 子控制器链接到父控制器
- 父级 `abort()` → 子级自动 `abort()`
- 但子级单独 `abort()` → 不影响父级

**场景对比**：
```
# 交互式子代理（共享）
shareAbortController: true
→ 用户 Ctrl+C → 子代理和父代理一起停止

# 后台代理（独立）
默认 createChildAbortController
→ 父代理取消 → 后台代理随之停止
→ 后台代理单独取消 → 父代理不受影响
```

#### 权限上下文封装

```typescript
const getAppState = overrides?.shareAbortController
  ? parentContext.getAppState
  : () => {
      const state = parentContext.getAppState()
      return {
        ...state,
        toolPermissionContext: {
          ...state.toolPermissionContext,
          shouldAvoidPermissionPrompts: true,  // 强制避免权限弹窗
        },
      }
    }
```

**核心逻辑**：后台代理无法显示权限弹窗 → 设置 `shouldAvoidPermissionPrompts: true` → 触发权限请求冒泡到 Leader（通过 Mailbox）。

#### Mutation Callbacks 阻断

| 回调 | 默认值 | 共享条件 | 用途 |
|------|--------|----------|------|
| `setAppState` | `() => {}` | `shareSetAppState: true` | 更新全局状态 |
| `setResponseLength` | `() => {}` | `shareSetResponseLength: true` | 更新响应长度 UI |
| `setInProgressToolUseIDs` | `() => {}` | 无 | 工具调用追踪 |
| `updateFileHistoryState` | `() => {}` | 无 | 文件历史记录 |

**特殊例外**：
```typescript
// 任务注册必须穿透到根存储
setAppStateForTasks:
  parentContext.setAppStateForTasks ?? parentContext.setAppState
```

后台代理的权限拒绝计数需要本地追踪（`localDenialTracking`），否则重试时计数器不会累积。

#### UI 回调阻断

```typescript
addNotification: undefined,
setToolJSX: undefined,
setStreamMode: undefined,
setSDKStatus: undefined,
openMessageSelector: undefined,
```

子代理无法控制父代理的 UI——全部置为 `undefined`。

#### QueryTracking 链路追踪

```typescript
queryTracking: {
  chainId: randomUUID(),       // 新链 ID
  depth: (parentContext.queryTracking?.depth ?? -1) + 1,  // 深度递增
}
```

用于 analytics 追踪代理调用链深度，方便调试和性能分析。

#### 隔离策略总结表

| 状态类型 | 默认行为 | 共享选项 | 设计意图 |
|----------|----------|----------|----------|
| `readFileState` | 克隆 | 无 | 提示缓存命中 + 状态隔离 |
| `contentReplacementState` | 克隆 | `overrides.contentReplacementState` | 提示缓存命中 |
| `abortController` | 子控制器 | `shareAbortController` | 父取消→子取消，子取消→父不受影响 |
| `getAppState` | 封装（避免弹窗） | `shareAbortController` 或显式覆盖 | 权限冒泡 |
| `setAppState` | no-op | `shareSetAppState` | 防止后台代理污染状态 |
| `setResponseLength` | no-op | `shareSetResponseLength` | 响应长度不计入父代理 |
| UI 回调 | undefined | 无 | 子代理无法控制 UI |

#### 使用示例

```typescript
// 后台研究代理（完全隔离）
const ctx = createSubagentContext(parentContext)

// 交互式子代理（部分共享）
const ctx = createSubagentContext(parentContext, {
  shareSetAppState: true,       // 能更新全局状态
  shareAbortController: true,   // 随父代理一起取消
  shareSetResponseLength: true, // 响应长度计入父代理
})

// 自定义覆盖
const ctx = createSubagentContext(parentContext, {
  options: customOptions,       // 使用自定义工具集
  agentId: newAgentId,          // 新代理 ID
  messages: initialMessages,    // 初始消息
})
```

### 2.4 Mailbox 消息传递

```typescript
export class Mailbox {
  private queue: Message[] = []
  private waiters: Waiter[] = []

  send(msg: Message): void {
    const idx = this.waiters.findIndex(w => w.fn(msg))
    if (idx !== -1) {
      const waiter = this.waiters.splice(idx, 1)[0]
      waiter.resolve(msg)
      return
    }
    this.queue.push(msg)
  }

  receive(fn: (msg: Message) => boolean): Promise<Message> {
    const idx = this.queue.findIndex(fn)
    if (idx !== -1) {
      return Promise.resolve(this.queue.splice(idx, 1)[0])
    }
    return new Promise(resolve => {
      this.waiters.push({ fn, resolve })
    })
  }
}
```

### 2.5 Swarm 后端实现

系统支持三种后端类型：

| 后端类型 | 执行环境 | 隔离机制 | 适用场景 |
|---------|---------|---------|---------|
| `tmux` | tmux pane | 进程级 | 生产环境，可视化布局 |
| `iterm2` | iTerm2 split pane | 进程级 | macOS iTerm2 用户 |
| `in-process` | 同一 Node.js 进程 | AsyncLocalStorage | 轻量级并发 |

### 2.6 权限同步机制

权限同步是 Swarm 模式的关键安全机制：

**请求流程**:
1. Worker 遇到权限提示 → 创建 `SwarmPermissionRequest`
2. 通过 `sendPermissionRequestViaMailbox()` 发送给 Leader
3. Leader 显示权限对话框，用户批准/拒绝
4. 通过 `sendPermissionResponseViaMailbox()` 返回结果
5. Worker 轮询响应，继续执行

---

## 三、关键代码解读

### 3.1 Fork 子代理上下文继承

```typescript
export function buildForkedMessages(directive: string, assistantMessage: AssistantMessage) {
  // 克隆完整的 assistant 消息（包含所有 tool_use blocks）
  // 构建占位符 tool_results（相同内容，保证缓存命中）
  // 返回: [assistant(all_tool_uses), user(placeholder_results..., directive)]
}
```

**设计亮点**: 所有 Fork 子代理使用相同的占位符文本，只有最后的 directive 不同，最大化提示缓存命中率。

### 3.2 InProcess 队友启动

```typescript
export async function spawnInProcessTeammate(config, context) {
  // 创建独立的 AbortController
  const abortController = createAbortController()

  // 创建 TeammateContext（AsyncLocalStorage 用）
  const teammateContext = createTeammateContext({...})

  // 注册到 AppState.tasks
  registerTask(taskState, setAppState)

  return { success: true, agentId, taskId, abortController, teammateContext }
}
```

---

## 四、设计亮点

### 4.1 提示缓存共享

Fork 子代理通过以下机制实现缓存命中：
1. 继承父代理的 `renderedSystemPrompt`（字节精确）
2. 使用 `useExactTools` 继承父代理的工具列表
3. 占位符 `tool_result` 内容完全相同
4. 只有最后的 directive 文本不同

### 4.2 分层权限管理

```
┌─────────────────────────────────────────┐
│ Leader Permission Context               │
│ (Full permissions, can show prompts)    │
└────────────────┬────────────────────────┘
                 │ delegation
                 ▼
┌─────────────────────────────────────────┐
│ Worker Permission Context               │
│ (Restricted tools, shouldAvoidPrompts)  │
│ → Bubbles to leader for approvals       │
└─────────────────────────────────────────┘
```

### 4.3 生命周期管理

- **Sync Agent**: 共享父级 `abortController`，随父级取消
- **Async Agent**: 独立 `abortController`，在 `AppState.tasks` 中追踪
- **Teammate**: 独立生命周期，通过 `shutdownRequested` 标志优雅退出

### 4.4 Worktree 隔离

```typescript
if (effectiveIsolation === 'worktree') {
  const slug = `agent-${earlyAgentId.slice(0, 8)}`;
  worktreeInfo = await createAgentWorktree(slug);
}
```

子代理在独立的 git worktree 中执行，修改不影响主工作目录。

---

## 五、文件路径索引

| 模块 | 文件路径 |
|------|---------|
| **Coordinator 模式** | `src/coordinator/coordinatorMode.ts` |
| **AgentTool 主入口** | `src/tools/AgentTool/AgentTool.tsx` |
| **runAgent 执行器** | `src/tools/AgentTool/runAgent.ts` |
| **Fork 子代理** | `src/tools/AgentTool/forkSubagent.ts` |
| **createSubagentContext** | `src/utils/forkedAgent.ts` |
| **Mailbox 消息队列** | `src/utils/mailbox.ts` |
| **Backend 类型定义** | `src/utils/swarm/backends/types.ts` |
| **TmuxBackend** | `src/utils/swarm/backends/TmuxBackend.ts` |
| **InProcessBackend** | `src/utils/swarm/backends/InProcessBackend.ts` |
| **权限同步** | `src/utils/swarm/permissionSync.ts` |
| **Team 帮助函数** | `src/utils/swarm/teamHelpers.ts` |
| **TeammateContext** | `src/utils/teammateContext.ts` |

---

该多代理协调系统展现了企业级 Agent 编排的最佳实践，特别是在提示缓存优化、权限分层管理、跨进程通信等方面的设计值得深入研究。