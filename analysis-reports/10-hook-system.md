# Claude Code Hook 系统深度分析报告

## 模块概述（通俗开场）

### 一句话角色定位

**Hook 系统是 Claude Code 的"可编程触发器"**——它像智能家居的自动化系统，在特定事件发生时自动执行预设的操作。

### 核心职责

想象智能家居的场景：当有人敲门时自动开灯、当温度过高时自动开空调。Hook 系统就是这样一套自动化规则：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code 自动化系统                          │
├─────────────────────────────────────────────────────────────────┤
│  1. 【事件监听】    监听 28 种生命周期事件                           │
│  2. 【规则匹配】    根据工具名、条件过滤匹配 Hook                     │
│  3. 【执行分发】    分发到 Shell/Prompt/HTTP/Agent 四种执行器         │
│  4. 【结果处理】    解析输出，决定继续/阻断/修改行为                   │
│  5. 【异步管理】    支持后台运行和超时唤醒                            │
└─────────────────────────────────────────────────────────────────┘
```

### 与其他模块的关系图

```
                    ┌──────────────┐
                    │ QueryEngine  │  ← 触发 PreToolUse/PostToolUse
                    │  (查询引擎)   │
                    └──────┬───────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │                    Hook System                       │
    │                   (Hook 系统)                         │
    ├─────────────────────────────────────────────────────┤
    │                                                      │
    │   事件触发          Hook匹配              执行器       │
    │  ┌─────────┐     ┌─────────┐     ┌─────────────────┐ │
    │  │PreToolUse│ ──→ │ 匹配器   │ ──→ │ execCommandHook │ │
    │  │PostToolUse│    │getMatchingHooks │execPromptHook │ │
    │  │SessionStart│   └─────────┘     │ execHttpHook    │ │
    │  │Stop      │                     │ execAgentHook   │ │
    │  │...       │                     └─────────────────┘ │
    │  └─────────┘                                          │
    │         │                                            │
    │         ▼                                            │
    │  ┌─────────────────┐                                 │
    │  │ AsyncHookRegistry│ ← 异步 Hook 管理                │
    │  └─────────────────┘                                 │
    └─────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │  权限系统  │     │ 消息流   │     │ 设置管理  │
    │(Permission)│    │(Messages) │    │(Settings) │
    └──────────┘     └──────────┘     └──────────┘
```

---

## 核心概念（生活化类比）

### 1. Hook Event（Hook 事件）—— 触发器触发时机

Hook 系统定义了 28 种事件，就像智能家居的各种传感器：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hook 事件分类                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  【工具生命周期】                    【会话生命周期】              │
│  ├── PreToolUse      (工具执行前)    ├── SessionStart  (会话开始) │
│  ├── PostToolUse     (工具执行后)    ├── SessionEnd    (会话结束) │
│  └── PostToolUseFailure (执行失败)   └── Setup         (仓库初始化)│
│                                                                  │
│  【响应控制】                        【子Agent控制】               │
│  ├── Stop            (响应结束)      ├── SubagentStart (子Agent启动)│
│  └── StopFailure     (API错误)       └── SubagentStop  (子Agent结束)│
│                                                                  │
│  【权限控制】                        【内存管理】                  │
│  ├── PermissionRequest (权限询问)    ├── PreCompact    (压缩前)    │
│  └── PermissionDenied  (权限拒绝)    └── PostCompact   (压缩后)    │
│                                                                  │
│  【用户交互】                        【任务管理】                  │
│  ├── UserPromptSubmit (用户提交)     ├── TaskCreated   (任务创建)  │
│  └── Elicitation     (MCP请求输入)   └── TaskCompleted (任务完成)  │
│                                                                  │
│  【其他】                                                        │
│  ├── Notification    (通知发送)                                   │
│  ├── TeammateIdle    (Teammate空闲)                              │
│  ├── ConfigChange    (配置变更)                                   │
│  └── FileChanged     (文件变更)                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**生活类比**：每个事件就像智能家居的一个触发条件：
- `PreToolUse` = 门铃响（有人来访）
- `PostToolUse` = 门关上（客人离开）
- `SessionStart` = 早上起床（启动日常流程）
- `Stop` = 晚上睡觉（检查门窗）

### 2. Hook Type（Hook 类型）—— 执行器类型

Hook 有 5 种执行方式，对应不同的处理逻辑：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hook 执行器类型                                 │
├──────────────┬──────────────┬────────────────────────────────────┤
│     类型      │   生活类比    │              说明                  │
├──────────────┼──────────────┼────────────────────────────────────┤
│   command    │  定时开关     │ 执行 Shell 命令，最常用            │
│   prompt     │  AI助手      │ 发送给 LLM 判断条件                │
│   agent      │  智能管家     │ 多轮工具调用的复杂判断             │
│   http       │  远程控制     │ POST 到远程服务器                  │
│   callback   │  内置脚本     │ TypeScript 回调函数（内部使用）    │
└──────────────┴──────────────┴────────────────────────────────────┘
```

**类型定义**：

```typescript
// Shell 命令 Hook（最常用）
type BashCommandHook = {
  type: 'command'
  command: string              // 要执行的命令
  if?: string                  // 条件过滤（如 "tool_name == 'Bash'"）
  shell?: 'bash' | 'powershell'
  timeout?: number             // 超时秒数
  async?: boolean              // 后台运行
  asyncRewake?: boolean        // 后台运行，exit 2 时唤醒模型
}

// LLM Prompt Hook（AI 判断）
type PromptHook = {
  type: 'prompt'
  prompt: string               // 发送给 LLM 的提示
  model?: string               // 使用的模型
  timeout?: number
}

// Agent Hook（多轮工具调用）
type AgentHook = {
  type: 'agent'
  prompt: string               // 验证提示
  model?: string
}

// HTTP Hook（远程调用）
type HttpHook = {
  type: 'http'
  url: string                  // POST 目标 URL
  headers?: Record<string, string>
  allowedEnvVars?: string[]    // 允许注入的环境变量
}

// Callback Hook（内部使用）
type HookCallback = {
  type: 'callback'
  callback: (input, toolUseID, signal) => Promise<HookJSONOutput>
  timeout?: number
}
```

### 3. Exit Code（退出码）—— 命令执行结果语义

Shell 命令 Hook 的退出码有特殊语义：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Exit Code 语义                                 │
├──────────────┬──────────────┬────────────────────────────────────┤
│  Exit Code   │    含义       │              行为                  │
├──────────────┼──────────────┼────────────────────────────────────┤
│      0       │    成功       │ 继续执行，stdout 作为附加上下文    │
│      1       │   非阻塞错误   │ stderr 显示给用户，继续执行        │
│      2       │   阻塞错误    │ stderr 显示给模型，阻止当前操作     │
│   其他      │   非阻塞错误   │ 同 exit 1                         │
└──────────────┴──────────────┴────────────────────────────────────┘
```

**生活类比**：
- `exit 0` = 门卫点头放行："没问题，请进"
- `exit 1` = 门卫提醒："有点小问题，但你坚持的话也行"
- `exit 2` = 门卫拦住："这绝对不行，必须请示上级"

### 4. HookJSONOutput（JSON 输出）—— 结构化输出

Hook 可以返回 JSON 对象来精确控制行为：

```typescript
type SyncHookJSONOutput = {
  continue?: boolean        // false 时阻止继续
  suppressOutput?: boolean  // 隐藏 stdout
  stopReason?: string       // 阻止原因

  // 权限决策
  decision?: 'approve' | 'block'
  reason?: string

  // 系统消息
  systemMessage?: string

  // 事件特定输出
  hookSpecificOutput?: {
    hookEventName: 'PreToolUse' | 'PostToolUse' | ...
    // PreToolUse 特有
    permissionDecision?: 'allow' | 'deny' | 'ask'
    updatedInput?: Record<string, unknown>  // 修改工具输入
    additionalContext?: string
    // ...
  }
}

// 异步声明
type AsyncHookJSONOutput = {
  async: true
  asyncTimeout?: number  // 异步等待超时
}
```

### 5. AsyncHookRegistry（异步 Hook 注册表）—— 后台任务管理

当 Hook 声明异步模式时，它被注册到异步注册表中：

```
┌─────────────────────────────────────────────────────────────────┐
│                    异步 Hook 生命周期                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Hook 返回 {"async": true}                                   │
│         ↓                                                        │
│  2. 注册到 AsyncHookRegistry                                     │
│         ↓                                                        │
│  3. Hook 在后台继续执行                                          │
│         ↓                                                        │
│  4a. 正常完成 → 记录日志，清理注册                               │
│  4b. asyncRewake + exit 2 → 唤醒模型，注入阻塞消息               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 完整工作流程（数据流图）

### Hook 执行完整流水线

当触发一个 Hook 事件时，系统执行以下流程：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Hook 执行完整流水线                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: hookEvent, hookInput, matchQuery, signal                      │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第一阶段：前置检查                                                   │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [1] 检查全局禁用                                                    │
│       shouldDisableAllHooksIncludingManaged() → 是则退出            │
│                                                                      │
│  [2] 检查 CLAUDE_CODE_SIMPLE 模式                                   │
│       简化模式下跳过 Hook                                            │
│                                                                      │
│  [3] 检查工作区信任                                                  │
│       shouldSkipHookDueToTrust() → 未信任则退出                     │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第二阶段：Hook 匹配                                                 │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [4] 获取所有配置的 Hook                                             │
│       getHooksConfigFromSnapshot()                                  │
│       ↓                                                             │
│       合并用户设置、项目设置、插件 Hook                               │
│                                                                      │
│  [5] 过滤匹配的 Hook                                                 │
│       getMatchingHooks(appState, hookEvent, hookInput)              │
│       ↓                                                             │
│       检查 matcher 条件                                              │
│       检查 if 表达式                                                 │
│       匹配工具名称                                                   │
│                                                                      │
│  [6] 无匹配 Hook → 退出                                             │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第三阶段：并行执行                                                   │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [7] 快速路径：仅内部回调                                            │
│       如果所有 Hook 都是 callback 类型：                             │
│       → 直接调用，跳过 JSON 序列化                                   │
│       → 跳过进度消息和超时处理                                       │
│       → 性能优化：~70% 时间节省                                      │
│                                                                      │
│  [8] 常规路径：准备执行                                              │
│       jsonStringify(hookInput) → 共享输入 JSON                      │
│       emitHookStarted() → 发送开始事件                              │
│       yield progress message → 显示进度                             │
│                                                                      │
│  [9] 并行执行所有 Hook                                               │
│       ┌─────────────────────────────────────────────┐               │
│       │ for each hook:                               │               │
│       │   ├── callback → executeHookCallback()      │               │
│       │   ├── command  → execCommandHook()          │               │
│       │   ├── prompt   → execPromptHook()           │               │
│       │   ├── agent    → execAgentHook()            │               │
│       │   └── http     → execHttpHook()             │               │
│       └─────────────────────────────────────────────┘               │
│       每个执行器有独立的超时和 AbortSignal                           │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第四阶段：结果处理                                                   │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [10] 解析输出                                                       │
│       parseHookOutput(stdout) → {json} | {plainText}               │
│       ↓                                                             │
│       JSON 模式：validateHookJson() 验证 schema                     │
│       纯文本模式：作为附加上下文                                     │
│                                                                      │
│  [11] 处理异步声明                                                   │
│       如果 json.async === true:                                     │
│       → executeInBackground() → 注册到 AsyncHookRegistry           │
│       → 返回，不等待完成                                            │
│                                                                      │
│  [12] 构建结果对象                                                   │
│       processHookJSONOutput() → HookResult                          │
│       ↓                                                             │
│       提取 permissionBehavior (allow/deny/ask)                      │
│       提取 updatedInput (修改工具输入)                              │
│       提取 additionalContext (附加上下文)                           │
│       提取 preventContinuation (阻止继续)                           │
│                                                                      │
│  [13] 聚合结果                                                       │
│       合并所有 Hook 的结果                                           │
│       任何一个 preventContinuation=true → 阻断                      │
│                                                                      │
│  输出: AsyncGenerator<AggregatedHookResult>                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 四种执行器的执行流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Command Hook 执行流程                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  execCommandHook(hook, jsonInput, signal)                           │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 1. 准备环境变量                           │                       │
│  │    CLAUDE_PROJECT_DIR                    │                       │
│  │    CLAUDE_PLUGIN_ROOT (插件Hook)          │                       │
│  │    CLAUDE_ENV_FILE (会话环境)             │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 2. 变量替换                               │                       │
│  │    ${CLAUDE_PLUGIN_ROOT} → 插件目录       │                       │
│  │    ${user_config.X} → 用户配置值          │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 3. Shell 选择                             │                       │
│  │    hook.shell === 'powershell' → pwsh    │                       │
│  │    否则 → bash (Windows 上用 Git Bash)   │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 4. 执行命令                               │                       │
│  │    spawn(shell, [command], {env, signal})│                       │
│  │    捕获 stdout/stderr                    │                       │
│  │    等待 exit code                        │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  返回 {stdout, stderr, exitCode}                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Prompt Hook 执行流程                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  execPromptHook(hook, jsonInput, signal, toolUseContext)            │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 1. 构建提示                               │                       │
│  │    prompt + $ARGUMENTS → jsonInput       │                       │
│  │    添加 JSON schema 约束                  │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 2. 调用 LLM                               │                       │
│  │    queryModelWithoutStreaming({          │                       │
│  │      model: hook.model || 'haiku',       │                       │
│  │      outputFormat: {json_schema},        │                       │
│  │    })                                    │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 3. 解析响应                               │                       │
│  │    期望: {ok: true} 或 {ok: false, reason}│                       │
│  │    ok=true → 成功                        │                       │
│  │    ok=false → 阻塞，显示 reason          │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  返回 HookResult {outcome, blockingError?}                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Agent Hook 执行流程                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  execAgentHook(hook, jsonInput, signal, toolUseContext)             │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 1. 创建独立 Agent                         │                       │
│  │    hook-agent-{uuid}                     │                       │
│  │    mode: 'dontAsk'                       │                       │
│  │    可用工具: 过滤掉 AgentTool 等          │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 2. 多轮查询                               │                       │
│  │    for await (message of query()) {      │                       │
│  │      // Agent 可以使用工具读取文件        │                       │
│  │      // 最多 50 轮                        │                       │
│  │    }                                     │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 3. 结构化输出                             │                       │
│  │    Agent 必须调用 StructuredOutputTool   │                       │
│  │    返回 {ok: true/false, reason?}        │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  返回 HookResult {outcome, blockingError?}                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    HTTP Hook 执行流程                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  execHttpHook(hook, jsonInput, signal)                              │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 1. URL 白名单检查                         │                       │
│  │    allowedHttpHookUrls 配置               │                       │
│  │    不匹配 → 拒绝                          │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 2. 构建请求                               │                       │
│  │    POST {url}                            │                       │
│  │    headers: 插入环境变量                  │                       │
│  │    body: jsonInput                       │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 3. SSRF 防护                              │                       │
│  │    ssrfGuardedLookup() 检查 IP           │                       │
│  │    阻止私有 IP 范围                       │                       │
│  │    (沙箱代理或环境代理时跳过)             │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────┐                       │
│  │ 4. 发送请求                               │                       │
│  │    axios.post(url, jsonInput, options)   │                       │
│  │    代理: 沙箱代理 或 环境代理             │                       │
│  └──────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  返回 {ok, statusCode, body}                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 关键代码解读（逐行注释）

### 1. 核心 executeHooks 函数

这是 Hook 系统的"大脑"，处理所有 Hook 事件：

```typescript
// 文件: src/utils/hooks.ts
// 行号: 1952-2250

async function* executeHooks({
  hookInput,        // Hook 输入数据（包含事件名、工具信息等）
  toolUseID,        // 工具调用 ID
  matchQuery,       // 匹配查询（如工具名）
  signal,           // AbortSignal 用于取消
  timeoutMs = TOOL_HOOK_EXECUTION_TIMEOUT_MS,  // 默认超时 10 分钟
  toolUseContext,   // 工具执行上下文
  messages,         // 对话历史（用于 prompt/function hook）
  forceSyncExecution,
  requestPrompt,
}: {...}): AsyncGenerator<AggregatedHookResult> {

  // ===== 第一阶段：前置检查 =====

  // [1] 检查全局禁用开关
  // 当 shouldAllowManagedHooksOnly() 且用户未配置任何 Hook 时返回 true
  if (shouldDisableAllHooksIncludingManaged()) {
    return
  }

  // [2] 检查简化模式
  // CLAUDE_CODE_SIMPLE=1 时跳过所有 Hook（用于调试）
  if (isEnvTruthy(process.env.CLAUDE_CODE_SIMPLE)) {
    return
  }

  const hookEvent = hookInput.hook_event_name
  const hookName = matchQuery ? `${hookEvent}:${matchQuery}` : hookEvent

  // [3] 检查工作区信任
  // 安全关键：所有 Hook 都需要用户信任工作区
  // 防止恶意仓库通过 Hook 执行任意命令
  if (shouldSkipHookDueToTrust()) {
    logForDebugging(`Skipping ${hookName} hook - workspace trust not accepted`)
    return
  }

  // ===== 第二阶段：Hook 匹配 =====

  const appState = toolUseContext ? toolUseContext.getAppState() : undefined
  const sessionId = toolUseContext?.agentId ?? getSessionId()

  // [4] 获取匹配当前事件的所有 Hook
  const matchingHooks = await getMatchingHooks(
    appState,
    sessionId,
    hookEvent,
    hookInput,
    toolUseContext?.options?.tools,
  )
  if (matchingHooks.length === 0) {
    return
  }

  // [5] 快速路径优化：仅内部回调
  // 如果所有 Hook 都是 callback 类型（内部使用），跳过重量级处理
  const userHooks = matchingHooks.filter(h => !isInternalHook(h))
  if (userHooks.length > 0) {
    // 记录分析事件
    logEvent('tengu_run_hook', { hookName, numCommands: userHooks.length })
  } else {
    // 快速路径：直接调用回调，跳过 JSON 序列化
    // 性能提升：6.01µs → ~1.8µs (-70%)
    for (const [i, { hook }] of matchingHooks.entries()) {
      if (hook.type === 'callback') {
        await hook.callback(hookInput, toolUseID, signal, i, context)
      }
    }
    return
  }

  // ===== 第三阶段：并行执行 =====

  // [6] 发送进度消息（UI 显示）
  for (const { hook } of matchingHooks) {
    yield {
      message: {
        type: 'progress',
        data: {
          type: 'hook_progress',
          hookEvent,
          hookName,
          command: getHookDisplayText(hook),
        },
      },
    }
  }

  // [7] 延迟 JSON 序列化（性能优化）
  // hookInput 只序列化一次，所有 Hook 共享
  let jsonInputResult: { ok: true; value: string } | { ok: false; error: unknown } | undefined
  function getJsonInput() {
    if (jsonInputResult !== undefined) return jsonInputResult
    try {
      return (jsonInputResult = { ok: true, value: jsonStringify(hookInput) })
    } catch (error) {
      return (jsonInputResult = { ok: false, error })
    }
  }

  // [8] 并行执行所有 Hook
  const hookPromises = matchingHooks.map(async function* (
    { hook, pluginRoot, pluginId, skillRoot },
    hookIndex,
  ): AsyncGenerator<HookResult> {

    // --- Callback Hook ---
    if (hook.type === 'callback') {
      const { signal: abortSignal, cleanup } = createCombinedAbortSignal(
        signal,
        { timeoutMs: hook.timeout ? hook.timeout * 1000 : timeoutMs },
      )
      yield executeHookCallback({...}).finally(cleanup)
      return
    }

    // --- Function Hook ---
    if (hook.type === 'function') {
      yield executeFunctionHook({...})
      return
    }

    // --- Command/Prompt/Agent/HTTP Hook ---
    const jsonInputRes = getJsonInput()
    if (!jsonInputRes.ok) {
      yield { outcome: 'non_blocking_error', ... }
      return
    }
    const jsonInput = jsonInputRes.value

    // 执行不同类型的 Hook
    if (hook.type === 'prompt') {
      const result = await execPromptHook(hook, hookName, hookEvent, jsonInput, abortSignal, toolUseContext, messages, toolUseID)
      yield result
    } else if (hook.type === 'agent') {
      const result = await execAgentHook(hook, hookName, hookEvent, jsonInput, abortSignal, toolUseContext, messages, toolUseID)
      yield result
    } else if (hook.type === 'http') {
      const { ok, body, error } = await execHttpHook(hook, hookEvent, jsonInput, abortSignal)
      // 处理 HTTP 响应...
    } else {
      // Command Hook
      const { stdout, stderr, status: exitCode } = await execCommandHook(...)
      // 处理命令输出...
    }
  })

  // [9] 聚合所有 Hook 的结果
  for await (const result of all(hookPromises)) {
    yield result
  }
}
```

### 2. Command Hook 执行器

Shell 命令是最常用的 Hook 类型：

```typescript
// 文件: src/utils/hooks.ts
// 行号: 747-900

async function execCommandHook(
  hook: HookCommand & { type: 'command' },
  hookEvent: HookEvent | 'StatusLine' | 'FileSuggestion',
  hookName: string,
  jsonInput: string,      // JSON 格式的 Hook 输入
  signal: AbortSignal,
  hookId: string,
  hookIndex?: number,
  pluginRoot?: string,    // 插件目录（用于变量替换）
  pluginId?: string,
  skillRoot?: string,
  forceSyncExecution?: boolean,
): Promise<{stdout, stderr, output, status, aborted?, backgrounded?}> {

  // ===== Shell 选择 =====
  // Windows 上默认使用 Git Bash (Cygwin)
  // 可通过 hook.shell 切换到 PowerShell
  const shellType = hook.shell ?? DEFAULT_HOOK_SHELL
  const isPowerShell = shellType === 'powershell'

  // Windows 路径转换（Bash 需要 POSIX 格式）
  const toHookPath =
    isWindows && !isPowerShell
      ? (p: string) => windowsPathToPosixPath(p)  // C:\Users\foo → /c/Users/foo
      : (p: string) => p

  // ===== 变量替换 =====
  let command = hook.command

  // 替换 ${CLAUDE_PLUGIN_ROOT}
  if (pluginRoot) {
    const rootPath = toHookPath(pluginRoot)
    command = command.replace(/\$\{CLAUDE_PLUGIN_ROOT\}/g, () => rootPath)
  }

  // 替换 ${user_config.X}（插件配置值）
  if (pluginId) {
    command = substituteUserConfigVariables(command, loadPluginOptions(pluginId))
  }

  // ===== 环境变量 =====
  const envVars: NodeJS.ProcessEnv = {
    ...subprocessEnv(),
    CLAUDE_PROJECT_DIR: toHookPath(projectDir),
  }

  // 暴露插件选项作为环境变量
  if (pluginOpts) {
    for (const [key, value] of Object.entries(pluginOpts)) {
      envVars[`CLAUDE_USER_CONFIG_${key.toUpperCase()}`] = String(value)
    }
  }

  // ===== JSON 输入传递 =====
  // 通过临时文件传递（避免命令行长度限制）
  const envFilePath = await getHookEnvFilePath(hookIndex)
  await fs.writeFile(envFilePath, jsonInput)
  envVars.CLAUDE_ENV_FILE = envFilePath

  // ===== 执行命令 =====
  const hookTimeoutMs = hook.timeout ? hook.timeout * 1000 : TOOL_HOOK_EXECUTION_TIMEOUT_MS

  const shellCommand = wrapSpawn(shell, shellArgs, {
    env: envVars,
    signal: combinedSignal,
    timeout: hookTimeoutMs,
  })

  // ===== 异步模式处理 =====
  // Hook 返回 {"async": true} 时后台执行
  if (hook.async || asyncResponse?.async) {
    const backgrounded = executeInBackground({
      processId,
      hookId,
      shellCommand,
      asyncResponse,
      hookEvent,
      hookName,
      command,
      asyncRewake: hook.asyncRewake,
    })
    return { stdout: '', stderr: '', output: '', status: 0, backgrounded }
  }

  // ===== 同步执行结果 =====
  const result = await shellCommand.result
  return {
    stdout: await shellCommand.taskOutput.getStdout(),
    stderr: shellCommand.taskOutput.getStderr(),
    output: stdout + stderr,
    status: result.code,
    aborted: combinedSignal.aborted,
  }
}
```

### 3. Hook 输出解析

解析 Hook 返回的 JSON 或纯文本：

```typescript
// 文件: src/utils/hooks.ts
// 行号: 399-451

function parseHookOutput(stdout: string): {
  json?: HookJSONOutput
  plainText?: string
  validationError?: string
} {
  const trimmed = stdout.trim()

  // [1] 非 JSON 输出：作为纯文本上下文
  if (!trimmed.startsWith('{')) {
    logForDebugging('Hook output does not start with {, treating as plain text')
    return { plainText: stdout }
  }

  // [2] JSON 输出：验证 schema
  try {
    const result = validateHookJson(trimmed)
    if ('json' in result) {
      return result
    }
    // Schema 验证失败：返回错误和期望格式
    return { plainText: stdout, validationError: result.validationError }
  } catch (e) {
    return { plainText: stdout }
  }
}

// 验证 JSON 输出是否符合 Hook 输出 schema
function validateHookJson(jsonString: string): { json: HookJSONOutput } | { validationError: string } {
  const parsed = jsonParse(jsonString)
  const validation = hookJSONOutputSchema().safeParse(parsed)

  if (validation.success) {
    return { json: validation.data }
  }

  // 格式化验证错误
  const errors = validation.error.issues
    .map(err => `  - ${err.path.join('.')}: ${err.message}`)
    .join('\n')
  return { validationError: `Hook JSON output validation failed:\n${errors}` }
}
```

---

## 设计亮点（工程智慧）

### 1. 工作区信任机制（安全第一）

所有 Hook 执行前都检查工作区信任：

```typescript
function shouldSkipHookDueToTrust(): boolean {
  // 非交互模式（SDK）隐式信任
  const isInteractive = !getIsNonInteractiveSession()
  if (!isInteractive) return false

  // 交互模式：必须显式信任
  const hasTrust = checkHasTrustDialogAccepted()
  return !hasTrust
}
```

**设计智慧**：
- Hook 可以执行任意 Shell 命令
- 恶意仓库可以在 settings.json 中配置危险 Hook
- 用户必须先确认信任工作区，Hook 才能执行
- 这是防止远程代码执行（RCE）的关键防线

### 2. 内部回调快速路径（性能优化）

当只有内部 Hook 时，跳过重量级处理：

```typescript
const userHooks = matchingHooks.filter(h => !isInternalHook(h))
if (userHooks.length === 0) {
  // 快速路径：直接调用回调
  // 跳过 JSON 序列化、进度消息、超时处理
  // 性能提升：6.01µs → ~1.8µs (-70%)
  for (const { hook } of matchingHooks) {
    await hook.callback(...)
  }
  return
}
```

**设计智慧**：
- 内部 Hook（如文件访问分析、归属追踪）每秒可能触发数十次
- 跳过不必要的处理显著降低开销
- 典型的"快速路径"优化模式

### 3. 延迟 JSON 序列化（懒加载）

Hook 输入只在实际需要时才序列化：

```typescript
let jsonInputResult: {...} | undefined

function getJsonInput() {
  if (jsonInputResult !== undefined) return jsonInputResult
  try {
    return (jsonInputResult = { ok: true, value: jsonStringify(hookInput) })
  } catch (error) {
    return (jsonInputResult = { ok: false, error })
  }
}

// 只在 Command/Prompt/Agent/HTTP Hook 时调用
const jsonInput = getJsonInput().value
```

**设计智慧**：
- Callback Hook 不需要 JSON 输入
- 避免不必要的序列化开销
- 所有 Hook 共享同一份序列化结果

### 4. 异步 Hook 唤醒机制

后台 Hook 可以在完成时唤醒模型：

```typescript
if (asyncRewake) {
  void shellCommand.result.then(result => {
    if (result.code === 2) {
      // exit 2: 阻塞错误，唤醒模型
      enqueuePendingNotification({
        value: wrapInSystemReminder(`Stop hook blocking error: ${stderr}`),
        mode: 'task-notification',
      })
    }
  })
}
```

**设计智慧**：
- 长时间运行的 Hook 不阻塞用户
- 但仍然可以在发现问题时通知模型
- 类似智能家居的"后台监控"模式

### 5. HTTP Hook 的 SSRF 防护

防止服务器端请求伪造：

```typescript
// DNS 解析时检查 IP 范围
const response = await axios.post(url, jsonInput, {
  lookup: sandboxProxy || envProxyActive ? undefined : ssrfGuardedLookup,
})

// ssrfGuardedLookup 阻止：
// - 私有 IP (10.x.x.x, 172.16.x.x, 192.168.x.x)
// - 链路本地 (169.254.x.x)
// - 回环地址 (127.x.x.x) - 除非显式允许
```

**设计智慧**：
- HTTP Hook 可以向任意 URL 发送请求
- 恶意配置可能访问内部服务（如 http://localhost:8080/admin）
- SSRF 防护确保只能访问公网地址

### 6. 多执行器统一接口

四种执行器返回相同的结果格式：

```typescript
// 所有执行器都返回 HookResult
type HookResult = {
  message?: Message
  blockingError?: HookBlockingError
  outcome: 'success' | 'blocking' | 'non_blocking_error' | 'cancelled'
  preventContinuation?: boolean
  permissionBehavior?: 'ask' | 'deny' | 'allow'
  updatedInput?: Record<string, unknown>
  additionalContext?: string
}
```

**设计智慧**：
- 不同执行器的差异被抽象化
- 调用者无需关心具体执行方式
- 易于扩展新的执行器类型

---

## 完整示例：PreToolUse Hook 工作流

假设配置了以下 Hook：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "check-dangerous-cmd.sh"
          }
        ]
      }
    ]
  }
}
```

当 Claude 执行 `Bash(rm -rf /)` 时：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PreToolUse Hook 示例                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. QueryEngine 调用 Bash 工具                                       │
│     input = {command: "rm -rf /"}                                   │
│                                                                      │
│  2. executePreToolHooks("Bash", toolUseID, input, context)          │
│     ↓                                                               │
│     executeHooks({hookInput: {                                      │
│       hook_event_name: "PreToolUse",                                │
│       tool_name: "Bash",                                            │
│       tool_input: {command: "rm -rf /"}                             │
│     }})                                                             │
│                                                                      │
│  3. 匹配 Hook                                                        │
│     getMatchingHooks() 找到 matcher="Bash" 的 Hook                  │
│                                                                      │
│  4. 执行 Command Hook                                                │
│     execCommandHook()                                               │
│     ↓                                                               │
│     环境变量: CLAUDE_ENV_FILE = /tmp/hook-env-xxx                   │
│     命令: check-dangerous-cmd.sh                                    │
│     ↓                                                               │
│     脚本读取 CLAUDE_ENV_FILE，解析 tool_input                       │
│     发现 "rm -rf /" 是危险命令                                      │
│     ↓                                                               │
│     输出 JSON: {"decision": "block", "reason": "危险命令：rm -rf"}  │
│     exit code: 0                                                    │
│                                                                      │
│  5. 解析输出                                                         │
│     parseHookOutput(stdout) → {json: {decision: "block"}}          │
│     ↓                                                               │
│     processHookJSONOutput() → {                                     │
│       outcome: "blocking",                                          │
│       permissionBehavior: "deny",                                   │
│       blockingError: "危险命令：rm -rf"                             │
│     }                                                               │
│                                                                      │
│  6. 返回结果                                                         │
│     AggregatedHookResult {                                          │
│       preventContinuation: true,                                    │
│       blockingError: "危险命令：rm -rf"                             │
│     }                                                               │
│                                                                      │
│  7. QueryEngine 处理                                                 │
│     收到 preventContinuation=true                                   │
│     → 不执行 Bash 工具                                              │
│     → 向模型发送阻塞消息                                            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 文件路径索引

### 核心文件
- `src/utils/hooks.ts` - **主执行逻辑，executeHooks 函数**
- `src/types/hooks.ts` - TypeScript 类型定义和 Zod schema
- `src/schemas/hooks.ts` - Hook Zod schema 定义

### 执行器
- `src/utils/hooks/execPromptHook.ts` - Prompt Hook 执行器（LLM 单轮判断）
- `src/utils/hooks/execAgentHook.ts` - Agent Hook 执行器（多轮工具调用）
- `src/utils/hooks/execHttpHook.ts` - HTTP Hook 执行器（POST 请求）
- `src/utils/hooks/hookHelpers.ts` - 执行器辅助函数

### 配置与管理
- `src/utils/hooks/hooksConfigManager.ts` - Hook 配置管理
- `src/utils/hooks/hooksConfigSnapshot.ts` - Hook 配置快照
- `src/utils/hooks/hooksSettings.ts` - Hook 设置处理
- `src/utils/hooks/sessionHooks.ts` - 会话级 Hook 管理

### 安全
- `src/utils/hooks/ssrfGuard.ts` - SSRF 防护（DNS 检查）
- `src/utils/hooks/AsyncHookRegistry.ts` - 异步 Hook 注册表

### 事件系统
- `src/utils/hooks/hookEvents.ts` - Hook 事件广播系统

---

## 总结

Claude Code 的 Hook 系统是一个精心设计的可扩展框架：

| 特性 | 实现方式 | 效果 |
|------|---------|------|
| **安全优先** | 工作区信任检查 | 防止恶意 RCE |
| **高性能** | 内部回调快速路径 | 70% 性能提升 |
| **延迟加载** | JSON 序列化懒执行 | 减少不必要开销 |
| **多执行器** | 统一结果接口 | 灵活扩展 |
| **异步支持** | AsyncHookRegistry | 不阻塞用户 |
| **SSRF 防护** | DNS IP 检查 | 保护内部服务 |

这个系统让用户可以在不修改 Claude Code 源码的情况下，通过配置文件注入自定义逻辑，实现了强大的可扩展性。

---

## 附录：Hook 系统核心认知

### A. 三种执行器的定位与选择

| Hook 类型 | 定位 | 能力 | 速度 | 成本 | 适用场景 |
|-----------|------|------|------|------|----------|
| **Command** | 执行器 | 跑 Shell 命令/脚本 | ⚡ 快 | 💰 低 | 明确规则（黑名单、路径检查、自动备份） |
| **Prompt** | 判断器 | 单轮 LLM 语义判断 | 🚀 较快 | 💰💰 中 | 模糊判断（"是否危险"、"是否合理"） |
| **Agent** | 调查员 | 多轮工具调用 + 推理 | 🐢 慢 | 💰💰💰 高 | 复杂验证（需查文件、查数据库、多步分析） |

**选择指南：**

```
需要做什么判断？
│
├─ 规则明确（黑名单/路径检查/格式验证）
│  └─ → Command Hook
│
├─ 需要语义理解（"这是否危险"、"是否合理"）
│  └─ → Prompt Hook
│
└─ 需要查文件/查数据库/多步验证
   └─ → Agent Hook
```

---

### B. Hook 的能力边界

| 流程阶段 | Hook 事件 | 控制能力 |
|----------|-----------|----------|
| 用户提交输入 | `UserPromptSubmit` | ✅ 可修改/过滤输入 |
| 模型生成中 | **无** | ❌ **无法干预** |
| 工具调用前 | `PreToolUse` | ✅ **可拦截/修改/阻断** |
| 工具执行后 | `PostToolUse` | ✅ 可修改结果/添加上下文 |
| 工具执行失败 | `PostToolUseFailure` | ✅ 可处理错误 |
| 响应结束 | `Stop` | ✅ 可触发后续动作 |

**不能做的：**
- ❌ 修改模型生成的文本内容（生成过程无法干预）
- ❌ 在模型思考中插入内容（无对应 Hook 事件）
- ❌ 动态添加新的工具调用（Hook 不能代替模型决策）
- ❌ 改变模型的推理逻辑（模型内部行为）

**定位：** Hook 系统是**事件拦截器**，不是**流程编排引擎**。

---

### C. 为什么用 Hook 系统而不是写死在主流程？

这是**架构选择**，不是技术必须。核心是**控制反转（IoC）**：

| 维度 | 写死在主流程 | Hook 系统 |
|------|--------------|-----------|
| **扩展权** | 官方团队垄断 | 用户/团队/插件各自决定 |
| **定制性** | 需改源码/重启 | 改配置即生效 |
| **插件生态** | 无法存在 | 核心支撑 |
| **需求冲突** | 难以协调 | 各自配置互不干扰 |
| **安全边界** | 分散 | 统一管理（信任/超时/SSRF） |

**本质：** Hook 系统牺牲了一点性能（事件分发、JSON 序列化），换来了**可扩展性**和**生态可能性**。

这和以下设计模式是同一思路：

| 领域 | 类似概念 |
|------|----------|
| Web 框架 | Middleware / Plugin |
| Git | Hook (pre-commit, post-receive) |
| VS Code | Extension API |
| WordPress | Action / Filter |
| 游戏引擎 | Event System |

---

### D. 一句话总结

> **Hook 是 Claude Code 的"可编程触发器"——在特定事件发生时自动执行预设操作，让用户无需修改源码就能扩展/干预系统行为。**

**核心价值：** 从"固定行为"变成"可编程平台"。

---

### E. 为什么 Hook 可以执行任意 Shell 命令？

#### 技术实现：底层就是 spawn 一个 Shell 进程

```typescript
// src/utils/hooks.ts - execCommandHook

async function execCommandHook(hook: HookCommand, ...) {
  // 1. 选择 Shell（bash 或 powershell）
  const shell = hook.shell === 'powershell' ? 'pwsh' : 'bash'
  
  // 2. 准备环境变量
  const env = {
    CLAUDE_PROJECT_DIR: projectDir,
    CLAUDE_ENV_FILE: hookEnvFile,  // JSON 输入通过文件传递
    ...process.env
  }
  
  // 3. 直接 spawn 子进程执行
  const shellCommand = spawn(shell, [hook.command], { env, signal })
  
  // 4. 等待执行结果
  const { stdout, stderr, code } = await shellCommand.result
  
  return { stdout, stderr, status: code }
}
```

**本质：** Hook 系统调用 `child_process.spawn()` 启动一个 Shell 子进程，把 `hook.command` 传进去执行。所以 **Shell 能做什么，Hook 就能做什么**。

#### 为什么要给这个能力？

| 目标 | 需要 Shell 能力 |
|------|----------------|
| **安全检查** | 运行安全扫描工具（如 `gitleaks`、`trufflehog`） |
| **环境准备** | 激活虚拟环境、加载配置（`source .venv/bin/activate`） |
| **文件操作** | 备份、同步、版本控制（`git add/commit`） |
| **外部集成** | 调用 CLI 工具（`aws`、`kubectl`、`docker`） |
| **通知告警** | 发送消息（`curl` 到 Slack/DingTalk API） |
| **日志审计** | 写入日志系统（`logger`、`syslog`） |

**如果限制 Shell 命令，Hook 的扩展能力就废了。**

#### 安全约束：如何防止滥用？

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hook 安全防护体系                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  【第 1 层】工作区信任                                            │
│  ─────────────────────────────────────────────────────────────  │
│  交互式会话中，用户必须先确认信任工作区，Hook 才能执行            │
│  防止恶意仓库通过 settings.json 注入危险 Hook                    │
│                                                                  │
│  【第 2 层】超时控制                                              │
│  ─────────────────────────────────────────────────────────────  │
│  默认 10 分钟超时，防止 Hang 住或无限循环                         │
│                                                                  │
│  【第 3 层】退出码语义                                            │
│  ─────────────────────────────────────────────────────────────  │
│  exit 0/1/2 有明确语义，系统可以统一处理                         │
│                                                                  │
│  【第 4 层】HTTP Hook 的 SSRF 防护                               │
│  ─────────────────────────────────────────────────────────────  │
│  DNS 解析时检查 IP，阻止访问内网                                 │
│                                                                  │
│  【第 5 层】环境变量隔离                                          │
│  ─────────────────────────────────────────────────────────────  │
│  Hook 只能访问显式暴露的环境变量                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**最关键的是第 1 层——工作区信任机制：**

```typescript
function shouldSkipHookDueToTrust(): boolean {
  const isInteractive = !getIsNonInteractiveSession()
  if (!isInteractive) return false  // SDK 模式隐式信任
  
  const hasTrust = checkHasTrustDialogAccepted()
  return !hasTrust  // 交互模式必须显式信任
}
```

#### 行业对比

| 系统 | 类似机制 | 权限 |
|------|----------|------|
| **Git** | `pre-commit`、`post-receive` Hook | 任意 Shell 命令 |
| **VS Code** | Task / Extension | 任意 Node.js/Shell |
| **npm** | `preinstall`、`postinstall` 脚本 | 任意 Shell 命令 |
| **WordPress** | Plugin/Action | 任意 PHP 代码 |
| **Claude Code** | Hook 系统 | 任意 Shell 命令 |

**本质权衡：**

```
扩展能力 ↑  ←→  安全风险 ↑
```

Hook 系统选择了**给用户最大扩展能力**，同时用**信任机制**把决策权交给用户。

---

### F. 为什么需要 Agent Hook？

#### 核心问题

既然 Command Hook 能执行任意 Shell 命令，为什么还要专门设计 Agent Hook？

```
┌─────────────────────────────────────────────────────────────────┐
│                    Command Hook vs Agent Hook                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Command Hook                    Agent Hook                      │
│  ────────────                    ──────────                      │
│  执行预设脚本                    启动独立 Agent                   │
│  ↓                             ↓                                │
│  只能做脚本里写好的事            可以动态决策、多轮推理            │
│  ↓                             ↓                                │
│  无法读取文件（除非脚本写死）    可以调用工具读文件、搜索、分析    │
│  ↓                             ↓                                │
│  规则是静态的                   推理是动态的                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 场景对比：检查文件删除操作是否安全

**方案 A：Command Hook**

```bash
#!/bin/bash
# check-delete.sh

# 只能做预设的规则检查
if [[ "$INPUT" == *"rm -rf /"* ]]; then
  echo '{"ok": false, "reason": "危险命令"}'
  exit 2
fi

if [[ "$INPUT" == *"rm -rf .git"* ]]; then
  echo '{"ok": false, "reason": "不能删除 git 目录"}'
  exit 2
fi

# 问题：无法动态判断其他情况
echo '{"ok": true}'
```

**局限：**
- ❌ 规则是写死的，新情况无法处理
- ❌ 无法读取文件系统了解上下文
- ❌ 无法判断"这个目录是否重要"

---

**方案 B：Agent Hook**

```json
{
  "type": "agent",
  "prompt": "检查这个删除操作是否安全。你可以读取目录结构来分析影响。"
}
```

**执行流程：**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Hook 执行过程                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  第 1 轮：Agent 读取当前目录结构                                  │
│         Read tool → 发现要删除的是 build/ 目录                   │
│                                                                  │
│  第 2 轮：Agent 检查是否有重要文件                               │
│         Read tool → 发现 build/output.js 是生产依赖              │
│                                                                  │
│  第 3 轮：Agent 搜索代码引用                                     │
│         Bash tool → grep -r "build/output" 发现 3 处引用         │
│                                                                  │
│  第 4 轮：Agent 做出判断                                         │
│         StructuredOutput → {"ok": false, "reason": "有代码引用"} │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**优势：**
- ✅ 可以动态读取文件了解上下文
- ✅ 可以多步推理分析影响
- ✅ 可以调用其他工具辅助判断

---

#### 本质区别

| 维度 | Command Hook | Agent Hook |
|------|--------------|------------|
| **决策方式** | 脚本逻辑（if/else） | LLM 多轮推理 |
| **信息获取** | 只能靠输入参数 | 可以主动调用工具获取 |
| **灵活性** | 规则是静态的 | 可以动态适应新情况 |
| **能力边界** | Shell 能做什么 | Agent 工具集能做什么 |
| **维护成本** | 规则越复杂脚本越难写 | 提示词写好即可 |

---

#### 什么时候必须用 Agent Hook？

| 场景 | Command Hook | Agent Hook |
|------|--------------|------------|
| 检查代码修改是否破坏 API 兼容性 | ❌ 做不到（无法动态读文件分析） | ✅ 可以读旧代码 + 新代码 + 测试文件，综合判断 |
| 检查数据库配置修改是否安全 | ❌ 只能做简单规则匹配 | ✅ 可以读配置 + 查代码使用 + 检查迁移脚本 |
| 判断操作是否符合公司安全政策 | ❌ 政策文档几千行，脚本没法写 | ✅ 可以让 Agent 读取政策文档 + 分析当前操作 |

---

#### 为什么不只用 Agent Hook？

| 原因 | 说明 |
|------|------|
| **成本** | Agent Hook 多次 LLM 调用，Command Hook 几乎免费 |
| **速度** | Agent Hook 可能几十秒，Command Hook 几毫秒 |
| **确定性** | Agent Hook 输出不稳定，Command Hook 规则确定 |
| **简单场景** | 黑名单检查用脚本就够了，不需要杀鸡用牛刀 |

---

#### 三层决策体系

```
                    需要做什么判断？
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
   明确规则判断        语义理解判断        复杂调查验证
   (黑名单/路径)      ("是否危险")      (需查文件/多步)
        │                  │                  │
        ▼                  ▼                  ▼
   Command Hook       Prompt Hook        Agent Hook
   成本：低           成本：中           成本：高
   速度：快           速度：中           速度：慢
```

---

#### 总结

| 问题 | 答案 |
|------|------|
| 为什么有 Agent Hook？ | Command Hook 无法动态获取信息、多步推理 |
| 核心差异？ | Command Hook 是**执行预设逻辑**，Agent Hook 是**动态调查决策** |
| 什么时候用？ | 需要读文件/多步验证/复杂推理时用 Agent Hook |
| 为什么不只用 Agent？ | 成本、速度、确定性——简单场景不需要 |

**一句话：** Agent Hook 是把**复杂判断**外包给一个能思考、能查资料的小 Agent，而 Command Hook 只能执行**写死的脚本逻辑**。