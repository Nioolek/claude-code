# Claude Code 权限系统深度分析报告

## 模块概述

Claude Code 的权限系统是一个多层、多源、异步决策的安全框架，负责在工具执行前进行权限检查。系统采用分层架构：

- **类型定义层** (`src/types/permissions.ts`)：纯类型定义，避免循环依赖
- **核心逻辑层** (`src/utils/permissions/`)：权限规则解析、匹配、持久化
- **Hook 集成层** (`src/hooks/toolPermission/`)：权限请求处理器与 UI 集成

---

## 核心组件分析

### 1. 权限模式 (PermissionMode)

系统定义了 6 种权限模式：

| 模式 | 说明 | UI 符号 |
|------|------|---------|
| `default` | 默认模式，每个工具都需确认 | 无 |
| `plan` | 计划模式，只读操作 | 暂停图标 |
| `acceptEdits` | 自动接受编辑操作 | ⏵⏵ |
| `bypassPermissions` | 绕过所有权限检查（危险） | ⏵⏵ |
| `dontAsk` | 不询问直接拒绝 | ⏵⏵ |
| `auto` | AI 分类器自动决策 | ⏵⏵ |

**模式切换逻辑**：
```
Shift+Tab 循环切换顺序：
default -> acceptEdits -> plan -> bypassPermissions -> auto -> default
```

### 2. 权限决策流程

权限决策有 4 种行为：

```typescript
type PermissionBehavior = 'allow' | 'deny' | 'ask' | 'passthrough'

type PermissionDecision<Input> =
  | PermissionAllowDecision<Input>  // { behavior: 'allow', updatedInput? }
  | PermissionAskDecision<Input>    // { behavior: 'ask', message, suggestions? }
  | PermissionDenyDecision          // { behavior: 'deny', message }
```

### 3. 权限规则系统

**规则格式**:
```
ToolName                    // 工具级别规则
ToolName(ruleContent)       // 内容级别规则
ToolName(prefix:*)          // 前缀匹配
ToolName(wild*card)         // 通配符匹配
```

**Shell 规则匹配**:
```typescript
type ShellPermissionRule =
  | { type: 'exact'; command: string }      // 精确匹配
  | { type: 'prefix'; prefix: string }      // 前缀匹配
  | { type: 'wildcard'; pattern: string }   // 通配符匹配
```

### 4. 多源竞争决策机制

权限检查的核心流程：

```
┌─────────────────────────────────────────────────────────────┐
│                    权限检查决策流水线                          │
├─────────────────────────────────────────────────────────────┤
│ 1. getDenyRuleForTool        → 整工具拒绝规则              │
│ 2. getAskRuleForTool         → 整工具询问规则              │
│ 3. tool.checkPermissions()   → 工具自定义权限检查           │
│ 4. 内容级别规则检查                                         │
│ 5. 安全检查 (safetyCheck, 绕过免疫)                        │
│ 6. bypassPermissions 模式检查                               │
│ 7. toolAlwaysAllowedRule    → 整工具允许规则              │
│ 8. 模式后处理（dontAsk/auto）                               │
└─────────────────────────────────────────────────────────────┘
```

### 5. 权限处理器

系统提供 3 种权限处理器：

#### interactiveHandler（交互式主代理）

实现 **4 路竞速决策**：

```
路径 1: 本地用户交互 (ToolUseConfirm queue)
路径 2: Bridge 远程响应 (claude.ai Web UI)
路径 3: Channel 消息中继 (Telegram/iMessage)
路径 4: Hook 异步决策 (PermissionRequest hook)
路径 5: Bash 分类器自动批准
         ↓ 竞速获胜者 ↓
    createResolveOnce().claim()  // 原子竞争解决
```

#### coordinatorHandler（协调器工作器）

顺序等待 Hook 和分类器完成，然后回退到交互式对话框。

#### swarmWorkerHandler（群体工作器）

将权限请求通过 mailbox 转发给领导者，等待领导者响应。

### 6. Bash 分类器自动批准

```
┌─────────────────────────────────────────────────────────────┐
│                    Bash 分类器决策流程                        │
├─────────────────────────────────────────────────────────────┤
│ BASH_CLASSIFIER feature flag:                                │
│   - 异步运行，与用户交互竞速                                  │
│                                                              │
│ TRANSCRIPT_CLASSIFIER feature flag (Auto 模式):              │
│   - 同步运行（阻塞工具执行）                                  │
│   - 两阶段分类：fast (Haiku) → thinking (Sonnet)             │
└─────────────────────────────────────────────────────────────┘
```

---

## 设计亮点

### 1. createResolveOnce 原子竞争解决

```typescript
type ResolveOnce<T> = {
  resolve(value: T): void
  isResolved(): boolean
  claim(): boolean  // 原子检查并标记
}

// claim() 返回 true 表示赢得了竞争
if (!claim()) return  // 已有其他源响应，退出
```

### 2. 分层决策流水线

- **规则层**：deny > ask > allow 的优先级
- **模式层**：bypassPermissions > auto > dontAsk 的转换
- **异步层**：Hook 与分类器的竞速

### 3. 安全检查的绕过免疫

某些安全检查可以被分类器覆盖，而某些则必须用户确认。

### 4. 拒绝追踪的渐进式回退

Auto 模式下，连续 3 次拒绝或总计 20 次拒绝后，系统自动回退到用户确认模式。

### 5. 功能门控的条件编译

```typescript
if (feature('TRANSCRIPT_CLASSIFIER')) {
  // Auto 模式逻辑
}
```

---

## 文件路径索引

### 类型定义
- `src/types/permissions.ts` - 核心权限类型

### 权限模式
- `src/utils/permissions/PermissionMode.ts` - 模式定义与配置
- `src/utils/permissions/getNextPermissionMode.ts` - 模式切换逻辑

### 权限规则
- `src/utils/permissions/PermissionRule.ts` - 规则类型
- `src/utils/permissions/permissionRuleParser.ts` - 规则解析器
- `src/utils/permissions/shellRuleMatching.ts` - Shell 规则匹配

### 权限决策
- `src/utils/permissions/PermissionResult.ts` - 决策结果类型
- `src/utils/permissions/permissions.ts` - 核心决策逻辑

### 分类器
- `src/utils/permissions/bashClassifier.ts` - Bash 分类器
- `src/utils/permissions/yoloClassifier.ts` - Auto 模式分类器
- `src/utils/permissions/classifierDecision.ts` - 分类器决策辅助

### 处理器
- `src/hooks/toolPermission/PermissionContext.ts` - 权限上下文
- `src/hooks/toolPermission/handlers/interactiveHandler.ts` - 交互式处理器
- `src/hooks/toolPermission/handlers/coordinatorHandler.ts` - 协调器处理器
- `src/hooks/toolPermission/handlers/swarmWorkerHandler.ts` - 群体工作器处理器

### 安全与验证
- `src/utils/permissions/dangerousPatterns.ts` - 危险模式
- `src/utils/permissions/denialTracking.ts` - 拒绝追踪
- `src/utils/permissions/pathValidation.ts` - 路径验证

---

这份报告完整分析了 Claude Code 权限系统的架构、核心组件、决策流程和设计亮点。系统通过分层设计、多源竞速、原子竞争解决等机制，实现了既安全又灵活的权限控制。