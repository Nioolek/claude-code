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

```typescript
export function createSubagentContext(
  parentContext: ToolUseContext,
  overrides?: SubagentContextOverrides,
): ToolUseContext {
  return {
    // Mutable state - cloned by default
    readFileState: cloneFileStateCache(parentContext.readFileState),
    nestedMemoryAttachmentTriggers: new Set<string>(),

    // AbortController
    abortController: overrides?.abortController ??
      createChildAbortController(parentContext.abortController),

    // AppState access - wrapped to set shouldAvoidPermissionPrompts
    getAppState: overrides?.getAppState ?? ...,

    // Mutation callbacks - no-op by default
    setAppState: overrides?.shareSetAppState ? parentContext.setAppState : () => {},
  }
}
```

**隔离策略**:

| 状态类型 | 默认行为 | 可选共享 |
|---------|---------|---------|
| readFileState | 克隆 | - |
| abortController | 新建子控制器 | shareAbortController |
| setAppState | no-op | shareSetAppState |

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