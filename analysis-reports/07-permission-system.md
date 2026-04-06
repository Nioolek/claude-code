# Claude Code 权限系统深度分析报告

## 模块概述（通俗开场）

### 一句话角色定位

**权限系统是 Claude Code 的"安全门卫"**——它站在每一个工具执行之前，像一位严谨的保安，检查每个请求是否获得了通行许可。

### 核心职责

想象一家高科技公司的安保系统：

```
┌─────────────────────────────────────────────────────────────────┐
│                      Claude Code 安全门卫                          │
├─────────────────────────────────────────────────────────────────┤
│  1. 【身份验证】    检查工具类型是否被禁止或允许                     │
│  2. 【权限核验】    检查具体操作内容是否符合规则                     │
│  3. 【安全审查】    对危险路径(.git/、.claude/)进行特殊检查          │
│  4. 【审批流转】    将请求提交给用户/分类器/Hook进行审批              │
│  5. 【决策执行】    根据审批结果允许或拒绝工具执行                    │
│  6. 【记录归档】    记录所有决策用于审计和后续优化                    │
└─────────────────────────────────────────────────────────────────┘
```

### 与其他模块的关系图

```
                    ┌──────────────┐
                    │   QueryEngine │  ← 发起工具调用请求
                    │  (查询引擎)    │
                    └──────┬───────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │                  Permission System                   │
    │                   (权限系统)                          │
    ├──────────┬──────────┬──────────┬──────────┬─────────┤
    │          │          │          │          │         │
    ▼          ▼          ▼          ▼          ▼         ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│  Rules │ │  Mode  │ │ Hooks  │ │Classifier│ │  UI   │ │Bridge  │
│ (规则) │ │ (模式) │ │ (钩子) │ │(分类器) │ │(对话框)│ │(远程) │
└────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘
     │         │         │         │         │         │
     └─────────┴─────────┴─────────┴────┬────┴─────────┴────┘
                                        │
                                        ▼
                               ┌──────────────┐
                               │ Tool Execution│  ← 执行或拒绝
                               │  (工具执行)    │
                               └──────────────┘
```

---

## 核心概念（生活化类比）

### 1. PermissionMode（权限模式）—— 门卫的工作方式

想象门卫有几种不同的工作状态：

| 模式 | 生活类比 | 实际行为 |
|------|---------|---------|
| `default` | **标准安检**：每个人都要出示通行证 | 每个工具调用都需要用户确认 |
| `plan` | **只读参观**：只允许参观，不允许触碰 | 只允许读取操作，禁止写入 |
| `acceptEdits` | **VIP通道**：编辑操作免检通过 | 自动接受所有编辑类工具调用 |
| `bypassPermissions` | **紧急状态**：门卫暂时休息（危险） | 绕过所有权限检查 |
| `dontAsk` | **闭门模式**：来人直接拒之门外 | 直接拒绝所有请求，不询问 |
| `auto` | **AI安检员**：智能判断是否放行 | AI分类器自动决策 |

**模式切换（Shift+Tab 快捷键）**：

```
default → acceptEdits → plan → bypassPermissions → auto → default
   ↑                                                      │
   └──────────────────────────────────────────────────────┘
```

### 2. PermissionRule（权限规则）—— 门卫的通行证清单

门卫手里有一本"通行证清单"，记录着哪些人可以无条件通过：

```
┌─────────────────────────────────────────────────────────────┐
│                    通行证清单示例                              │
├─────────────────────────────────────────────────────────────┤
│  Bash                           ← 整个 Bash 工具允许         │
│  Bash(git:*)                    ← 所有 git 命令允许          │
│  Bash(npm install)              ← 精确匹配：npm install 允许 │
│  Bash(npm run *)                ← 通配符：npm run xxx 允许   │
│  Read                           ← 整个 Read 工具允许         │
│  Read(*.md)                     ← 只允许读取 .md 文件        │
└─────────────────────────────────────────────────────────────┘
```

**规则匹配类型**：

| 类型 | 格式 | 匹配示例 | 生活类比 |
|------|------|---------|---------|
| `exact` | `npm install` | 只匹配"npm install" | **指定名单**：只有张三能进 |
| `prefix` | `git:*` | 匹配"git clone"、"git push"等 | **姓氏准入**：姓李的都能进 |
| `wildcard` | `npm run *` | 匹配"npm run dev"、"npm run test" | **模糊名单**：穿蓝衣服的都能进 |

### 3. PermissionBehavior（权限行为）—— 门卫的决定

门卫对每个请求有三种决定：

```
┌─────────────────────────────────────────────────────────────┐
│                    门卫的三种决定                              │
├──────────────┬──────────────┬───────────────────────────────┤
│   'allow'    │   'deny'     │        'ask'                  │
│   【放行】    │   【拒绝】    │        【请示上级】            │
├──────────────┼──────────────┼───────────────────────────────┤
│ 直接执行工具  │ 拒绝并告知原因 │ 弹出对话框等待用户/分类器决策 │
└──────────────┴──────────────┴───────────────────────────────┘
```

### 4. ToolPermissionContext（权限上下文）—— 门卫的记事本

门卫随身携带一本记事本，记录当前状态：

```typescript
type ToolPermissionContext = {
  mode: PermissionMode              // 当前工作模式（标准安检/VIP通道等）
  additionalWorkingDirectories: Map // 额外允许访问的目录
  alwaysAllowRules: {...}           // 永久放行清单
  alwaysDenyRules: {...}            // 永久拒绝清单
  alwaysAskRules: {...}             // 永久需要请示的清单
  isBypassPermissionsModeAvailable: boolean // 是否可以使用紧急状态
}
```

**生活类比**：门卫的记事本上写着"今天是VIP接待日"、"张经理全家可以进入"、"王秘书需要请示"等信息。

### 5. createResolveOnce（原子竞争解决）—— 门卫的唯一发言权

当多人同时试图批准一个请求时，需要确保只有一个人的决定生效：

```typescript
type ResolveOnce<T> = {
  resolve(value: T): void    // 做出最终决定
  isResolved(): boolean      // 检查是否已有人决定
  claim(): boolean           // 尝试夺取决定权（原子操作）
}
```

**生活类比**：想象公司有5个部门主管都能批准门卫的请示。门卫发出请示后，哪个主管先回复就由他决定，其他主管的回复作废。`claim()` 就是门卫用来确认"我收到您的批准了，其他主管的回复我不再接受"的机制。

---

## 完整工作流程（数据流图）

### 权限检查完整流水线

当 Claude 想执行一个工具时，权限系统启动完整的检查流程：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    权限检查决策流水线（14步）                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: tool(工具), input(参数), context(上下文)                       │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第一阶段：规则层检查（强制执行，不可绕过）                             │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [1a] 检查整工具拒绝规则                                              │
│       ↓ 有拒绝规则 → 返回 {behavior: 'deny'}                         │
│                                                                      │
│  [1b] 检查整工具询问规则                                              │
│       ↓ 有询问规则 → 返回 {behavior: 'ask'}                          │
│                                                                      │
│  [1c] 工具自身权限检查 (tool.checkPermissions)                        │
│       ↓ Bash 检查子命令规则、Read 检查路径等                          │
│                                                                      │
│  [1d] 工具实现返回拒绝                                                │
│       ↓ 返回 deny → 直接拒绝                                         │
│                                                                      │
│  [1e] 工具需要用户交互 (requiresUserInteraction)                      │
│       ↓ 是 → 必须弹出对话框                                           │
│                                                                      │
│  [1f] 内容级询问规则                                                  │
│       ↓ 如 Bash(npm publish:*) → 必须询问                            │
│                                                                      │
│  [1g] 安全检查（绕过免疫）                                            │
│       ↓ .git/、.claude/、shell配置 → 必须询问                         │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第二阶段：模式层检查                                                 │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [2a] bypassPermissions 模式                                         │
│       ↓ 是 → 直接放行（跳过后续检查）                                 │
│                                                                      │
│  [2b] 整工具允许规则                                                  │
│       ↓ 有允许规则 → 直接放行                                         │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第三阶段：模式后处理                                                 │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [3] passthrough → ask 转换                                          │
│       ↓ 无明确决策 → 转为需要询问                                     │
│                                                                      │
│  [4] dontAsk 模式                                                     │
│       ↓ 直接拒绝，不询问                                              │
│                                                                      │
│  [5] auto 模式 + TRANSCRIPT_CLASSIFIER                               │
│       ↓ 运行 AI 分类器自动决策                                        │
│                                                                      │
│  [6] shouldAvoidPermissionPrompts                                    │
│       ↓ 后台/无头模式 → 自动拒绝                                      │
│                                                                      │
│  ══════════════════════════════════════════════════════════════════ │
│  第四阶段：交互层处理                                                 │
│  ══════════════════════════════════════════════════════════════════ │
│                                                                      │
│  [7] 5路竞速决策                                                      │
│       ┌─────────────────────────────────────────────┐               │
│       │ 路径1: 本地用户交互对话框                     │               │
│       │ 路径2: Bridge 远程响应 (claude.ai Web UI)    │               │
│       │ 路径3: Channel 消息中继 (Telegram/iMessage)  │               │
│       │ 路径4: Hook 异步决策 (PermissionRequest)     │               │
│       │ 路径5: Bash 分类器自动批准                   │               │
│       └─────────────────────────────────────────────┘               │
│       ↓ 竞速获胜者通过 claim() 获取决定权                             │
│                                                                      │
│  输出: PermissionDecision {behavior: 'allow' | 'deny' | 'ask'}       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 交互式权限请求的5路竞速

当权限检查返回 `ask`（需要请示）时，系统启动5路竞速：

```
                        ┌─────────────────┐
                        │  Permission Ask │
                        │   (需要请示)     │
                        └────────┬────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌──────────────┐         ┌──────────────┐        ┌──────────────┐
│   本地 UI     │         │   Bridge     │        │   Channel    │
│  (用户对话框) │         │ (Web UI)     │        │ (Telegram等) │
│              │         │              │        │              │
│ 用户按键操作  │         │ 远程用户批准 │        │ 消息回复批准  │
└──────┬───────┘         └──────┬───────┘        └──────┬───────┘
       │                        │                       │
       │         ┌──────────────┼──────────────┐        │
       │         │              │              │        │
       │         ▼              ▼              ▼        │
       │   ┌──────────┐  ┌──────────┐  ┌──────────┐     │
       │   │  Hooks   │  │Classifier│  │ 分类器   │     │
       │   │(异步决策)│  │ (Bash)   │  │ (Auto)   │     │
       │   └────┬─────┘  └────┬─────┘  └────┬─────┘     │
       │        │            │            │            │
       └────────┴────────────┴────────────┴────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   createResolveOnce     │
                    │   (原子竞争解决)          │
                    │                         │
                    │   claim() → 唯一决策者   │
                    │   resolve() → 最终结果   │
                    └─────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   PermissionDecision    │
                    │   {allow/deny/ask}      │
                    └─────────────────────────┘
```

---

## 关键代码解读（逐行注释）

### 1. 核心决策函数 hasPermissionsToUseToolInner

这是权限系统的"大脑"，每个工具调用都会经过这个函数：

```typescript
// 文件: src/utils/permissions/permissions.ts
// 行号: 1158-1319

async function hasPermissionsToUseToolInner(
  tool: Tool,                        // 要执行的工具
  input: { [key: string]: unknown }, // 工具参数
  context: ToolUseContext,           // 执行上下文（包含权限状态）
): Promise<PermissionDecision> {     // 返回: 允许/拒绝/询问

  // ===== 预检查 =====
  // 如果用户已经按 Ctrl+C 中止，直接抛出异常
  if (context.abortController.signal.aborted) {
    throw new AbortError()
  }

  // 获取当前应用状态（包含权限上下文）
  let appState = context.getAppState()

  // ===== 第一阶段：规则层检查 =====
  // 这些检查是强制性的，即使在 bypass 模式下也要执行

  // [1a] 检查整工具拒绝规则
  // 如果整个工具类型被禁止（如 "Bash" 在 deny 清单中），直接拒绝
  const denyRule = getDenyRuleForTool(appState.toolPermissionContext, tool)
  if (denyRule) {
    return {
      behavior: 'deny',
      decisionReason: { type: 'rule', rule: denyRule },
      message: `Permission to use ${tool.name} has been denied.`,
    }
  }

  // [1b] 检查整工具询问规则
  // 如果工具类型需要询问（如配置了 "Bash(ask)"），进入询问流程
  const askRule = getAskRuleForTool(appState.toolPermissionContext, tool)
  if (askRule) {
    // 特殊情况：沙箱模式下可以自动放行某些 Bash 命令
    const canSandboxAutoAllow =
      tool.name === BASH_TOOL_NAME &&
      SandboxManager.isSandboxingEnabled() &&
      SandboxManager.isAutoAllowBashIfSandboxedEnabled() &&
      shouldUseSandbox(input)

    // 如果不能自动放行，返回询问决策
    if (!canSandboxAutoAllow) {
      return {
        behavior: 'ask',
        decisionReason: { type: 'rule', rule: askRule },
        message: createPermissionRequestMessage(tool.name),
      }
    }
    // 能自动放行时，继续后续检查
  }

  // [1c] 工具自身权限检查
  // 每个工具可以定义自己的权限检查逻辑
  // Bash 检查子命令规则，Read 检查文件路径等
  let toolPermissionResult: PermissionResult = {
    behavior: 'passthrough',  // 默认：无明确决策，传递给下一阶段
    message: createPermissionRequestMessage(tool.name),
  }
  try {
    const parsedInput = tool.inputSchema.parse(input)  // 先验证参数格式
    toolPermissionResult = await tool.checkPermissions(parsedInput, context)
  } catch (e) {
    // 保留中止错误，其他错误记录日志但不中断流程
    if (e instanceof AbortError || e instanceof APIUserAbortError) {
      throw e
    }
    logError(e)
  }

  // [1d] 工具实现返回拒绝
  // 工具自身检查发现问题（如危险命令），直接拒绝
  if (toolPermissionResult?.behavior === 'deny') {
    return toolPermissionResult
  }

  // [1e] 工具需要强制用户交互
  // 某些工具（如 AskUserQuestion）必须有用户参与
  if (
    tool.requiresUserInteraction?.() &&
    toolPermissionResult?.behavior === 'ask'
  ) {
    return toolPermissionResult
  }

  // [1f] 内容级询问规则
  // 如配置了 "Bash(npm publish:*)" 需要询问，即使 bypass 模式也必须询问
  if (
    toolPermissionResult?.behavior === 'ask' &&
    toolPermissionResult.decisionReason?.type === 'rule' &&
    toolPermissionResult.decisionReason.rule.ruleBehavior === 'ask'
  ) {
    return toolPermissionResult
  }

  // [1g] 安全检查（绕过免疫）
  // 某些路径（.git/、.claude/、shell配置）在任何模式下都需要用户确认
  if (
    toolPermissionResult?.behavior === 'ask' &&
    toolPermissionResult.decisionReason?.type === 'safetyCheck'
  ) {
    return toolPermissionResult
  }

  // ===== 第二阶段：模式层检查 =====

  // 重新获取最新状态（因为模式可能在检查过程中被改变）
  appState = context.getAppState()

  // [2a] bypassPermissions 模式检查
  // 如果在"紧急状态"或"计划模式+原紧急状态"，直接放行
  const shouldBypassPermissions =
    appState.toolPermissionContext.mode === 'bypassPermissions' ||
    (appState.toolPermissionContext.mode === 'plan' &&
      appState.toolPermissionContext.isBypassPermissionsModeAvailable)

  if (shouldBypassPermissions) {
    return {
      behavior: 'allow',
      updatedInput: getUpdatedInputOrFallback(toolPermissionResult, input),
      decisionReason: {
        type: 'mode',
        mode: appState.toolPermissionContext.mode,
      },
    }
  }

  // [2b] 整工具允许规则
  // 如果工具类型在"永久放行清单"中，直接放行
  const alwaysAllowedRule = toolAlwaysAllowedRule(
    appState.toolPermissionContext,
    tool,
  )
  if (alwaysAllowedRule) {
    return {
      behavior: 'allow',
      updatedInput: getUpdatedInputOrFallback(toolPermissionResult, input),
      decisionReason: { type: 'rule', rule: alwaysAllowedRule },
    }
  }

  // ===== 第三阶段：转换 =====

  // [3] 将 passthrough 转换为 ask
  // 如果所有检查都没有明确决策，转为"需要询问"
  const result: PermissionDecision =
    toolPermissionResult.behavior === 'passthrough'
      ? {
          ...toolPermissionResult,
          behavior: 'ask' as const,
          message: createPermissionRequestMessage(
            tool.name,
            toolPermissionResult.decisionReason,
          ),
        }
      : toolPermissionResult

  // 记录权限建议（用于"永久放行"按钮的选项）
  if (result.behavior === 'ask' && result.suggestions) {
    logForDebugging(
      `Permission suggestions for ${tool.name}: ${jsonStringify(result.suggestions, null, 2)}`,
    )
  }

  return result
}
```

### 2. createResolveOnce 原子竞争解决

当多个审批源同时响应时，确保只有一个生效：

```typescript
// 文件: src/hooks/toolPermission/PermissionContext.ts
// 行号: 63-94

type ResolveOnce<T> = {
  resolve(value: T): void    // 做出最终决定
  isResolved(): boolean      // 检查是否已有决定
  claim(): boolean           // 尝试夺取决定权（原子操作）
}

function createResolveOnce<T>(resolve: (value: T) => void): ResolveOnce<T> {
  let claimed = false        // 是否已被某人"认领"
  let delivered = false      // 是否已最终决定

  return {
    // 做出最终决定（只能调用一次）
    resolve(value: T) {
      if (delivered) return  // 已决定，忽略后续调用
      delivered = true       // 标记已决定
      claimed = true         // 同时标记已认领
      resolve(value)         // 调用外部的 resolve 函数
    },

    // 检查是否已有人认领
    isResolved() {
      return claimed
    },

    // 尝试认领（原子操作）
    // 返回 true 表示成功认领，可以做决定
    // 返回 false 表示已被其他人认领，不能做决定
    claim() {
      if (claimed) return false  // 已认领，失败
      claimed = true             // 标记认领
      return true                // 成功认领
    },
  }
}
```

**使用示例**：

```typescript
// 在 interactiveHandler.ts 中的典型使用模式
function handleInteractivePermission(params, resolve) {
  const { claim, resolveOnce } = createResolveOnce(resolve)

  // 路径1: 本地用户批准
  onAllow() {
    if (!claim()) return  // 原子检查：如果已被其他人认领，退出
    resolveOnce(allowDecision)  // 做出最终决定
  }

  // 路径2: Bridge 远程批准
  bridgeCallbacks.onResponse(response => {
    if (!claim()) return  // 原子检查：如果已被本地用户认领，退出
    resolveOnce(allowDecision)
  })

  // 路径3: Hook 异步批准
  void ctx.runHooks().then(hookDecision => {
    if (!hookDecision || !claim()) return  // 原子检查
    resolveOnce(hookDecision)
  })

  // 路径4: 分类器自动批准
  void classifierCheck().then(decision => {
    if (!claim()) return  // 原子检查
    resolveOnce(allowDecision)
  })
}
```

### 3. Shell 规则匹配

Bash 工具的命令匹配逻辑：

```typescript
// 文件: src/utils/permissions/shellRuleMatching.ts
// 行号: 159-184

// 解析权限规则字符串，返回结构化的规则对象
export function parsePermissionRule(permissionRule: string): ShellPermissionRule {
  // 1. 检查旧版前缀语法 (git:* 格式)
  const prefix = permissionRuleExtractPrefix(permissionRule)
  if (prefix !== null) {
    return { type: 'prefix', prefix }  // 前缀匹配规则
  }

  // 2. 检查新版通配符语法 (包含 * 但不是 :* 结尾)
  if (hasWildcards(permissionRule)) {
    return { type: 'wildcard', pattern: permissionRule }  // 通配符规则
  }

  // 3. 否则是精确匹配
  return { type: 'exact', command: permissionRule }
}
```

**通配符匹配详解**：

```typescript
// 文件: src/utils/permissions/shellRuleMatching.ts
// 行号: 90-154

export function matchWildcardPattern(pattern: string, command: string): boolean {
  // 处理转义字符：\* 匹配字面星号，\\ 匹配字面反斜杠
  let processed = ''
  let i = 0
  while (i < pattern.length) {
    if (pattern[i] === '\\' && i + 1 < pattern.length) {
      if (pattern[i + 1] === '*') {
        processed += '\x00ESCAPED_STAR\x00'  // 占位符：字面星号
        i += 2
        continue
      } else if (pattern[i + 1] === '\\') {
        processed += '\x00ESCAPED_BACKSLASH\x00'  // 占位符：字面反斜杠
        i += 2
        continue
      }
    }
    processed += pattern[i]
    i++
  }

  // 转义正则特殊字符（除了 *）
  const escaped = processed.replace(/[.+?^${}()|[\]\\'"]/g, '\\$&')

  // 将 * 转换为 .*（正则通配符）
  const withWildcards = escaped.replace(/\*/g, '.*')

  // 将占位符还原为转义的正则字符
  let regexPattern = withWildcards
    .replace(/\x00ESCAPED_STAR\x00/g, '\\*')
    .replace(/\x00ESCAPED_BACKSLASH\x00/g, '\\\\')

  // 特殊处理：'git *' 模式（只有末尾一个通配符）
  // 让 'git' 命令本身也能匹配（与 git:* 语义一致）
  if (regexPattern.endsWith(' .*') && 只有末尾一个星号) {
    regexPattern = regexPattern.slice(0, -3) + '( .*)?'
  }

  // 创建正则并匹配
  const regex = new RegExp(`^${regexPattern}$`, 's')
  return regex.test(command)
}
```

---

## 设计亮点（工程智慧）

### 1. 分层决策流水线（防御纵深）

系统采用多层检查，每层都有明确的职责：

```
规则层（强制）→ 模式层（可选）→ 交互层（兜底）

规则层: deny > ask > allow
模式层: bypassPermissions 跳过后续检查
交互层: 用户/Hook/分类器 多源竞速决策
```

**设计智慧**：这种分层确保了：
- **安全性**：危险操作（如修改 .git/）必须用户确认
- **灵活性**：用户可以设置规则减少重复确认
- **可扩展性**：新增检查逻辑只需添加新层

### 2. 原子竞争解决（并发安全）

当多个审批源同时响应时，`createResolveOnce` 确保只有一个生效：

```typescript
// 问题场景：用户点击"允许"的同时，分类器也返回"允许"
// 解决方案：claim() 是原子操作，先到先得

if (!claim()) return  // 如果已被认领，直接退出
resolveOnce(decision) // 否则认领并做决定
```

**设计智慧**：
- **避免冲突**：不会出现"双重批准"或"批准后又被拒绝"
- **简单高效**：用布尔标志实现，无需复杂锁机制
- **竞速公平**：所有审批源平等竞争，无优先级

### 3. 安全检查的绕过免疫

某些安全检查在任何模式下都必须执行：

```
┌─────────────────────────────────────────────────────────────┐
│                    绕过免疫的安全检查                          │
├─────────────────────────────────────────────────────────────┤
│  修改 .git/ 目录        → 必须用户确认                        │
│  修改 .claude/ 目录      → 必须用户确认                        │
│  修改 shell 配置文件     → 必须用户确认                        │
│  Windows 路径绕过尝试    → 必须用户确认                        │
│  跨机器 Bridge 消息      → 必须用户确认                        │
└─────────────────────────────────────────────────────────────┘
```

**设计智慧**：这些是"红线"，即使在 bypass 模式下也不能绕过，防止用户误操作导致严重后果。

### 4. 拒绝追踪的渐进式回退

Auto 模式下，如果 AI 分类器连续拒绝多次，系统会自动回退到用户确认模式：

```typescript
// 连续拒绝 3 次 → 回退到用户确认
// 总计拒绝 20 次 → 回退到用户确认

if (denialState.consecutiveDenials >= 3) {
  return { behavior: 'ask', message: '请手动审核...' }
}
if (denialState.totalDenials >= 20) {
  return { behavior: 'ask', message: '本会话已拒绝20次，请审核...' }
}
```

**设计智慧**：
- **防止失控**：AI 分类器可能误判，多次拒绝提示用户介入
- **渐进提醒**：先连续拒绝触发，后总数触发，给用户喘息空间
- **自动恢复**：成功批准后重置连续计数，避免误判累积

### 5. 功能门控的条件编译

使用 Bun 的 feature() 进行编译时优化：

```typescript
if (feature('TRANSCRIPT_CLASSIFIER')) {
  // Auto 模式逻辑只在启用时编译
}

if (feature('BASH_CLASSIFIER')) {
  // Bash 分类器逻辑只在启用时编译
}
```

**设计智慧**：
- **零开销**：未启用功能不会产生任何运行时开销
- **灵活部署**：不同用户群可以启用不同功能集
- **安全默认**：新功能默认关闭，减少意外行为

### 6. 多源审批的优雅降级

当某个审批源失败时，系统仍能工作：

```
Bridge 连接失败 → 本地对话框兜底
Channel 发送失败 → 本地对话框兜底
分类器 API 错误 → 根据配置拒绝或询问
Hook 执行失败 → 继续其他审批源
```

**设计智慧**：任何单点故障都不会阻塞整个流程，始终有本地对话框作为最终兜底。

---

## 完整示例：一次 Bash 命令的权限检查

假设 Claude 想执行 `npm install lodash`：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    权限检查完整示例                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: tool=Bash, input={command: "npm install lodash"}              │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  Step 1a: 检查整工具拒绝规则                                          │
│           denyRules 中有 "Bash" 吗？                                  │
│           → 没有，继续                                                │
│                                                                      │
│  Step 1b: 检查整工具询问规则                                          │
│           askRules 中有 "Bash" 吗？                                   │
│           → 没有，继续                                                │
│                                                                      │
│  Step 1c: Bash.checkPermissions()                                    │
│           检查子命令 "npm install lodash"                            │
│           → 检查 allowRules 中是否有匹配规则                          │
│           → 有 "npm:*" 前缀规则                                       │
│           → 返回 {behavior: 'allow', reason: 'npm:*'}               │
│                                                                      │
│  Step 2b: 整工具允许规则检查                                          │
│           → 上一步已有匹配，直接返回                                   │
│                                                                      │
│  输出: {behavior: 'allow', reason: 'rule: npm:*'}                    │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  结果: 命令直接执行，无需用户确认                                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**如果没有匹配规则**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    无匹配规则的示例                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  输入: tool=Bash, input={command: "rm -rf node_modules"}             │
│                                                                      │
│  Step 1-2: 所有规则检查都不匹配                                       │
│           → 返回 {behavior: 'ask', suggestions: ['Bash(rm:*)']}      │
│                                                                      │
│  Step 4: 5路竞速                                                     │
│           ┌─ 本地对话框弹出："是否执行 rm -rf node_modules?"          │
│           │                                                          │
│           ├─ Bridge 发送请求到 Web UI                                │
│           ├─ Channel 发送消息到 Telegram                             │
│           ├─ Hook 异步运行 PermissionRequest                         │
│           └─ 分类器异步评估命令安全性                                  │
│                                                                      │
│           用户点击"允许 + 永久放行 rm:*"                              │
│           → claim() 成功                                             │
│           → resolveOnce({allow, saveRule: 'rm:*'})                   │
│                                                                      │
│  输出: {behavior: 'allow', savedRule: 'Bash(rm:*)'}                  │
│                                                                      │
│  ────────────────────────────────────────────────────────────────── │
│  后续效果: 下次执行 rm 命令将自动放行                                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 文件路径索引

### 类型定义层
- `src/types/permissions.ts` - 纯类型定义，避免循环依赖

### 权限模式
- `src/utils/permissions/PermissionMode.ts` - 模式定义与配置
- `src/utils/permissions/getNextPermissionMode.ts` - Shift+Tab 模式切换逻辑

### 权限规则
- `src/utils/permissions/PermissionRule.ts` - 规则类型定义
- `src/utils/permissions/permissionRuleParser.ts` - 规则字符串解析器
- `src/utils/permissions/shellRuleMatching.ts` - Shell 命令规则匹配（精确/前缀/通配符）

### 权限决策核心
- `src/utils/permissions/permissions.ts` - **核心决策函数 hasPermissionsToUseTool**
- `src/utils/permissions/PermissionResult.ts` - 决策结果类型
- `src/utils/permissions/PermissionUpdate.ts` - 权限更新应用逻辑
- `src/utils/permissions/PermissionUpdateSchema.ts` - 更新操作类型定义

### 分类器系统
- `src/utils/permissions/bashClassifier.ts` - Bash 命令安全分类器
- `src/utils/permissions/yoloClassifier.ts` - Auto 模式 AI 分类器
- `src/utils/permissions/classifierDecision.ts` - 分类器决策辅助函数

### Hook 集成层
- `src/hooks/toolPermission/PermissionContext.ts` - **createResolveOnce 原子竞争解决**
- `src/hooks/toolPermission/handlers/interactiveHandler.ts` - **交互式主代理（5路竞速）**
- `src/hooks/toolPermission/handlers/coordinatorHandler.ts` - 协调器工作器处理器
- `src/hooks/toolPermission/handlers/swarmWorkerHandler.ts` - 群体工作器处理器
- `src/hooks/toolPermission/permissionLogging.ts` - 权限决策日志记录

### 安全与验证
- `src/utils/permissions/dangerousPatterns.ts` - 危险命令模式检测
- `src/utils/permissions/denialTracking.ts` - 拒绝追踪（Auto 模式回退）
- `src/utils/permissions/pathValidation.ts` - 路径安全验证

### UI 组件
- `src/components/permissions/PermissionRequest.tsx` - 权限请求对话框组件

---

## 总结

Claude Code 的权限系统是一个精心设计的多层安全框架：

| 特性 | 实现方式 | 效果 |
|------|---------|------|
| **防御纵深** | 14步流水线检查 | 多层保障，无单点失效 |
| **并发安全** | createResolveOnce 原子竞争 | 多审批源无冲突 |
| **绕过免疫** | safetyCheck 强制执行 | 关键路径永不跳过 |
| **渐进回退** | 拒绝追踪计数 | AI 失误时用户介入 |
| **优雅降级** | 多源审批兜底 | 任何故障都有备选 |
| **零开销** | feature() 条件编译 | 未启用功能无成本 |

这个系统在安全性和用户体验之间找到了精妙的平衡——既保护用户免受危险操作，又通过规则、模式、分类器减少不必要的打扰。