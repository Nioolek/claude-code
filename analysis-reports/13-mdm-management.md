# Claude Code MDM 企业管理系统模块深度分析报告

## 一、模块概述

MDM (Mobile Device Management) 模块是 Claude Code 的企业级策略管理系统，用于从操作系统级别的配置源读取企业托管设置。该模块支持 macOS plist、Windows 注册表（HKLM/HKCU）以及 Linux 的文件系统配置，实现了多源级联优先级的"First Source Wins"策略，确保企业策略的安全性和可控性。

### 核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    MDM Settings Pipeline                         │
│                                                                  │
│  Priority (highest to lowest):                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────────────┐ │
│  │ Remote API  │→ │ HKLM/plist  │→ │ managed-settings.json +   │ │
│  │ (highest)   │  │ (admin)     │  │ managed-settings.d/*.json │ │
│  └─────────────┘  └─────────────┘  └───────────────────────────┘ │
│                         ↓                                        │
│              ┌───────────────────┐                               │
│              │ HKCU (lowest)     │                               │
│              │ (user-writable)   │                               │
│              └───────────────────┘                               │
│                                                                  │
│  Files: constants.ts → rawRead.ts → settings.ts                  │
└─────────────────────────────────────────────────────────────────┘
```

## 二、核心组件分析

### 2.1 constants.ts - 共享常量模块

该模块定义了 MDM 配置的核心路径和常量，特点是**零重量级依赖**（仅导入 `os`），可在模块评估早期安全使用。

**关键常量定义**:

| 常量 | 值 | 说明 |
|------|-----|------|
| `MACOS_PREFERENCE_DOMAIN` | `com.anthropic.claudecode` | macOS MDM profile 偏好域 |
| `WINDOWS_REGISTRY_KEY_PATH_HKLM` | `HKLM\SOFTWARE\Policies\ClaudeCode` | Windows 管理员级注册表路径 |
| `WINDOWS_REGISTRY_KEY_PATH_HKCU` | `HKCU\SOFTWARE\Policies\ClaudeCode` | Windows 用户级注册表路径 |
| `WINDOWS_REGISTRY_VALUE_NAME` | `Settings` | 注册表值名（JSON blob） |
| `PLUTIL_PATH` | `/usr/bin/plutil` | macOS plist 转换工具路径 |
| `MDM_SUBPROCESS_TIMEOUT_MS` | `5000` | 子进程超时（5秒） |

**Windows 注册表路径设计要点**:

使用 `SOFTWARE\Policies` 而非 `SOFTWARE\ClaudeCode` 的原因是：`Policies` 位于 WOW64 共享键列表，32位和64位进程可看到相同值，避免注册表重定向问题。

**macOS plist 路径优先级构建**:

```typescript
export function getMacOSPlistPaths(): Array<{ path: string; label: string }> {
  // 1. Per-user managed preferences (highest priority)
  /Library/Managed Preferences/${username}/${MACOS_PREFERENCE_DOMAIN}.plist

  // 2. Device-level managed preferences
  /Library/Managed Preferences/${MACOS_PREFERENCE_DOMAIN}.plist

  // 3. User preferences (ant-only, for testing)
  ~/Library/Preferences/${MACOS_PREFERENCE_DOMAIN}.plist  // 仅 USER_TYPE='ant' 时
}
```

### 2.2 rawRead.ts - 子进程 I/O 模块

该模块负责执行 MDM 配置的原始读取，同样采用**最小依赖设计**，确保可以在 `main.tsx` 模块评估阶段立即执行。

**两种使用模式**:

1. **启动时**: `startMdmRawRead()` 在 `main.tsx` 顶层调用
2. **轮询/备用**: `fireRawRead()` 按需创建新读取

**核心实现 - `fireRawRead` 函数**:

```typescript
export function fireRawRead(): Promise<RawReadResult> {
  // macOS: 并行读取所有 plist 路径
  if (process.platform === 'darwin') {
    const plistPaths = getMacOSPlistPaths()
    const allResults = await Promise.all(
      plistPaths.map(async ({ path, label }) => {
        // Fast-path: 同步检查文件存在，避免 spawn plutil 的 ~5ms 开销
        if (!existsSync(path)) {
          return { stdout: '', label, ok: false }
        }
        const { stdout, code } = await execFilePromise(PLUTIL_PATH, [
          '-convert', 'json', '-o', '-', '--', path,
        ])
        return { stdout, label, ok: code === 0 && !!stdout }
      }),
    )
    // First source wins (array is in priority order)
    const winner = allResults.find(r => r.ok)
    return { plistStdouts: winner ? [{ stdout: winner.stdout, label: winner.label }] : [] }
  }

  // Windows: 并行读取 HKLM 和 HKCU
  if (process.platform === 'win32') {
    const [hklm, hkcu] = await Promise.all([
      execFilePromise('reg', ['query', WINDOWS_REGISTRY_KEY_PATH_HKLM, '/v', WINDOWS_REGISTRY_VALUE_NAME]),
      execFilePromise('reg', ['query', WINDOWS_REGISTRY_KEY_PATH_HKCU, '/v', WINDOWS_REGISTRY_VALUE_NAME]),
    ])
    return { hklmStdout: hklm.code === 0 ? hklm.stdout : null, hkcuStdout: hkcu.code === 0 ? hkcu.stdout : null }
  }

  // Linux: 无 MDM 等效机制
  return { plistStdouts: null, hklmStdout: null, hkcuStdout: null }
}
```

**设计亮点 - 快速路径优化**:

同步 `existsSync` 检查确保子进程在事件循环轮询前启动，对于非 MDM 机器可节省约5ms的 spawn 开销。

### 2.3 settings.ts - 解析与缓存模块

这是 MDM 模块的核心逻辑层，负责解析原始输出、应用"First Source Wins"策略、管理缓存。

**缓存架构**:

```typescript
type MdmResult = { settings: SettingsJson; errors: ValidationError[] }
const EMPTY_RESULT: MdmResult = Object.freeze({ settings: {}, errors: [] })
let mdmCache: MdmResult | null = null      // Admin-only MDM (HKLM/plist)
let hkcuCache: MdmResult | null = null     // User-writable HKCU
```

**"First Source Wins" 策略实现**:

```typescript
function consumeRawReadResult(raw: RawReadResult): { mdm: MdmResult; hkcu: MdmResult } {
  // macOS: plist result (first source wins)
  if (raw.plistStdouts && raw.plistStdouts.length > 0) {
    const result = parseCommandOutputAsSettings(raw.plistStdouts[0].stdout, ...)
    if (Object.keys(result.settings).length > 0) {
      return { mdm: result, hkcu: EMPTY_RESULT }
    }
  }

  // Windows: HKLM result
  if (raw.hklmStdout) {
    const result = parseCommandOutputAsSettings(parseRegQueryStdout(raw.hklmStdout), ...)
    if (Object.keys(result.settings).length > 0) {
      return { mdm: result, hkcu: EMPTY_RESULT }
    }
  }

  // No admin MDM — check managed-settings.json before using HKCU
  if (hasManagedSettingsFile()) {
    return { mdm: EMPTY_RESULT, hkcu: EMPTY_RESULT }
  }

  // Fall through to HKCU
  if (raw.hkcuStdout) {
    const result = parseCommandOutputAsSettings(parseRegQueryStdout(raw.hkcuStdout), ...)
    return { mdm: EMPTY_RESULT, hkcu: result }
  }

  return { mdm: EMPTY_RESULT, hkcu: EMPTY_RESULT }
}
```

**关键策略要点**:

1. **HKLM/plist 优于 HKCU**: 找到管理员级配置后立即返回
2. **managed-settings.json 优于 HKCU**: 文件存在时跳过 HKCU
3. **单一源策略**: 不合并多个 MDM 源

### 2.4 pluginOnlyPolicy.ts - 企业策略锁定模块

实现 `strictPluginOnlyCustomization` 企业策略，锁定定制化表面仅允许插件/托管来源。

```typescript
export const CUSTOMIZATION_SURFACES = [
  'skills', 'agents', 'hooks', 'mcp',
] as const

export function isRestrictedToPluginOnly(surface: CustomizationSurface): boolean {
  const policy = getSettingsForSource('policySettings')?.strictPluginOnlyCustomization
  if (policy === true) return true          // 锁定所有表面
  if (Array.isArray(policy)) return policy.includes(surface)
  return false
}

const ADMIN_TRUSTED_SOURCES: ReadonlySet<string> = new Set([
  'plugin', 'policySettings', 'built-in', 'builtin', 'bundled',
])
```

## 三、与主配置系统的集成

### 3.1 启动加载流程

**main.tsx 中的初始化顺序**:

```typescript
// These side-effects must run before all other imports:
profileCheckpoint('main_tsx_entry');
import { startMdmRawRead } from './utils/settings/mdm/rawRead.js';
startMdmRawRead();  // 立即在模块评估阶段执行
```

### 3.2 policySettings 级联优先级

**完整优先级链**:

```
Remote API (最高) → HKLM/macOS plist → managed-settings.json + drop-ins → HKCU (最低)
```

### 3.3 变更检测与热重载

**MDM 轮询机制**（30分钟间隔）:

```typescript
const MDM_POLL_INTERVAL_MS = 30 * 60 * 1000  // 30 分钟

mdmPollTimer = setInterval(() => {
  const currentSnapshot = jsonStringify({ mdm, hkcu })
  if (currentSnapshot !== lastMdmSnapshot) {
    setMdmSettingsCache(current, currentHkcu)
    fanOut('policySettings')  // 触发热重载
  }
}, MDM_POLL_INTERVAL_MS)
```

## 四、设计亮点

### 4.1 启动性能优化

| 技术 | 效果 |
|------|------|
| **最小依赖设计** | 可在模块评估阶段立即执行 |
| **子进程并行启动** | MDM 子进程在 import 期间并行运行 |
| **快速路径检查** | existsSync 避免非 MDM 机器的 spawn 开销 |

### 4.2 安全设计

| 特性 | 说明 |
|------|------|
| **First Source Wins** | 不合并多源，防止低权限源覆盖高权限策略 |
| **HKLM/plist > HKCU** | 管理员配置优先于用户配置 |
| **项目级排除** | strictPluginOnlyCustomization 排除 projectSettings |

### 4.3 变更检测机制

| 源类型 | 监控方式 |
|--------|----------|
| 文件系统 | chokidar FSWatcher（实时） |
| 注册表/plist | 30分钟轮询 |
| Remote API | 1小时轮询 + ETag 缓存 |

## 五、文件路径索引

| 文件 | 职责 |
|------|------|
| `src/utils/settings/mdm/constants.ts` | MDM 路径常量定义 |
| `src/utils/settings/mdm/rawRead.ts` | 子进程原始读取 |
| `src/utils/settings/mdm/settings.ts` | 解析与缓存管理 |
| `src/utils/settings/managedPath.ts` | 托管设置路径 |
| `src/utils/settings/pluginOnlyPolicy.ts` | 企业策略锁定 |
| `src/services/remoteManagedSettings/index.ts` | 远程托管设置 API |