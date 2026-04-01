# Claude Code 配置系统深度分析报告

## 模块结构概述

```
src/utils/settings/
├── constants.ts          # 设置源枚举
├── types.ts              # Zod schema定义 (~1100行)
├── settings.ts           # 核心加载/合并逻辑
├── settingsCache.ts      # 三级缓存管理
├── validation.ts         # Zod错误格式化
├── changeDetector.ts     # 文件监视+MDM轮询
├── applySettingsChange.ts # 应用设置变更
└── mdm/                  # MDM企业策略
    ├── constants.ts
    ├── rawRead.ts
    └── settings.ts
```

## 1. 设置文件层次结构

### 优先级顺序（从低到高）

```typescript
export const SETTING_SOURCES = [
  'userSettings',      // ~/.claude/settings.json
  'projectSettings',   // $PWD/.claude/settings.json
  'localSettings',     // $PWD/.claude/settings.local.json
  'flagSettings',      // --settings CLI标志 + SDK内联
  'policySettings',    // MDM/注册表/远程API
] as const
```

### 文件路径

| 来源 | 路径 |
|------|------|
| `userSettings` | `~/.claude/settings.json` |
| `projectSettings` | `$PWD/.claude/settings.json` |
| `localSettings` | `$PWD/.claude/settings.local.json`（gitignore） |
| `policySettings` | 多源级联（见下文） |

### Policy设置"First Source Wins"级联

```
优先级: remote API > HKLM/macOS plist > managed-settings.json + drop-ins > HKCU

1. 远程管理设置（API企业策略）
2. MDM（macOS plist / Windows HKLM注册表）
3. managed-settings.json + managed-settings.d/*.json
4. HKCU注册表（Windows用户可写）
```

## 2. 设置合并逻辑

### 深度合并 + 数组连接去重

```typescript
function settingsMergeCustomizer(objValue, srcValue) {
  if (Array.isArray(objValue) && Array.isArray(srcValue)) {
    return mergeArrays(objValue, srcValue)  // 连接+去重
  }
  return undefined  // lodash默认合并
}
```

**关键合并行为:**
- **数组**: 连接并去重
- **对象**: 深度合并
- **Undefined**: 删除信号

## 3. 三级缓存机制

```typescript
// Level 1: Session-level merged settings cache
let sessionSettingsCache: SettingsWithErrors | null = null

// Level 2: Per-source settings cache
const perSourceCache = new Map<SettingSource, SettingsJson | null>()

// Level 3: File parse cache (path → parsed settings)
const parseFileCache = new Map<string, ParsedSettings>()
```

### 缓存流程

```
getInitialSettings()
    ↓
sessionSettingsCache ──── MISS → loadSettingsFromDisk()
                              ↓
                        getSettingsForSource()
                              ↓
                        perSourceCache ──── MISS
                              ↓
                        parseSettingsFile()
                              ↓
                        parseFileCache ──── MISS
                              ↓
                        Read + Zod parse
```

### 缓存失效

```typescript
function resetSettingsCache(): void {
  sessionSettingsCache = null
  perSourceCache.clear()
  parseFileCache.clear()
}
```

## 4. 验证系统

### Schema定义

```typescript
export const SettingsSchema = lazySchema(() =>
  z.object({
    $schema: z.literal(CLAUDE_CODE_SETTINGS_SCHEMA_URL).optional(),
    apiKeyHelper: z.string().optional(),
    env: EnvironmentVariablesSchema().optional(),
    permissions: PermissionsSchema().optional(),
    hooks: HooksSchema().optional(),
    // ... ~100 fields total
  }).passthrough()  // 允许未知字段
)
```

### 预Schema过滤

无效权限规则在schema验证前被过滤，避免一个坏规则拒绝整个文件。

### Zod错误格式化

```typescript
type ValidationError = {
  file?: string
  path: string
  message: string
  expected?: string
  suggestion?: string
  docLink?: string
}
```

## 5. 变更检测和热重载

### 架构

1. **Chokidar文件监视** - 原生文件系统事件
2. **MDM轮询定时器** - 30分钟间隔检查注册表/plist
3. **内部写入抑制** - 5秒窗口忽略自写入
4. **删除宽限期** - 1.7秒延迟处理删除重建

### 变更事件流程

```
文件变更检测
    ↓
handleChange(path)
    ↓
检查内部写入抑制（5秒窗口）
    ↓
执行ConfigChange hooks
    ↓
fanOut(source)
    ↓
resetSettingsCache()
    ↓
settingsChanged.emit(source)
```

### MDM轮询

```typescript
const MDM_POLL_INTERVAL_MS = 30 * 60 * 1000  // 30分钟

mdmPollTimer = setInterval(() => {
  const currentSnapshot = jsonStringify({ mdm, hkcu })
  if (currentSnapshot !== lastMdmSnapshot) {
    setMdmSettingsCache(current)
    fanOut('policySettings')
  }
}, MDM_POLL_INTERVAL_MS)
```

## 6. 安全考虑

### 信任 vs 非信任来源

`projectSettings` 被故意排除在安全敏感检查之外：

```typescript
function hasSkipDangerousModePermissionPrompt(): boolean {
  return !!(
    getSettingsForSource('userSettings')?.skipDangerousModePermissionPrompt ||
    // projectSettings EXCLUDED - 恶意项目可能自动绕过
    getSettingsForSource('flagSettings')?.skipDangerousModePermissionPrompt ||
    getSettingsForSource('policySettings')?.skipDangerousModePermissionPrompt
  )
}
```

### Plugin-Only Policy

```typescript
function isRestrictedToPluginOnly(surface): boolean {
  const policy = getSettingsForSource('policySettings')?.strictPluginOnlyCustomization
  if (policy === true) return true  // 锁定所有表面
  if (Array.isArray(policy)) return policy.includes(surface)
  return false
}
```

## 7. 关键设计模式

1. **懒Schema评估**: 所有schema使用 `lazySchema()` 延迟构造
2. **前向兼容**: `.passthrough()` 和 `.catch()` 允许未知字段
3. **循环依赖打破**: 多个模块专门用于打破循环依赖
4. **并行预取**: MDM读取在 `main.tsx` 中提前启动

## 8. 文件路径索引

| 文件 | 职责 |
|------|------|
| `src/utils/settings/constants.ts` | 设置源枚举 |
| `src/utils/settings/types.ts` | Zod schema定义 |
| `src/utils/settings/settings.ts` | 核心加载/合并 |
| `src/utils/settings/settingsCache.ts` | 三级缓存 |
| `src/utils/settings/validation.ts` | 错误格式化 |
| `src/utils/settings/changeDetector.ts` | 文件监视 |
| `src/utils/settings/mdm/` | MDM企业策略 |