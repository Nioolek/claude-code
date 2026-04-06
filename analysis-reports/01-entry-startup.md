# Claude Code 入口与启动流程深度解读报告

## 模块概述

入口与启动模块是 Claude Code 的「点火系统」，就像**一辆汽车的启动流程**——从插入钥匙（执行命令）到引擎启动（REPL 就绪），每个步骤都经过精心优化以确保极速启动。

### 核心职责

1. **CLI 参数解析**：基于 Commander.js 的类型安全命令行解析
2. **启动流程编排**：初始化、配置加载、权限设置的顺序控制
3. **模式分支处理**：交互式 REPL、非交互式 print、SSH 远程等多种模式
4. **性能优化**：并行预取、懒加载、编译时死代码消除

### 生活化类比

| 概念 | 类比 | 说明 |
|------|------|------|
| `main.tsx` | 汽车点火钥匙 | 整个系统的入口点 |
| `startMdmRawRead()` | 预热发动机 | 在导入期间并行启动子进程 |
| `startKeychainPrefetch()` | 预热油路 | 并行读取 macOS 钥匙串 |
| `init()` | 自检系统 | 初始化所有必要服务 |
| `setup()` | 安全检查 | 验证权限、设置工作目录 |
| `launchRepl()` | 挂挡起步 | 启动交互式会话 |

---

## 启动流程全景图

### 完整启动时序

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Phase 1: 模块评估阶段 (同步)                               │
│                    时间: ~135ms                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 1. profileCheckpoint('main_tsx_entry')                                 │  │
│  │    → 记录启动起点                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 2. startMdmRawRead() ─────────────────────────────┐                   │  │
│  │    macOS: plutil 读取 MDM 配置                     │                   │  │
│  │    Windows: reg query 注册表                       ├─► 子进程并行      │  │
│  │    耗时: ~20ms                                    │   与后续导入      │  │
│  └───────────────────────────────────────────────────┘                   │  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 3. startKeychainPrefetch() ───────────────────────┐                   │  │
│  │    macOS: 两个 security 子进程                     │                   │  │
│  │    - OAuth 凭证读取                               ├─► 并行执行        │  │
│  │    - Legacy API key 读取                          │   耗时: ~65ms    │  │
│  └───────────────────────────────────────────────────┘                   │  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 4. 大量静态导入 (~135ms)                                                │  │
│  │    - React, Ink, Commander, Zod                                       │  │
│  │    - 服务模块 (api, mcp, oauth)                                        │  │
│  │    - 工具模块 (tools, commands)                                        │  │
│  │    - 条件导入 (feature flags)                                          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 5. profileCheckpoint('main_tsx_imports_loaded')                        │  │
│  │    → 模块加载完成，子进程结果应已就绪                                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Phase 2: main() 函数                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Windows 安全环境变量设置                                             │  │
│  │    setShellIfWindows()                                                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 2. 初始化警告处理器                                                     │  │
│  │    initializeWarningHandler()                                          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 3. 参数重写处理                                                         │  │
│  │    - 深链接参数 (--deep-link-*)                                        │  │
│  │    - SSH 远程模式                                                       │  │
│  │    - Assistant 模式                                                     │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 4. 模式检测                                                             │  │
│  │    hasPrintFlag = -p/--print                                           │  │
│  │    hasInitOnlyFlag = --init-only                                       │  │
│  │    hasSdkUrl = --sdk-url                                               │  │
│  │    isNonInteractive = 打印模式 || 无 TTY                               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 5. 客户端类型检测                                                       │  │
│  │    clientType = cli/sdk-typescript/sdk-python/github-action/...       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 6. eagerLoadSettings()                                                 │  │
│  │    解析 --settings/--setting-sources 参数                              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 7. await run()                                                         │  │
│  │    进入 Commander.js 命令解析                                          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Phase 3: run() → preAction 钩子                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ program.hook('preAction', async () => {                                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 1. await Promise.all([                                                 │  │
│  │      ensureMdmSettingsLoaded(),      // 等待 MDM 子进程完成            │  │
│  │      ensureKeychainPrefetchCompleted() // 等待钥匙串读取完成           │  │
│  │    ])                                                                  │  │
│  │    → 几乎零等待（子进程已在导入期间完成）                               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 2. await init()                                                        │  │
│  │    → 初始化所有服务（详见下节）                                         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 3. initSinks()                                                         │  │
│  │    → 初始化日志接收器                                                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 4. runMigrations()                                                     │  │
│  │    → 运行数据迁移                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 5. void loadRemoteManagedSettings()  // 非阻塞                         │  │
│  │    void loadPolicyLimits()            // 非阻塞                         │  │
│  │    → 企业设置后台加载                                                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    │                                           │
                    ▼                                           ▼
┌───────────────────────────────┐         ┌───────────────────────────────┐
│       交互式模式               │         │      非交互式模式            │
│   (!isNonInteractiveSession)   │         │   (isNonInteractiveSession)  │
├───────────────────────────────┤         ├───────────────────────────────┤
│                               │         │                               │
│ 1. createRoot() (React)       │         │ 1. applyConfigEnvironmentVars│
│                               │         │                               │
│ 2. showSetupScreens()         │         │ 2. initializeTelemetry       │
│    ├─ TrustDialog (信任确认)   │         │                               │
│    ├─ Onboarding (引导流程)   │         │ 3. processSessionStartHooks  │
│    ├─ ApproveApiKey           │         │                               │
│    └─ 各种确认对话框           │         │ 4. connectMcpBatch()         │
│                               │         │                               │
│ 3. 初始化 LSP 管理器           │         │ 5. runHeadless()             │
│                               │         │    └─ cli/print.js          │
│ 4. 预取 MCP 资源               │         │                               │
│                               │         │                               │
│ 5. 创建初始状态                │         │                               │
│                               │         │                               │
│ 6. launchRepl()               │         │                               │
│    └─ 渲染 REPL.tsx           │         │                               │
│                               │         │                               │
│ 7. startDeferredPrefetches()  │         │                               │
│                               │         │                               │
└───────────────────────────────┘         └───────────────────────────────┘
```

---

## 核心概念详解

### 1. 并行预取模式（Parallel Prefetch）

**生活类比**：在等电梯的时候顺便查手机通知

并行预取是启动性能优化的关键设计。在模块评估阶段（同步），系统同时启动两个子进程：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    并行预取时序图                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  时间轴 ────────────────────────────────────────────────────────────────►    │
│                                                                              │
│  T=0ms    ┌─────────────────────────────────────────────────────────────┐   │
│           │ startMdmRawRead() 启动                                       │   │
│           │ macOS: spawn('plutil', ...)                                  │   │
│           │ Windows: spawn('reg', ...)                                   │   │
│           └─────────────────────────────┬───────────────────────────────┘   │
│                                         │ 子进程运行中...                     │
│  T=0ms    ┌─────────────────────────────────────────────────────────────┐   │
│           │ startKeychainPrefetch() 启动                                 │   │
│           │ macOS: spawn('security', ...) x2                             │   │
│           └─────────────────────────────┬───────────────────────────────┘   │
│                                         │ 子进程运行中...                     │
│                                                                              │
│  T=0-135ms  ┌───────────────────────────────────────────────────────────┐   │
│             │ 模块导入（同步）                                           │   │
│             │ - React, Ink, Commander                                   │   │
│             │ - 60+ 工具模块                                             │   │
│             │ - 服务模块                                                 │   │
│             └───────────────────────────────────────────────────────────┘   │
│                                         │                                   │
│  T=20ms     ◄───────────────────────────┘ MDM 子进程完成                   │
│                                                                              │
│  T=65ms     ◄───────────────────────────┘ Keychain 子进程完成               │
│                                                                              │
│  T=135ms    模块导入完成                                                    │
│             子进程结果已就绪（几乎零等待）                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**性能收益**：
- MDM 设置读取：~20ms（与导入并行，节省 ~20ms）
- Keychain 读取：~65ms（原本串行，现在并行，节省 ~65ms）

### 2. init() 初始化流程

**生活类比**：汽车启动前的自检系统

`init()` 函数负责初始化所有必要的服务，采用 `memoize` 确保只执行一次：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    init() 初始化步骤                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 1: enableConfigs()                                                │  │
│  │         启用配置系统                                                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 2: applySafeConfigEnvironmentVariables()                          │  │
│  │         应用安全环境变量（信任对话框前）                                 │  │
│  │         applyExtraCACertsFromConfig()                                  │  │
│  │         应用 TLS 证书（Bun 启动前必须）                                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 3: setupGracefulShutdown()                                        │  │
│  │         设置优雅关闭处理器                                              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 4: void Promise.all([                                             │  │
│  │           import('firstPartyEventLogger'),                             │  │
│  │           import('growthbook')                                         │  │
│  │         ])  // 懒加载 OpenTelemetry                                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 5: void populateOAuthAccountInfoIfNeeded()                        │  │
│  │         填充 OAuth 账户信息                                             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 6: void initJetBrainsDetection()                                  │  │
│  │         JetBrains IDE 检测                                              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 7: initializeRemoteManagedSettingsLoadingPromise()                │  │
│  │         初始化远程设置加载 Promise（企业用户）                          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 8: configureGlobalMTLS()                                          │  │
│  │         配置全局 mTLS 设置                                              │  │
│  │         configureGlobalAgents()                                        │  │
│  │         配置全局 HTTP 代理                                              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 9: preconnectAnthropicApi()                                       │  │
│  │         预连接 Anthropic API（TCP+TLS 握手）                            │  │
│  │         与业务逻辑并行执行                                              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Step 10: await ensureScratchpadDir()                                   │  │
│  │          初始化 scratchpad 目录（如果启用）                             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. 特性标志系统（Feature Flags）

**生活类比**：汽车的可选配置包

Claude Code 使用 Bun 的 `bun:bundle` feature() 实现编译时死代码消除：

```typescript
// 编译时条件导入
const coordinatorModeModule = feature('COORDINATOR_MODE')
  ? require('./coordinator/coordinatorMode.js')
  : null;

const assistantModule = feature('KAIROS')
  ? require('./assistant/index.js')
  : null;
```

**关键特性标志**：

| 标志 | 功能 | 说明 |
|------|------|------|
| `PROACTIVE` | 主动模式 | 后台任务自动执行 |
| `KAIROS` | Assistant 模式 | Claude AI 助手 |
| `BRIDGE_MODE` | IDE Bridge | VS Code/JetBrains 集成 |
| `DAEMON` | 守护进程 | 后台服务模式 |
| `VOICE_MODE` | 语音模式 | 语音交互 |
| `COORDINATOR_MODE` | 协调器 | 多代理协调 |
| `SSH_REMOTE` | SSH 远程 | 远程会话代理 |
| `UDS_INBOX` | Unix Socket | 进程间消息 |

### 4. 运行模式矩阵

| 模式 | 触发条件 | 特点 | 安全边界 |
|------|----------|------|----------|
| **交互式 REPL** | 默认 | 完整 TUI，信任对话框 | 需确认工作区信任 |
| **Print 模式** | `-p/--print` | 跳过信任对话框，单次查询 | 跳过信任确认 |
| **SDK 模式** | `--sdk-url` | 流式 JSON I/O | 无交互 UI |
| **SSH 模式** | `claude ssh <host>` | 远程会话代理 | 远程信任 |
| **Bare 模式** | `--bare` | 最小化启动 | 无预取/无 OAuth |

---

## 关键代码解读

### 1. 并行预取实现

```typescript
// src/main.tsx:1-20

// 这些副作用必须在所有其他导入之前执行：
// 1. profileCheckpoint 在重型模块评估开始前标记入口点
// 2. startMdmRawRead 启动 MDM 子进程（plutil/reg query）
//    使其与后续 ~135ms 的导入并行运行
// 3. startKeychainPrefetch 启动两个 macOS 钥匙串读取
//    否则会通过 sync spawn 串行读取（每次 ~65ms）

import { profileCheckpoint } from './utils/startupProfiler.js';

// 记录入口点
profileCheckpoint('main_tsx_entry');

import { startMdmRawRead } from './utils/settings/mdm/rawRead.js';
// 立即启动 MDM 子进程（不等待）
startMdmRawRead();

import { startKeychainPrefetch } from './utils/secureStorage/keychainPrefetch.js';
// 立即启动钥匙串预取（不等待）
startKeychainPrefetch();
```

### 2. Commander.js preAction 钩子

```typescript
// src/main.tsx:907-967

// preAction 钩子在命令执行前运行初始化
// 只在执行命令时运行，显示帮助时跳过
program.hook('preAction', async thisCommand => {
  profileCheckpoint('preAction_start');

  // 等待模块评估阶段启动的子进程完成
  // 几乎零等待 —— 子进程在 ~135ms 的导入期间已完成
  await Promise.all([
    ensureMdmSettingsLoaded(),      // MDM 设置加载
    ensureKeychainPrefetchCompleted() // 钥匙串读取完成
  ]);
  profileCheckpoint('preAction_after_mdm');

  // 初始化所有服务
  await init();
  profileCheckpoint('preAction_after_init');

  // 设置进程标题
  if (!isEnvTruthy(process.env.CLAUDE_CODE_DISABLE_TERMINAL_TITLE)) {
    process.title = 'claude';
  }

  // 初始化日志接收器
  const { initSinks } = await import('./utils/sinks.js');
  initSinks();
  profileCheckpoint('preAction_after_sinks');

  // 运行数据迁移
  runMigrations();
  profileCheckpoint('preAction_after_migrations');

  // 企业设置后台加载（非阻塞）
  void loadRemoteManagedSettings();
  void loadPolicyLimits();
});
```

### 3. init() 核心逻辑

```typescript
// src/entrypoints/init.ts:57-150

export const init = memoize(async (): Promise<void> => {
  const initStartTime = Date.now();
  logForDiagnosticsNoPII('info', 'init_started');
  profileCheckpoint('init_function_start');

  // 1. 启用配置系统
  enableConfigs();
  profileCheckpoint('init_configs_enabled');

  // 2. 应用安全环境变量（信任对话框前）
  // 完整环境变量在信任建立后应用
  applySafeConfigEnvironmentVariables();

  // 应用 NODE_EXTRA_CA_CERTS（TLS 握手前）
  // Bun 通过 BoringSSL 缓存 TLS 证书存储，必须在首次 TLS 握手前
  applyExtraCACertsFromConfig();
  profileCheckpoint('init_safe_env_vars_applied');

  // 3. 设置优雅关闭
  setupGracefulShutdown();
  profileCheckpoint('init_after_graceful_shutdown');

  // 4. 初始化 1P 事件日志（懒加载避免启动开销）
  void Promise.all([
    import('../services/analytics/firstPartyEventLogger.js'),
    import('../services/analytics/growthbook.js'),
  ]).then(([fp, gb]) => {
    fp.initialize1PEventLogging();
    // 配置变更时重建 logger
    gb.onGrowthBookRefresh(() => {
      void fp.reinitialize1PEventLoggingIfConfigChanged();
    });
  });

  // 5. 填充 OAuth 账户信息
  void populateOAuthAccountInfoIfNeeded();

  // 6. JetBrains IDE 检测（填充缓存）
  void initJetBrainsDetection();

  // 7. GitHub 仓库检测（填充缓存）
  void detectCurrentRepository();

  // 8. 初始化远程设置加载 Promise
  if (isEligibleForRemoteManagedSettings()) {
    initializeRemoteManagedSettingsLoadingPromise();
  }

  // 9. 配置全局 mTLS 和代理
  configureGlobalMTLS();
  configureGlobalAgents();

  // 10. 预连接 Anthropic API（TCP+TLS 握手并行）
  preconnectAnthropicApi();
});
```

### 4. setup() 会话设置

```typescript
// src/setup.ts:56-150

export async function setup(
  cwd: string,
  permissionMode: PermissionMode,
  allowDangerouslySkipPermissions: boolean,
  worktreeEnabled: boolean,
  // ...
): Promise<void> {
  logForDiagnosticsNoPII('info', 'setup_started');

  // 1. Node.js 版本检查
  const nodeVersion = process.version.match(/^v(\d+)\./)?.[1];
  if (!nodeVersion || parseInt(nodeVersion) < 18) {
    console.error('Error: Claude Code requires Node.js version 18 or higher.');
    process.exit(1);
  }

  // 2. UDS 消息服务器启动（特性门控）
  if (feature('UDS_INBOX')) {
    const m = await import('./utils/udsMessaging.js');
    await m.startUdsMessaging(messagingSocketPath ?? m.getDefaultUdsSocketPath());
  }

  // 3. 终端备份恢复（交互式会话）
  if (!getIsNonInteractiveSession()) {
    await checkAndRestoreITerm2Backup();
    await checkAndRestoreTerminalBackup();
  }

  // 4. 设置工作目录
  setCwd(cwd);

  // 5. 捕获 hooks 配置快照（安全审计）
  captureHooksConfigSnapshot();

  // 6. Worktree 创建（如果启用）
  if (worktreeEnabled) {
    const worktreeSession = await createWorktreeForSession(...);
    process.chdir(worktreeSession.worktreePath);
  }

  // 7. 后台任务初始化
  initSessionMemory();
  void lockCurrentVersion();

  // 8. 预取（非阻塞）
  void getCommands(getProjectRoot());
  void import('./utils/plugins/loadPluginHooks.js');
}
```

---

## 设计亮点

### 1. 性能优化策略

| 技术 | 实现位置 | 收益 | 生活类比 |
|------|----------|------|----------|
| **并行预取** | `main.tsx:12-20` | 节省 ~85ms | 等电梯时查通知 |
| **懒加载** | `init.ts` 动态 import | 延迟 ~400KB | 用到再买 |
| **API 预连接** | `init.ts:preconnectAnthropicApi` | TCP+TLS 并行 | 提前热车 |
| **memoize 缓存** | `init()` 函数 | 防止重复执行 | 单例模式 |
| **setImmediate 延迟** | `setup.ts` | 非关键任务后置 | 先做重要的事 |

### 2. 安全设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      安全边界设计                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 信任边界 (TrustDialog)                                                 │  │
│  │                                                                        │  │
│  │ showSetupScreens()                                                     │  │
│  │   → TrustDialog                                                        │  │
│  │   → 确认工作区信任                                                      │  │
│  │   → 任何代码执行前                                                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 权限验证 (bypassPermissions)                                           │  │
│  │                                                                        │  │
│  │ 仅允许在沙箱环境中使用：                                                │  │
│  │   - Docker 容器                                                        │  │
│  │   - 无网络访问                                                         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Hooks 快照 (captureHooksConfigSnapshot)                                │  │
│  │                                                                        │  │
│  │ 防止运行时 hooks 配置被篡改                                             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 环境变量分阶段应用                                                      │  │
│  │                                                                        │  │
│  │ applySafeConfigEnvironmentVariables()  → 信任对话框前                  │  │
│  │ applyConfigEnvironmentVariables()       → 信任对话框后                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. 启动性能分析器

```typescript
// src/utils/startupProfiler.ts

// 性能检查点记录
profileCheckpoint('main_tsx_entry');
profileCheckpoint('main_tsx_imports_loaded');
profileCheckpoint('init_function_start');
profileCheckpoint('preAction_start');
// ...

// 最终报告
profileReport();  // 输出启动时序分析
```

---

## 模块交互关系

```
                    ┌─────────────────┐
                    │   main.tsx      │
                    │   (入口点)       │
                    │                 │
                    │ • 参数解析      │
                    │ • 模式检测      │
                    │ • 并行预取      │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   init.ts       │ │   setup.ts      │ │   commands/     │
│   (初始化)       │ │   (会话设置)    │ │   (子命令)      │
│                 │ │                 │ │                 │
│ • 配置系统      │ │ • Node 版本检查 │ │ • mcp          │
│ • 环境变量      │ │ • 终端备份      │ │ • plugin       │
│ • 代理配置      │ │ • 工作目录      │ │ • auth         │
│ • API 预连接    │ │ • hooks 快照    │ │ • doctor       │
└────────┬────────┘ └────────┬────────┘ └─────────────────┘
         │                   │
         │                   │
         ▼                   ▼
┌─────────────────┐ ┌─────────────────┐
│   services/     │ │   bootstrap/    │
│                 │ │                 │
│ • analytics     │ │ • state.ts      │
│ • api           │ │   (全局状态)    │
│ • mcp           │ │                 │
│ • oauth         │ │ • sessionId     │
│ • lsp           │ │ • cwd           │
└─────────────────┘ │ • permissionCtx │
                    └─────────────────┘
```

---

## 文件路径索引

| 分类 | 文件路径 | 职责说明 |
|------|----------|----------|
| **入口点** | `src/main.tsx` | CLI 入口，Commander.js 配置，主命令处理器 |
| **初始化** | `src/entrypoints/init.ts` | 异步初始化逻辑（配置、网络、清理注册） |
| **会话设置** | `src/setup.ts` | 会话设置（权限验证、worktree 创建、预取） |
| **REPL 启动** | `src/replLauncher.tsx` | REPL 组件懒加载与渲染 |
| **全局状态** | `src/bootstrap/state.ts` | 全局状态管理（会话 ID、权限上下文等） |
| **交互辅助** | `src/interactiveHelpers.tsx` | 设置屏幕、信任对话框、渲染辅助 |
| **性能分析** | `src/utils/startupProfiler.ts` | 启动性能分析 |
| **MDM 预取** | `src/utils/settings/mdm/rawRead.ts` | MDM 设置子进程预取 |
| **Keychain 预取** | `src/utils/secureStorage/keychainPrefetch.ts` | macOS 钥匙串预取 |
| **命令定义** | `src/commands/init.ts` | 子命令注册 |
| **REPL 屏幕** | `src/screens/REPL.tsx` | 主交互界面 |
| **Print 模式** | `src/cli/print.js` | 非交互式输出模式 |
| **API 预连接** | `src/utils/apiPreconnect.ts` | TCP+TLS 握手预连接 |

---

## 总结

Claude Code 的入口与启动流程展现了现代 CLI 工程的最佳实践：

1. **性能优先**：通过并行预取、懒加载、memoize 等技术实现亚秒级启动
2. **安全第一**：信任对话框、权限验证、沙箱检测构成完整安全边界
3. **架构清晰**：main → init → setup → REPL 的分层启动流程职责分明
4. **可扩展性**：Commander.js 子命令系统支持丰富的功能扩展
5. **可观测性**：内置启动性能分析器支持持续优化
6. **模式适配**：支持交互式、非交互式、远程等多种运行模式