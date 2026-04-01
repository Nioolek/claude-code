# Claude Code Hook 系统深度分析报告

## 1. 概述

Claude Code 的 Hook 系统是一个强大的扩展机制，允许用户在 Claude 生命周期的关键节点注入自定义逻辑。支持多种事件类型、多种执行方式（Shell命令、LLM提示、HTTP请求、Agent验证）。

## 2. Hook事件类型

### 2.1 完整事件列表

```typescript
export const HOOK_EVENTS = [
  'PreToolUse',          // 工具执行前
  'PostToolUse',         // 工具执行后
  'PostToolUseFailure',  // 工具执行失败后
  'Notification',        // 通知发送时
  'UserPromptSubmit',    // 用户提交提示时
  'SessionStart',        // 会话开始时
  'SessionEnd',          // 会话结束时
  'Stop',                // Claude响应结束时
  'StopFailure',         // API错误导致响应结束时
  'SubagentStart',       // 子Agent启动时
  'SubagentStop',        // 子Agent结束时
  'PreCompact',          // 对话压缩前
  'PostCompact',         // 对话压缩后
  'PermissionRequest',   // 权限对话框显示时
  'PermissionDenied',    // 分类器拒绝工具调用时
  'Setup',               // 仓库初始化时
  'TeammateIdle',        // Teammate即将空闲时
  'TaskCreated',         // 任务创建时
  'TaskCompleted',       // 任务完成时
  'Elicitation',         // MCP服务器请求用户输入时
  'ConfigChange',        // 配置文件变更时
  'FileChanged',         // 监视的文件变更时
] as const
```

### 2.2 事件分类

| 类别 | 事件 | 说明 |
|------|------|------|
| **工具生命周期** | PreToolUse, PostToolUse, PostToolUseFailure | 拦截/修改/观察工具调用 |
| **会话生命周期** | SessionStart, SessionEnd, Setup | 初始化/清理 |
| **响应控制** | Stop, StopFailure, SubagentStop | 控制响应结束 |
| **权限控制** | PermissionRequest, PermissionDenied | 自定义权限决策 |
| **内存管理** | PreCompact, PostCompact | 压缩控制 |

## 3. Hook类型实现

### 3.1 类型定义

```typescript
// Bash命令Hook
type BashCommandHook = {
  type: 'command'
  command: string              // Shell命令
  if?: string                  // 条件过滤
  shell?: 'bash' | 'powershell'
  timeout?: number
  async?: boolean              // 后台运行
  asyncRewake?: boolean        // 后台运行，exit 2时唤醒
}

// LLM提示Hook
type PromptHook = {
  type: 'prompt'
  prompt: string               // 发送给LLM的提示
  model?: string
  timeout?: number
}

// Agent验证Hook
type AgentHook = {
  type: 'agent'
  prompt: string               // 验证提示
  model?: string
}

// HTTP Hook
type HttpHook = {
  type: 'http'
  url: string                  // POST目标URL
  headers?: Record<string, string>
  allowedEnvVars?: string[]
}
```

## 4. Hook执行流程

### 4.1 主执行函数

```typescript
async function* executeHooks({
  hookInput, toolUseID, matchQuery, signal, ...
}): AsyncGenerator<AggregatedHookResult> {
  // 1. 全局检查（信任、禁用）
  if (shouldDisableAllHooks()) return

  // 2. 获取匹配的Hooks
  const matchingHooks = await getMatchingHooks(appState, hookEvent, hookInput)

  // 3. 并行执行所有Hooks
  const hookPromises = matchingHooks.map(async function* ({hook, ...}) {
    if (hook.type === 'command') yield await execCommandHook(...)
    if (hook.type === 'prompt') yield await execPromptHook(...)
    if (hook.type === 'agent') yield await execAgentHook(...)
    if (hook.type === 'http') yield await execHttpHook(...)
  })

  // 4. 聚合结果
  for await (const result of all(hookPromises)) {
    yield result
  }
}
```

## 5. Exit Code语义

### 5.1 标准Exit Code

| Exit Code | 含义 | 行为 |
|-----------|------|------|
| **0** | 成功 | 继续执行 |
| **1** | 非阻塞错误 | stderr显示给用户，继续执行 |
| **2** | 阻塞错误 | stderr显示给模型，阻止当前操作 |

### 5.2 JSON输出模式

```typescript
type HookJSONOutput = {
  continue?: boolean        // false时阻止继续
  suppressOutput?: boolean  // 隐藏stdout
  stopReason?: string       // 阻止原因
  decision?: 'approve' | 'block'  // 权限决策
  systemMessage?: string    // 警告消息
  async?: true              // 声明异步模式
}
```

## 6. 异步Hook处理

Hook可以通过输出 `{"async": true}` 声明异步模式：

```typescript
// 配置声明式异步
type BashCommandHook = {
  type: 'command'
  command: 'long-running-script.sh'
  async: true           // 后台运行，不阻塞
  asyncRewake: true     // 后台运行，exit 2时唤醒模型
}
```

## 7. 安全机制

### 7.1 工作区信任

交互模式需要明确信任工作区后才执行用户配置的Hooks。

### 7.2 URL白名单（HTTP Hooks）

```typescript
function getHttpHookPolicy() {
  return {
    allowedUrls: settings.allowedHttpHookUrls,
    allowedEnvVars: settings.httpHookAllowedEnvVars,
  }
}
```

### 7.3 SSRF防护

HTTP Hook使用 `ssrfGuardedLookup` 阻止私有IP范围的请求。

## 8. 文件路径索引

| 文件 | 用途 |
|------|------|
| `src/schemas/hooks.ts` | Hook Zod schema定义 |
| `src/types/hooks.ts` | TypeScript类型定义 |
| `src/utils/hooks.ts` | 主执行逻辑 |
| `src/utils/hooks/execPromptHook.ts` | Prompt Hook执行器 |
| `src/utils/hooks/execAgentHook.ts` | Agent Hook执行器 |
| `src/utils/hooks/execHttpHook.ts` | HTTP Hook执行器 |
| `src/utils/hooks/AsyncHookRegistry.ts` | 异步Hook管理 |
| `src/utils/hooks/sessionHooks.ts` | 会话级Hook管理 |