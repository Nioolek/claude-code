# Claude Code 特性标志系统深度分析报告

## 1. 模块概述

Claude Code 使用 **Bun Runtime 的 `bun:bundle` feature() 函数**实现编译时死代码消除。这是一种独特的构建时特性标志机制，允许 Anthropic 在不同构建版本中控制功能的可用性。

**核心导入模式**:

```typescript
import { feature } from 'bun:bundle'
```

**典型使用模式**:

```typescript
// 条件导入 - 未启用时模块不会打包
const voiceCommand = feature('VOICE_MODE')
  ? require('./commands/voice/index.js').default
  : null

// 条件执行 - 正向三元模式确保字符串字面量被消除
return feature('BRIDGE_MODE')
  ? isClaudeAISubscriber() && getFeatureValue_CACHED_MAY_BE_STALE('tengu_ccr_bridge', false)
  : false
```

---

## 2. 特性标志完整清单

### 2.1 核心特性标志

| 标志名称 | 功能描述 | 主要使用位置 |
|---------|---------|------------|
| `PROACTIVE` | 主动模式 - 启用后台任务、自动执行 | `commands.ts`, `prompts.ts` |
| `KAIROS` | Assistant 模式核心 - 完整助手功能集 | 60+ 文件 |
| `BRIDGE_MODE` | Remote Control (IDE远程控制) | `bridge/` |
| `DAEMON` | 后台守护进程模式 | `commands.ts` |
| `VOICE_MODE` | 语音交互模式 | `voice/` |
| `COORDINATOR_MODE` | 多Agent协调模式 | `coordinator/` |

### 2.2 KAIROS 家族标志

| 标志名称 | 功能描述 |
|---------|---------|
| `KAIROS` | 主标志 - Assistant 模式完整功能 |
| `KAIROS_BRIEF` | BriefTool 快速通知功能 |
| `KAIROS_CHANNELS` | MCP 频道通知功能 |
| `KAIROS_PUSH_NOTIFICATION` | 推送通知工具 |
| `KAIROS_GITHUB_WEBHOOKS` | GitHub PR webhook订阅 |
| `KAIROS_DREAM` | 梦境/记忆整合功能 |

### 2.3 权限/安全相关标志

| 标志名称 | 功能描述 |
|---------|---------|
| `TRANSCRIPT_CLASSIFIER` | Auto Mode - AI驱动权限决策 |
| `BASH_CLASSIFIER` | Bash命令AI分类器 |

### 2.4 其他功能标志

| 标志名称 | 功能描述 |
|---------|---------|
| `HISTORY_SNIP` | 历史/对话裁剪压缩 |
| `AGENT_TRIGGERS` | Agent定时触发器 |
| `WORKFLOW_SCRIPTS` | 工作流脚本执行 |
| `EXPERIMENTAL_SKILL_SEARCH` | 实验性技能搜索 |
| `TEAMMEM` | 团队记忆共享 |
| `MONITOR_TOOL` | 监控工具 |
| `CONNECTOR_TEXT` | 连接器文本摘要Beta |
| `FORK_SUBAGENT` | Fork子Agent功能 |

---

## 3. 核心组件分析

### 3.1 特性标志条件导入机制

**位置**: `src/commands.ts`

```typescript
// Dead code elimination: conditional imports
const proactive =
  feature('PROACTIVE') || feature('KAIROS')
    ? require('./commands/proactive.js').default
    : null

const briefCommand =
  feature('KAIROS') || feature('KAIROS_BRIEF')
    ? require('./commands/brief.js').default
    : null

const bridge = feature('BRIDGE_MODE')
  ? require('./commands/bridge/index.js').default
  : null

const voiceCommand = feature('VOICE_MODE')
  ? require('./commands/voice/index.js').default
  : null
```

**设计要点**：
- 使用 `require()` 而非 ES `import` 实现真正的条件加载
- 未启用的功能模块完全不会打包
- 多标志组合使用 OR (`||`) 和 AND (`&&`) 逻辑

### 3.2 工具集条件注册

**位置**: `src/tools.ts`

```typescript
const SleepTool =
  feature('PROACTIVE') || feature('KAIROS')
    ? require('./tools/SleepTool/SleepTool.js').SleepTool
    : null

const cronTools = feature('AGENT_TRIGGERS')
  ? [
      require('./tools/ScheduleCronTool/CronCreateTool.js').CronCreateTool,
      require('./tools/ScheduleCronTool/CronDeleteTool.js').CronDeleteTool,
      require('./tools/ScheduleCronTool/CronListTool.js').CronListTool,
    ]
  : []
```

### 3.3 正向三元模式 (Positive Ternary Pattern)

**位置**: `src/bridge/bridgeEnabled.ts`

```typescript
/**
 * The `feature('BRIDGE_MODE')` guard ensures the GrowthBook string literal
 * is only referenced when bridge mode is enabled at build time.
 */
export function isBridgeEnabled(): boolean {
  // Positive ternary pattern — 反向模式不会消除字符串字面量
  return feature('BRIDGE_MODE')
    ? isClaudeAISubscriber() &&
        getFeatureValue_CACHED_MAY_BE_STALE('tengu_ccr_bridge', false)
    : false
}
```

**关键设计原则**：
- 必须使用正向三元 (`return feature('X') ? value : false`)
- 反向模式 (`if (!feature('X')) return`) 不会消除外部构建中的字符串
- 防止敏感信息（如 GrowthBoard 标志名称）泄露到外部构建

### 3.4 Auto Mode 分类器系统

**位置**: `src/utils/permissions/yoloClassifier.ts`

```typescript
const BASE_PROMPT: string = feature('TRANSCRIPT_CLASSIFIER')
  ? txtRequire(require('./yolo-classifier-prompts/auto_mode_system_prompt.txt'))
  : ''

const EXTERNAL_PERMISSIONS_TEMPLATE: string = feature('TRANSCRIPT_CLASSIFIER')
  ? txtRequire(require('./yolo-classifier-prompts/permissions_external.txt'))
  : ''
```

Auto Mode (TRANSCRIPT_CLASSIFIER) 是 Claude Code 的智能权限决策系统：
- 使用 AI 分类器自动判断工具调用是否应该被允许
- 减少用户手动审批的交互次数

### 3.5 Voice Mode 实现

**位置**: `src/voice/voiceModeEnabled.ts`

```typescript
export function isVoiceGrowthBookEnabled(): boolean {
  return feature('VOICE_MODE')
    ? !getFeatureValue_CACHED_MAY_BE_STALE('tengu_amber_quartz_disabled', false)
    : false
}

export function isVoiceModeEnabled(): boolean {
  return hasVoiceAuth() && isVoiceGrowthBookEnabled()
}
```

Voice Mode 需要：
1. 构建标志 `VOICE_MODE` 启用
2. Anthropic OAuth 认证
3. GrowthBoard Kill-switch 未触发

---

## 4. 特性标志组合模式

### 4.1 PROACTIVE | KAIROS 组合

```typescript
const proactive = feature('PROACTIVE') || feature('KAIROS')
  ? require('./commands/proactive.js').default
  : null
```

**含义**: KAIROS 模式是 PROACTIVE 功能的超集。

### 4.2 DAEMON && BRIDGE_MODE 组合

```typescript
const remoteControlServerCommand =
  feature('DAEMON') && feature('BRIDGE_MODE')
    ? require('./commands/remoteControlServer/index.js').default
    : null
```

**含义**: Remote Control Server 需要同时启用两个特性。

---

## 5. 条件编译逻辑深度分析

### 5.1 Dead Code Elimination 工作原理

Bun 的 `feature()` 在**构建时**被评估：
- 如果 `feature('FLAG')` 返回 `false`，整个条件分支被移除
- 相关模块的 `require()` 不会被打包
- 字符串字面量、导入语句都被消除

**示例**：

```typescript
// 构建前
const BASE_PROMPT: string = feature('TRANSCRIPT_CLASSIFIER')
  ? require('./prompt.txt')
  : ''

// 外部构建后 (feature('TRANSCRIPT_CLASSIFIER') = false)
const BASE_PROMPT: string = ''
```

### 5.2 内部 vs 外部构建

| 特性 | 内部构建 | 外部构建 |
|-----|---------|---------|
| PROACTIVE | 可能启用 | 通常禁用 |
| KAIROS | 启用 | 禁用 |
| BRIDGE_MODE | 启用 | 部分启用 |
| VOICE_MODE | 启用 | 启用 |
| TRANSCRIPT_CLASSIFIER | 启用 | 禁用 |
| COORDINATOR_MODE | 启用 | 禁用 |

### 5.3 运行时检查模式

```typescript
function checkFeature(): boolean {
  // 1. 构建标志 - 控制代码是否存在
  if (!feature('X')) return false

  // 2. 环境变量 - 用户运行时配置
  if (!isEnvTruthy(process.env.CLAUDE_CODE_X)) return false

  // 3. GrowthBoard标志 - 组织/用户级别权限
  if (!getFeatureValue_CACHED_MAY_BE_STALE('tengu_x', false)) return false

  return true
}
```

---

## 6. Beta Headers 与特性标志关联

**位置**: `src/constants/betas.ts`

```typescript
export const SUMMARIZE_CONNECTOR_TEXT_BETA_HEADER = feature('CONNECTOR_TEXT')
  ? 'summarize-connector-text-2026-03-13'
  : ''

export const AFK_MODE_BETA_HEADER = feature('TRANSCRIPT_CLASSIFIER')
  ? 'afk-mode-2026-01-31'
  : ''
```

**设计要点**：
- Beta Headers 用于启用 API 端点的实验性功能
- 未启用时返回空字符串，API 不会收到该 Beta 请求

---

## 7. 设计亮点

### 7.1 零运行时开销
- 未启用功能的代码完全从构建中移除
- 无条件判断开销，无额外内存占用

### 7.2 安全性设计
- 正向三元模式防止敏感字符串泄露
- GrowthBoard 标志名称不会出现在外部构建

### 7.3 模块隔离
- 条件 `require()` 避免循环依赖
- 每个特性有独立的状态模块

### 7.4 灵活组合
- OR 组合实现功能超集
- AND 组合实现功能依赖
- 家族标志实现功能模块化

---

## 8. 关键文件路径索引

| 文件路径 | 功能描述 |
|---------|---------|
| `src/commands.ts` | 命令条件注册中心 |
| `src/tools.ts` | 工具条件注册中心 |
| `src/bridge/bridgeEnabled.ts` | Bridge Mode 运行时检查 |
| `src/voice/voiceModeEnabled.ts` | Voice Mode 运行时检查 |
| `src/coordinator/coordinatorMode.ts` | Coordinator Mode 实现 |
| `src/bootstrap/state.ts` | 运行时状态管理 |
| `src/utils/permissions/yoloClassifier.ts` | Auto Mode 分类器 |
| `src/utils/permissions/autoModeState.ts` | Auto Mode 状态 |
| `src/constants/betas.ts` | Beta Headers 定义 |

---

## 9. 总结

Claude Code 的特性标志系统是 Bun Runtime 独特能力的典型应用：

1. **编译时消除**：代码在构建阶段被物理移除
2. **分层控制**：构建标志 → 环境变量 → GrowthBoard标志
3. **安全设计**：正向三元模式确保敏感信息不泄露
4. **模块化家族**：KAIROS 等主标志有子标志家族
5. **零开销**：外部用户不会为未使用功能付出任何性能代价

这套系统使得 Anthropic 可以：
- 在内部快速迭代实验性功能
- 安全地发布稳定版本
- 灵活控制不同用户/组织的能力范围