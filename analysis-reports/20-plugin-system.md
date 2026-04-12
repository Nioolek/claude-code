# Claude Code 插件系统深度分析报告

## 模块概述

### 一句话角色定位

**插件系统是 Claude Code 的扩展生态基础设施**——它提供了 Marketplace 发现、插件加载、组件注册、安全策略、用户配置等完整机制，让第三方扩展可以安全、可控地集成到 CLI 中。

### 核心架构理解

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Claude Code Plugin System                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌────────────────┐   ┌────────────────────┐   ┌────────────────────────┐   │
│  │ Marketplace    │   │ Plugin Loader      │   │ Plugin Registry       │   │
│  │ Manager        │──►│ (pluginLoader.ts)  │──►│ (LoadedPlugin[])      │   │
│  │                │   │                    │   │                        │   │
│  │ - 发现插件      │   │ - 加载 manifest    │   │ - enabled/disabled    │   │
│  │ - 缓存管理      │   │ - 验证 schema      │   │ - 错误收集            │   │
│  │ - 策略检查      │   │ - 解析来源         │   │                        │   │
│  └────────────────┘   └────────────────────┘   └────────────────────────┘   │
│        │                      │                        │                    │
│        ▼                      ▼                        ▼                    │
│  ┌────────────────┐   ┌────────────────────┐   ┌────────────────────────┐   │
│  │ Plugin Cache   │   │ Component Loaders  │   │ Global State           │   │
│  │ ~/.claude/     │   │                    │   │ STATE.registeredHooks  │   │
│  │ plugins/cache/ │   │ - loadPluginCmds   │   │                        │   │
│  │ plugins/data/  │   │ - loadPluginAgents │   │                        │   │
│  │                │   │ - loadPluginHooks  │   │                        │   │
│  └────────────────┘   │ - mcpPluginInteg   │   └────────────────────────┘   │
│                       │ - lspPluginInteg   │                                 │
│                       └────────────────────┘                                 │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      Plugin Components                               │   │
│  ├────────────┬────────────┬────────────┬──────────┬──────────────────┐   │
│  │ Commands   │ Skills     │ Hooks      │ Agents   │ MCP/LSP Servers  │   │
│  │ (.md)      │ (SKILL.md) │(hooks.json)│ (.md)    │                  │   │
│  │            │            │            │          │                  │   │
│  │ /plugin:x  │ SkillTool  │Event-based │AgentTool │ External         │   │
│  │            │ invocation │ callbacks  │ dispatch │ Processes        │   │
│  └────────────┴────────────┴────────────┴──────────┴──────────────────┘   │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 与其他模块的关系

```
                    ┌──────────────┐
                    │  main.tsx    │
                    │  (启动入口)   │
                    └──────┬───────┘
                           │ 启动时预加载
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │               pluginLoader.ts                        │
    │              (插件加载核心)                            │
    ├─────────────────────────────────────────────────────┤
    │                                                      │
    │  加载流程:                                            │
    │  loadAllPluginsCacheOnly()                           │
    │     │                                                │
    │     ├── getInlinePlugins() (--plugin-dir)           │
    │     ├── getBuiltinPlugins() (内置插件)               │
    │     └── loadPluginsFromMarketplaces() (配置插件)     │
    │                                                      │
    └─────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ Commands │     │ Hooks    │     │ MCP/LSP  │
    │ 系统注册  │     │ 系统注册  │     │ 服务启动 │
    │          │     │          │     │          │
    │ getPlugin│     │loadPlugin│     │extractMcp│
    │ Commands │     │ Hooks    │     │ Servers  │
    └──────────┘     └──────────┘     └──────────┘
         │                 │                 │
         ▼                 ▼                 ▼
    ┌──────────────────────────────────────────────────┐
    │                   AppState                        │
    │  - commands[]    - registeredHooks    - mcp/lsp  │
    └──────────────────────────────────────────────────┘
```

---

## 核心类型定义

### 1. 插件身份格式

```
pluginId = "${name}@${marketplace}"

示例:
- "my-plugin@claude-code-marketplace"  # 官方 marketplace
- "git-tools@my-company-marketplace"   # 企业 marketplace
- "internal-utils@builtin"             # 内置插件
- "session-plugin@inline"              # --plugin-dir 会话插件
```

### 2. LoadedPlugin 结构

```typescript
// src/types/plugin.ts:48-70
type LoadedPlugin = {
  name: string                // 插件名
  manifest: PluginManifest    // plugin.json 解析结果
  path: string                // 插件安装路径
  source: string              // 来源 marketplace
  repository: string          // 仓库标识符
  enabled?: boolean           // 是否启用
  isBuiltin?: boolean         // 是否内置
  sha?: string                // Git SHA (版本锁定)

  // 组件路径
  commandsPath?: string
  commandsPaths?: string[]
  commandsMetadata?: Record<string, CommandMetadata>
  agentsPath?: string
  agentsPaths?: string[]
  skillsPath?: string
  skillsPaths?: string[]
  outputStylesPath?: string

  // 配置
  hooksConfig?: HooksSettings
  mcpServers?: Record<string, McpServerConfig>
  lspServers?: Record<string, LspServerConfig>
  settings?: Record<string, unknown>
}
```

### 3. PluginManifest Schema 组合

```typescript
// src/utils/plugins/schemas.ts:884-898
PluginManifestSchema = z.object({
  ...PluginManifestMetadataSchema().shape,      // name, version, description
  ...PluginManifestHooksSchema().partial().shape,
  ...PluginManifestCommandsSchema().partial().shape,
  ...PluginManifestAgentsSchema().partial().shape,
  ...PluginManifestSkillsSchema().partial().shape,
  ...PluginManifestOutputStylesSchema().partial().shape,
  ...PluginManifestChannelsSchema().partial().shape,
  ...PluginManifestMcpServerSchema().partial().shape,
  ...PluginManifestLspServerSchema().partial().shape,
  ...PluginManifestSettingsSchema().partial().shape,
  ...PluginManifestUserConfigSchema().partial().shape,
})
```

### 4. PluginError 类型（25+ 种）

```typescript
// src/types/plugin.ts:101-284
type PluginError =
  | { type: 'path-not-found', source, plugin?, path, component }
  | { type: 'git-auth-failed', source, plugin?, gitUrl, authType }
  | { type: 'git-timeout', source, plugin?, gitUrl, operation }
  | { type: 'network-error', source, plugin?, url, details? }
  | { type: 'manifest-parse-error', source, plugin?, manifestPath, parseError }
  | { type: 'manifest-validation-error', source, plugin?, manifestPath, validationErrors[] }
  | { type: 'plugin-not-found', source, pluginId, marketplace }
  | { type: 'marketplace-not-found', source, marketplace, availableMarketplaces[] }
  | { type: 'marketplace-load-failed', source, marketplace, reason }
  | { type: 'mcp-config-invalid', source, plugin, serverName, validationError }
  | { type: 'mcp-server-suppressed-duplicate', source, plugin, serverName, duplicateOf }
  | { type: 'lsp-config-invalid', source, plugin, serverName, validationError }
  | { type: 'hook-load-failed', source, plugin, hookPath, reason }
  | { type: 'component-load-failed', source, plugin, component, path, reason }
  | { type: 'mcpb-download-failed', source, plugin, url, reason }
  | { type: 'mcpb-extract-failed', source, plugin, mcpbPath, reason }
  | { type: 'mcpb-invalid-manifest', source, plugin, mcpbPath, validationError }
  | { type: 'marketplace-blocked-by-policy', source, plugin?, marketplace, blockedByBlocklist?, allowedSources[] }
  | { type: 'dependency-unsatisfied', source, plugin, dependency, reason }
  | { type: 'plugin-cache-miss', source, plugin, installPath }
  | { type: 'lsp-server-start-failed', source, plugin, serverName, reason }
  | { type: 'lsp-server-crashed', source, plugin, serverName, exitCode, signal? }
  | { type: 'lsp-request-timeout', source, plugin, serverName, method, timeoutMs }
  | { type: 'lsp-request-failed', source, plugin, serverName, method, error }
  | { type: 'generic-error', source, plugin?, error }
```

---

## 插件生命周期

### Phase 1: 发现 (Discovery)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         插件发现优先级                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [优先级 1] Marketplace-based (settings.enabledPlugins)                     │
│  ────────────────────────────────────────────────────────────────────────── │
│  settings.json:                                                              │
│  {                                                                           │
│    "enabledPlugins": {                                                       │
│      "my-plugin@claude-code-marketplace": true,                              │
│      "git-tools@my-company-marketplace": true                                │
│    }                                                                         │
│  }                                                                           │
│                                                                              │
│  [优先级 2] Session-only (--plugin-dir CLI 参数)                             │
│  ────────────────────────────────────────────────────────────────────────── │
│  命令行: claude-code --plugin-dir ./my-plugins                               │
│  → 临时加载，session 结束后不保留                                             │
│                                                                              │
│  [优先级 3] Built-in (BUILTIN_PLUGINS Map)                                   │
│  ────────────────────────────────────────────────────────────────────────── │
│  src/plugins/builtinPlugins.ts                                               │
│  → registerBuiltinPlugin() 注册                                              │
│  → ID 格式: "{name}@builtin"                                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**关键发现函数:**

```
loadKnownMarketplacesConfigSafe()  // 读取 known_marketplaces.json
  → getMarketplaceCacheOnly(name)  // 检查缓存或从 source 加载
  → getPluginByIdCacheOnly(id)     // 在 marketplace catalog 中查找插件
  → resolvePluginPath()            // 解析插件来源路径
```

### Phase 2: 加载 (Loading)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    loadAllPluginsCacheOnly() 流程                            │
│                    (src/utils/plugins/pluginLoader.ts:3137)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [1] 获取 inline 插件                                                        │
│      const inlinePlugins = getInlinePlugins()                                │
│      // 来自 --plugin-dir CLI 参数                                           │
│                                                                              │
│  [2] 获取内置插件                                                            │
│      const { enabled: builtinEnabled, disabled: builtinDisabled }           │
│        = getBuiltinPlugins()                                                 │
│      // 来自 BUILTIN_PLUGINS Map                                             │
│                                                                              │
│  [3] 加载 marketplace 插件                                                   │
│      const { enabledPlugins, disabledPlugins } = getSettings_DEPRECATED()   │
│                                                                              │
│      for (const [pluginId, enabled] of Object.entries(enabledPlugins)) {    │
│        // 3.1 解析标识符: "plugin@marketplace"                               │
│        const { name, marketplace } = parsePluginIdentifier(pluginId)        │
│                                                                              │
│        // 3.2 检查策略                                                       │
│        if (isPluginBlockedByPolicy(pluginId)) {                             │
│          errors.push({ type: 'marketplace-blocked-by-policy', ... })        │
│          continue                                                            │
│        }                                                                     │
│                                                                              │
│        // 3.3 加载插件                                                       │
│        const plugin = await loadPluginFromMarketplace(                      │
│          pluginId, marketplace, entry                                        │
│        )                                                                     │
│                                                                              │
│        // 3.4 检查依赖                                                       │
│        if (hasUnsatisfiedDependencies(plugin, allPlugins)) {                │
│          plugin.enabled = false                                              │
│          errors.push({ type: 'dependency-unsatisfied', ... })               │
│        }                                                                     │
│      }                                                                       │
│                                                                              │
│  [4] 返回结果                                                                │
│      return {                                                                │
│        enabled: [...builtinEnabled, ...marketplaceEnabled, ...inline],      │
│        disabled: [...builtinDisabled, ...marketplaceDisabled],              │
│        errors                                                                │
│      }                                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 缓存路径结构

```
~/.claude/plugins/
├── cache/
│   └── {marketplace}/{plugin}/{version}/     # 版本化安装缓存
│       ├── .claude-plugin/
│       │   ├── plugin.json                   # 插件 manifest
│       │   └── hooks/hooks.json              # Hooks 配置
│       ├── commands/                         # Commands 目录
│       ├── agents/                           # Agents 目录
│       ├── skills/                           # Skills 目录
│       └── .mcp.json                         # MCP 配置
│
├── data/
│   └── {sanitized-plugin-id}/                # 持久化数据目录（跨版本保留）
│       # 用于 ${CLAUDE_PLUGIN_DATA} 变量
│
├── marketplaces/
│   └── {name}/.claude-plugin/marketplace.json # Marketplace catalog 缓存
│
├── npm-cache/                                # NPM 包缓存
│
└── known_marketplaces.json                   # 已知 marketplace 配置
```

### 环境变量控制

| 环境变量 | 作用 | 示例 |
|----------|------|------|
| `CLAUDE_CODE_PLUGIN_CACHE_DIR` | 直接覆盖插件根目录 | `~/custom-plugins` |
| `CLAUDE_CODE_USE_COWORK_PLUGINS` | 使用 `cowork_plugins` 目录 | `true` |
| `CLAUDE_CODE_PLUGIN_SEED_DIR` | 预配置种子目录（容器镜像） | `/opt/seed-plugins` |

### Phase 3: 注册 (Registration)

各组件有独立 loader 注册到全局状态:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    组件注册流程                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  QueryEngine.ts / setup.ts                                                   │
│      │                                                                       │
│      └─> loadAllPluginsCacheOnly()                                          │
│          │                                                                   │
│          └─> [并行组件加载]                                                   │
│              │                                                               │
│              ├─> getPluginCommands() [loadPluginCommands.ts:414]            │
│              │   ├── loadCommandsFromDirectory(commandsPath)                │
│              │   ├── loadCommandsFromDirectory(commandsPaths[])             │
│              │   └── createPluginCommand() → Command 对象                   │
│              │                                                               │
│              ├─> getPluginSkills() [loadPluginCommands.ts:840]              │
│              │   └── loadSkillsFromDirectory(skillsPath)                    │
│              │   └── transformPluginSkillFiles()                             │
│              │                                                               │
│              ├─> loadPluginAgents() [loadPluginAgents.ts:231]               │
│              │   └── loadAgentsFromDirectory(agentsPath)                    │
│              │   └── loadAgentFromFile() → AgentDefinition                  │
│              │                                                               │
│              ├─> loadPluginHooks() [loadPluginHooks.ts:91]                  │
│              │   ├── convertPluginHooksToMatchers()                         │
│              │   ├── clearRegisteredPluginHooks()                           │
│              │   └── registerHookCallbacks(STATE.registeredHooks)           │
│              │                                                               │
│              ├─> extractMcpServersFromPlugins() [mcpPluginIntegration.ts]   │
│              │   ├── 加载 .mcp.json                                          │
│              │   ├── 加载 manifest.mcpServers                                │
│              │   ├── 加载 MCPB 文件                                          │
│              │   └── 添加命名空间: "plugin:{name}:{server}"                  │
│              │                                                               │
│              └─> extractLspServersFromPlugins() [lspPluginIntegration.ts]   │
│                  ├── 加载 .lsp.json                                          │
│                  └── 加载 manifest.lspServers                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase 4: 执行 (Execution)

| 组件 | 执行路径 | 触发方式 |
|------|---------|----------|
| **Commands** | `getPromptForCommand()` → 注入对话 | `/plugin:command_name` |
| **Skills** | `SkillTool.ts` → `executeForkedSkill()` | SkillTool 调用 |
| **Hooks** | `STATE.registeredHooks[event]` → callback | 事件触发 |
| **Agents** | `AgentTool.ts` → `runAgent()` | AgentTool 调用 |
| **MCP Servers** | `mcp/config.ts` → stdio/SSE/WS 进程 | MCP tool 调用 |
| **LSP Servers** | `lsp/config.ts` → 文件打开时启动 | Editor 集成 |

---

## 插件组件详解

### 1. Commands

**目录结构:**

```
plugin/
├── commands/           # 默认目录
│   ├── build.md        # → /plugin:build
│   ├── deploy.md       # → /plugin:deploy
│   └── namespace/
│       └── test.md     # → /plugin:namespace:test
│
└── plugin.json         # 可指定 commandsPaths, commandsMetadata
```

**manifest.json 配置格式:**

```json
{
  "commands": [
    "./commands/build.md",           // 单个路径
    "./commands/deploy.md"           // 路径数组
  ],
  // 或命名命令对象:
  "commands": {
    "about": {
      "source": "./README.md",
      "description": "Show plugin info"
    },
    "help": {
      "content": "Inline content here...",  // 内联内容
      "description": "Quick help"
    }
  }
}
```

**Frontmatter 字段:**

```yaml
---
description: Build the project
allowed-tools: Bash, Glob          # 允许的工具列表
argument-hint: "[target]"          # 参数提示（显示在 UI）
model: haiku                       # 模型覆盖: haiku/sonnet/opus/inherit
effort: high                       # 努力级别: low/medium/high
user-invocable: true               # 用户可调用
shell: bash                        # Shell 类型: bash/powershell
---
```

**变量替换:**

| 变量 | 替换值 |
|------|--------|
| `$ARGUMENTS` | 用户提供的参数 |
| `${CLAUDE_PLUGIN_ROOT}` | 插件安装目录 |
| `${CLAUDE_PLUGIN_DATA}` | 持久化数据目录（跨版本保留） |
| `${CLAUDE_SESSION_ID}` | 当前会话 ID |
| `${user_config.X}` | 用户配置值（需要在 manifest.userConfig 中定义） |

**命令命名规则:**

```
┌────────────────────────────────────────────────────────────────────┐
│                    命令命名规则                                      │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  基础命令:                                                          │
│  commands/build.md  → pluginName:build                             │
│                                                                     │
│  嵌套命令:                                                          │
│  commands/namespace/test.md → pluginName:namespace:test            │
│                                                                     │
│  命名命令（commandsMetadata）:                                      │
│  manifest.json: { "about": {...} } → pluginName:about              │
│                                                                     │
│  Skill 文件:                                                        │
│  skills/review/SKILL.md → pluginName:review                        │
│  # 使用父目录名作为 skill 名                                         │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

### 2. Skills (SKILL.md)

**目录结构:**

```
plugin/
├── skills/             # 默认目录
│   ├── review/
│   │   └── SKILL.md    # → pluginName:review skill
│   └── analyze/
│       └── SKILL.md    # → pluginName:analyze skill
```

**执行模式:**

```yaml
---
context: inline  # 默认: 内容注入当前对话
---
# 或
---
context: fork    # 独立 sub-agent，隔离上下文和 token 预算
agent: general-purpose  # fork 时可选指定 agent 类型
---
```

**Skills vs Commands 区别:**

| 特性 | Skill | Command |
|------|-------|---------|
| 文件名 | `SKILL.md` | 任意 `.md` |
| 目录结构 | `skills/{name}/SKILL.md` | `commands/{name}.md` |
| 基目录注入 | 自动注入 `Base directory for this skill` | 不注入 |
| `CLAUDE_SKILL_DIR` | 可用 | 不可用 |
| `loadedFrom` | `'plugin'` | undefined |

### 3. Hooks

**Hook 类型 Schema:**

```typescript
// src/schemas/hooks.ts
HookCommandSchema = z.discriminatedUnion('type', [
  { type: 'command', command: string, timeout?: number },
  { type: 'prompt', prompt: string },
  { type: 'agent', prompt: string, agent?: string },
  { type: 'http', url: string, method?: string, headers?: Record<string,string> },
])
```

**manifest.json hooks 配置:**

```json
{
  "hooks": "./hooks/hooks.json",
  // 或内联:
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "echo 'Bash tool used'" }
        ]
      }
    ]
  }
}
```

**支持的事件类型:**

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    Hook 事件类型                                             │
├───────────────────────┬────────────────────────────────────────────────────┤
│        事件           │                     触发时机                        │
├───────────────────────┼────────────────────────────────────────────────────┤
│ PreToolUse            │ Tool 执行前                                         │
│ PostToolUse           │ Tool 执行成功后                                     │
│ PostToolUseFailure    │ Tool 执行失败后                                     │
│ PermissionDenied      │ 权限被拒绝时                                        │
│ Notification          │ 系统通知时                                          │
│ UserPromptSubmit      │ 用户提交 prompt 时                                  │
│ SessionStart          │ 会话开始时                                          │
│ SessionEnd            │ 会话结束时                                          │
│ Stop                  │ Agent 停止时                                        │
│ StopFailure           │ Agent 停止失败时                                    │
│ SubagentStart         │ 子 agent 启动时                                     │
│ SubagentStop          │ 子 agent 停止时                                     │
│ PreCompact            │ 上下文压缩前                                        │
│ PostCompact           │ 上下文压缩后                                        │
│ PermissionRequest     │ 权限请求时                                          │
│ Setup                 │ 插件设置时                                          │
│ TeammateIdle          │ Teammate 空闲时                                     │
│ TaskCreated           │ 任务创建时                                          │
│ TaskCompleted         │ 任务完成时                                          │
│ Elicitation           │ Elicitation 请求时                                 │
│ ElicitationResult     │ Elicitation 结果返回时                             │
│ ConfigChange          │ 配置变更时                                          │
│ WorktreeCreate        │ Worktree 创建时                                     │
│ WorktreeRemove        │ Worktree 移除时                                     │
│ InstructionsLoaded    │ 指令加载时                                          │
│ CwdChanged            │ 工作目录变更时                                      │
│ FileChanged           │ 文件变更时                                          │
└───────────────────────┴────────────────────────────────────────────────────┘
```

**热重载机制:**

```typescript
// src/utils/plugins/loadPluginHooks.ts:255-287
export function setupPluginHookHotReload(): void {
  settingsChangeDetector.subscribe(source => {
    if (source === 'policySettings') {
      // 检查 plugin-affecting settings 是否变化
      const newSnapshot = getPluginAffectingSettingsSnapshot()
      if (newSnapshot !== lastPluginSettingsSnapshot) {
        // 清除缓存并重新加载 hooks
        clearPluginCache()
        clearPluginHookCache()
        void loadPluginHooks()
      }
    }
  })
}
```

### 4. Agents

**目录结构:**

```
plugin/
├── agents/
│   ├── tester.md       # → pluginName:tester agent 类型
│   └── reviewer.md     # → pluginName:reviewer agent 类型
```

**Frontmatter 字段:**

```yaml
---
name: tester
description: Run automated tests
when-to-use: When you need to run tests
tools: Bash, Glob, Read            # 允许的工具
skills: /plugin:test-setup         # 关联 skills
color: blue                        # Agent 颜色: blue/green/yellow/...
model: haiku                       # 模型
background: true                   # 后台运行
memory: user                       # 内存范围: user/project/local
isolation: worktree                # 创建隔离 worktree
effort: medium                     # 努力级别
maxTurns: 10                       # 最大轮次
disallowedTools: WebFetch          # 禁止的工具
---
```

**安全限制（重要）:**

```
┌────────────────────────────────────────────────────────────────────────────┐
│           Plugin Agents 安全限制                                            │
│           (src/utils/plugins/loadPluginAgents.ts:153-168)                  │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Plugin agents **不能**设置以下 frontmatter 字段:                          │
│                                                                             │
│  ┌─────────────┬─────────────────────────────────────────────────────┐     │
│  │ 字段        │ 阻止原因                                             │     │
│  ├─────────────┼─────────────────────────────────────────────────────┤     │
│  │ permissionMode│ 权限升级风险 - 会绕过安装时批准                    │     │
│  │ hooks        │ 静默添加回调风险 - 未经用户同意                     │     │
│  │ mcpServers   │ 超出 manifest 声明风险 - 添加未审核的服务           │     │
│  └─────────────┴─────────────────────────────────────────────────────┘     │
│                                                                             │
│  这些字段会被忽略并记录警告                                                  │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### 5. MCP Servers

**配置来源:**

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    MCP 配置来源优先级                                        │
│                    (src/utils/plugins/mcpPluginIntegration.ts:131-212)      │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [最低优先级] .mcp.json 文件                                                 │
│  ───────────────────────────────────────────────────────────────────────── │
│  plugin/.mcp.json                                                           │
│                                                                             │
│  [更高优先级] manifest.mcpServers 字段                                       │
│  ───────────────────────────────────────────────────────────────────────── │
│  多种格式:                                                                  │
│  - String: "./servers/config.json"     → JSON 文件路径                     │
│  - MCPB: "./servers/my-server.mcpb"    → MCP Bundle 文件                   │
│  - MCPB URL: "https://.../server.mcpb" → 远程 MCPB                         │
│  - Object: { "telegram": {...} }       → 内联服务器配置                    │
│  - Array: [上述各种格式混合]            → 多个来源                         │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

**MCPB (MCP Bundle) 支持:**

```typescript
// src/utils/plugins/mcpbHandler.ts
loadMcpbFile(path, pluginPath, pluginId) → {
  extractedPath,   // 解压路径: ~/.claude/plugins/mcpb/{pluginId}/
  manifest,        // MCPB manifest
  mcpConfig        // MCP 服务器配置
}
```

**命名空间隔离:**

```typescript
// src/utils/plugins/mcpPluginIntegration.ts:341-360
scopedName = `plugin:${pluginName}:${originalName}`

// 示例:
// manifest: { "telegram": {...} }
// 结果: "plugin:my-plugin:telegram"
```

**Channel 用户配置:**

```typescript
// Channels 是 MCP servers that emit notifications/claude/channel
// (如 Telegram bot, Slack bot)

// manifest.json:
{
  "channels": [
    {
      "server": "telegram",           // MCP server 名
      "displayName": "Telegram Bot",
      "userConfig": {                  // Channel 专属配置
        "botToken": {
          "type": "string",
          "title": "Bot Token",
          "sensitive": true            // 存储到 keychain
        }
      }
    }
  ]
}
```

### 6. LSP Servers

**配置 Schema:**

```typescript
// src/services/lsp/types.ts
LspServerConfig = {
  command: string,                    // 启动命令
  args?: string[],                    // 命令行参数
  extensionToLanguage: {              // 扩展名 → LSP 语言 ID 映射
    ".ts": "typescript",
    ".js": "javascript"
  },
  transport: 'stdio' | 'socket',      // 传输方式
  env?: Record<string, string>,       // 环境变量
  initializationOptions?: unknown,    // LSP 初始化选项
  settings?: unknown,                 // LSP settings
  startupTimeout?: number,            // 启动超时（ms）
  shutdownTimeout?: number,           // 关闭超时（ms）
  restartOnCrash?: boolean,           // 崩溃后自动重启
  maxRestarts?: number                // 最大重启次数
}
```

**路径验证（安全）:**

```typescript
// src/utils/plugins/lspPluginIntegration.ts:28-45
validatePathWithinPlugin(pluginPath, relativePath)
  // 解析路径并确保停留在插件目录内
  // 防止路径遍历攻击
```

---

## 安全机制与策略检查

### 1. 官方 Marketplace 保护

```
┌────────────────────────────────────────────────────────────────────────────┐
│           官方 Marketplace 名称保护                                          │
│           (src/utils/plugins/schemas.ts:19-100)                             │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [专属名称] 只有 Anthropic 可以使用                                          │
│  ───────────────────────────────────────────────────────────────────────── │
│  ALLOWED_OFFICIAL_MARKETPLACE_NAMES = new Set([                            │
│    'claude-code-marketplace',                                              │
│    'claude-code-plugins',                                                  │
│    'anthropic-marketplace',                                                │
│    'anthropic-plugins',                                                    │
│    'agent-skills',                                                         │
│    'life-sciences',                                                        │
│    'knowledge-work-plugins'                                                │
│  ])                                                                        │
│                                                                             │
│  [冒充模式阻止]                                                             │
│  ───────────────────────────────────────────────────────────────────────── │
│  BLOCKED_OFFICIAL_NAME_PATTERN =                                          │
│    /(?:official.*anthropic|anthropic.*official|...)/i                     │
│                                                                             │
│  [Unicode homograph 攻击防护]                                               │
│  ───────────────────────────────────────────────────────────────────────── │
│  NON_ASCII_PATTERN = /[^\u0020-\u007E]/  // 仅允许 ASCII                   │
│                                                                             │
│  [GitHub org 验证]                                                          │
│  ───────────────────────────────────────────────────────────────────────── │
│  OFFICIAL_GITHUB_ORG = 'anthropics'                                        │
│  validateOfficialNameSource(name, source)                                  │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### 2. 策略阻断

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    策略阻断机制                                              │
├───────────────────────┬────────────────────────────────────────────────────┤
│        策略来源        │                     检查函数                        │
├───────────────────────┼────────────────────────────────────────────────────┤
│ policySettings        │ isPluginBlockedByPolicy()  → 企业管理设置           │
│ strictKnownMarketplaces│ isSourceAllowedByPolicy() → 仅允许白名单          │
│ blockedMarketplaces   │ isSourceInBlocklist()      → 显式阻止名单          │
└───────────────────────┴────────────────────────────────────────────────────┘
```

**策略错误类型:**

```typescript
type PluginError = {
  type: 'marketplace-blocked-by-policy'
  source: string
  plugin?: string
  marketplace: string
  blockedByBlocklist?: boolean  // true: 被 blocklist 阻止
                                // false: 不在 strictKnownMarketplaces
  allowedSources: string[]      // 允许的来源格式化字符串
}
```

### 3. 路径遍历防护

```typescript
// src/utils/plugins/validatePlugin.ts
checkPathTraversal(path, field, errors, hint)
  // 检查 '..' 路径段，防止目录穿越攻击

// src/utils/plugins/lspPluginIntegration.ts:28-45
validatePathWithinPlugin(pluginPath, relativePath)
  // 确保解析后的路径停留在插件目录内
```

### 4. 依赖解析

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    依赖解析机制                                              │
│                    (src/utils/plugins/dependencyResolver.ts)                │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  manifest.json 声明依赖:                                                    │
│  ───────────────────────────────────────────────────────────────────────── │
│  {                                                                          │
│    "dependencies": ["other-plugin", "plugin@marketplace"]                  │
│  }                                                                          │
│                                                                             │
│  解析流程:                                                                  │
│  ───────────────────────────────────────────────────────────────────────── │
│  verifyAndDemote(plugin, allPlugins)                                       │
│     │                                                                       │
│     ├── 检查所有依赖是否启用                                                │
│     │                                                                       │
│     ├── 依赖缺失 → plugin.enabled = false                                  │
│     │             errors.push({ type: 'dependency-unsatisfied', ... })    │
│     │                                                                       │
│     └── 依赖启用 → 继续加载                                                 │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Marketplace 机制

### 1. Marketplace 来源类型

```typescript
// src/utils/plugins/schemas.ts:906-999
MarketplaceSourceSchema = z.discriminatedUnion('source', [
  { source: 'url', url: string, headers?: Record<string,string> },
  { source: 'github', repo: string, ref?: string, path?: string, sparsePaths?: string[] },
  { source: 'git', url: string, ref?: string, path?: string, sparsePaths?: string[] },
  { source: 'npm', package: string, version?: string, registry?: string },
  { source: 'file', path: string },
  { source: 'directory', path: string },
  { source: 'hostPattern', hostPattern: string }  // 正则匹配 host
])
```

### 2. Marketplace.json 结构

```json
{
  "name": "my-marketplace",
  "metadata": {
    "description": "My company's plugin marketplace",
    "maintainer": "Company Name",
    "homepage": "https://company.com/plugins"
  },
  "plugins": [
    {
      "name": "my-plugin",
      "version": "1.0.0",
      "source": "./plugins/my-plugin",  // 相对于 marketplace root
      "description": "Plugin description",
      "category": "development",
      "tags": ["git", "build"],
      "autoUpdate": true                 // 是否自动更新
    }
  ]
}
```

### 3. Marketplace 加载流程

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    Marketplace 加载流程                                      │
│                    (src/utils/plugins/marketplaceManager.ts)                │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  loadKnownMarketplacesConfigSafe()                                          │
│      │ 读取 ~/.claude/plugins/known_marketplaces.json                      │
│      ▼                                                                      │
│  getMarketplaceCacheOnly(name)                                              │
│      │ 检查 ~/.claude/plugins/marketplaces/{name}/                         │
│      │                                                                      │
│      ├── 缓存存在 → 直接读取 marketplace.json                               │
│      │                                                                      │
│      └── 缓存不存在 → 从 source 加载                                        │
│          │                                                                  │
│          ├─ source: 'github' → cloneGitHubRepo(config)                     │
│          ├─ source: 'git'    → cloneGitRepo(config)                        │
│          ├─ source: 'url'    → fetchFromUrl(config)                        │
│          ├─ source: 'npm'    → extractNpmPackage(config)                   │
│          ├─ source: 'file'   → readLocalFile(config)                       │
│          └─ source: 'directory' → readLocalDirectory(config)               │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4. 自动更新策略

```typescript
// 官方 marketplaces 默认自动更新（除 knowledge-work-plugins）
// 第三方 marketplaces: autoUpdate: false 默认

isMarketplaceAutoUpdate(marketplaceName, entry)
  // 判断是否自动更新插件
```

---

## 用户配置系统

### 1. Schema 定义

```typescript
// src/utils/plugins/schemas.ts:587-621
PluginUserConfigOptionSchema = z.object({
  type: 'string' | 'number' | 'boolean' | 'directory' | 'file',
  title: string,           // 人可读标签
  description: string,     // 帮助文本
  required?: boolean,      // 必填验证（空则失败）
  default?: string | number | boolean | string[],
  multiple?: boolean,      // string 类型: 允许数组
  sensitive?: boolean,     // 存储到 keychain 而非 settings.json
  min?: number,            // 最小值（number 类型）
  max?: number,            // 最大值（number 类型）
})
```

### 2. manifest.json 配置示例

```json
{
  "userConfig": {
    "apiToken": {
      "type": "string",
      "title": "API Token",
      "description": "Your API token for authentication",
      "required": true,
      "sensitive": true              // 存储到 keychain
    },
    "defaultBranch": {
      "type": "string",
      "title": "Default Branch",
      "description": "Default git branch name",
      "default": "main"
    },
    "timeout": {
      "type": "number",
      "title": "Timeout (seconds)",
      "min": 1,
      "max": 300,
      "default": 30
    },
    "debugMode": {
      "type": "boolean",
      "title": "Debug Mode",
      "default": false
    }
  }
}
```

### 3. 存储分离

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    用户配置存储分离                                          │
│                    (src/utils/plugins/pluginOptionsStorage.ts:90-194)       │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  savePluginOptions(pluginId, values, schema)                               │
│                                                                             │
│  按 sensitive 标志分离存储:                                                  │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  sensitive: true                                                            │
│  ├── 存储位置: secureStorage (keychain 或 .credentials.json)               │
│  ├── 特点: 加密存储，不暴露在文件中                                          │
│  └── 用例: API tokens, passwords, secret keys                             │
│                                                                             │
│  sensitive: false                                                           │
│  ├── 存储位置: settings.json → pluginConfigs[pluginId].options             │
│  ├── 特点: 明文存储，可被版本控制                                            │
│  └── 用例: 默认分支名,超时设置,调试模式                                     │
│                                                                             │
│  重配置时:                                                                  │
│  ───────────────────────────────────────────────────────────────────────── │
│  scrubSets() → 清除相反存储位置的旧键                                        │
│  防止敏感数据残留在 settings.json                                           │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4. 变量替换

| 函数 | 替换内容 | 使用场景 |
|------|---------|---------|
| `substitutePluginVariables()` | `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` | Commands/Skills/Hooks |
| `substituteUserConfigVariables()` | `${user_config.KEY}` → 存储值 | Commands/Skills |
| `substituteUserConfigInContent()` | Skill/Agent prose 替换 | 发送给模型的内容 |

**替换示例:**

```markdown
# Skill 内容

API Token: ${user_config.apiToken}
Plugin Root: ${CLAUDE_PLUGIN_ROOT}
Data Directory: ${CLAUDE_PLUGIN_DATA}

Run command with token:
!`curl -H "Authorization: Bearer ${user_config.apiToken}" https://api.example.com`
```

---

## 关键代码路径索引

### 启动加载路径

```
main.tsx:282
  → loadAllPluginsCacheOnly() [pluginLoader.ts:3137]
    → getInlinePlugins() [bootstrap/state.ts]
    → getBuiltinPlugins() [builtinPlugins.ts:57]
    → loadPluginsFromMarketplaces() [pluginLoader.ts:1885+]
      → getMarketplaceCacheOnly() [marketplaceManager.ts]
      → getPluginByIdCacheOnly() [marketplaceManager.ts]
      → resolvePluginPath() [pluginLoader.ts:266]
      → loadPluginManifest() [pluginLoader.ts]
      → createPluginFromPath() [pluginLoader.ts:1348]
```

### 组件注册路径

```
QueryEngine.ts:536
  → loadAllPluginsCacheOnly()
  → [并行组件加载]:
    → getPluginCommands() [loadPluginCommands.ts:414]
    → getPluginSkills() [loadPluginCommands.ts:840]
    → loadPluginAgents() [loadPluginAgents.ts:231]
    → loadPluginHooks() [loadPluginHooks.ts:91]
    → extractMcpServersFromPlugins() [mcpPluginIntegration.ts:366]
    → extractLspServersFromPlugins() [lspPluginIntegration.ts:363]
```

### Skill 执行路径

```
SkillTool.ts:122
  → [context: 'fork']:
    executeForkedSkill() [forkedAgent.ts]
      → prepareForkedCommandContext()
      → runAgent() [AgentTool/runAgent.ts]
  → [context: 'inline']:
    getPromptForCommand() → 注入对话
```

### Hook 触发路径

```
QueryEngine.ts (事件触发)
  → STATE.registeredHooks[event] [bootstrap/state.ts]
  → Hook callback 执行
  → [Plugin hook matcher]:
      检查 pluginRoot 匹配启用插件
      执行 hooks 配置中的回调
```

---

## 核心文件索引

| 分类 | 文件 | 功能 |
|------|------|------|
| **核心类型** | `src/types/plugin.ts` | LoadedPlugin, PluginError, PluginLoadResult, BuiltinPluginDefinition |
| **Manifest Schema** | `src/utils/plugins/schemas.ts` | PluginManifestSchema, MarketplaceSourceSchema, UserConfig Schema |
| **插件加载器** | `src/utils/plugins/pluginLoader.ts` | loadAllPluginsCacheOnly, resolvePluginPath, createPluginFromPath |
| **Marketplace** | `src/utils/plugins/marketplaceManager.ts` | Marketplace 加载、缓存、插件查找 |
| **Commands** | `src/utils/plugins/loadPluginCommands.ts` | getPluginCommands, getPluginSkills, createPluginCommand |
| **Hooks** | `src/utils/plugins/loadPluginHooks.ts` | loadPluginHooks, setupPluginHookHotReload |
| **Agents** | `src/utils/plugins/loadPluginAgents.ts` | loadPluginAgents, agent frontmatter 解析 |
| **MCP** | `src/utils/plugins/mcpPluginIntegration.ts` | extractMcpServersFromPlugins, MCPB handling |
| **MCPB** | `src/utils/plugins/mcpbHandler.ts` | MCP Bundle 文件下载和解压 |
| **LSP** | `src/utils/plugins/lspPluginIntegration.ts` | extractLspServersFromPlugins, 路径验证 |
| **用户配置** | `src/utils/plugins/pluginOptionsStorage.ts` | loadPluginOptions, savePluginOptions, 变量替换 |
| **目录配置** | `src/utils/plugins/pluginDirectories.ts` | getPluginsDirectory, getPluginDataDir |
| **策略** | `src/utils/plugins/pluginPolicy.ts` | isPluginBlockedByPolicy |
| **Marketplace Helpers** | `src/utils/plugins/marketplaceHelpers.ts` | isSourceAllowedByPolicy |
| **依赖解析** | `src/utils/plugins/dependencyResolver.ts` | verifyAndDemote |
| **验证** | `src/utils/plugins/validatePlugin.ts` | validateManifest, validatePluginContents |
| **内置插件** | `src/plugins/builtinPlugins.ts` | BUILTIN_PLUGINS Map, registerBuiltinPlugin |
| **Skill 执行** | `src/tools/SkillTool/SkillTool.ts` | executeForkedSkill, Skill tool definition |
| **Forked Agent** | `src/utils/forkedAgent.ts` | prepareForkedCommandContext |

---

## 设计亮点

### 1. 身份格式设计

```
pluginId = "${name}@${marketplace}"
```

**设计智慧**:
- 唯一标识，跨 marketplace 无冲突
- 易于解析：`parsePluginIdentifier(pluginId)`
- 支持多种来源：builtin, inline, marketplace

### 2. 缓存与数据分离

```
cache/{marketplace}/{plugin}/{version}/  # 版本化，更新时丢弃
data/{sanitized-plugin-id}/              # 持久化，跨版本保留
```

**设计智慧**:
- Cache: 更新插件时自动清理旧版本
- Data: 用户数据持久化，插件升级不丢失
- 清晰的用途区分

### 3. PluginError 类型安全

25+ 种判别联合错误类型，而非字符串匹配:

```typescript
// 类型安全的错误处理
switch (error.type) {
  case 'marketplace-blocked-by-policy':
    // TypeScript 知道这里有 marketplace, blockedByBlocklist 等字段
    break
  case 'dependency-unsatisfied':
    // TypeScript 知道这里有 dependency, reason 字段
    break
}
```

**设计智慧**:
- 编译时类型检查
- 错误信息结构化，便于 UI 展示
- 避免 "error.message.includes()" 的脆弱匹配

### 4. Agent 安全限制

```typescript
// Plugin agents 不能设置:
// - permissionMode (权限升级)
// - hooks (静默回调)
// - mcpServers (未审核服务)
```

**设计智慧**:
- 安装时批准 → 执行时限制
- 防止插件利用 agent 配置绕过安全检查
- 明确的权限边界

### 5. 用户配置敏感分离

```
sensitive: true  → keychain
sensitive: false → settings.json
```

**设计智慧**:
- API token 等敏感数据加密存储
- 非敏感配置可版本控制
- 重配置时清理残留数据

### 6. Marketplace 层次化发现

```
known_marketplaces.json → marketplace catalog → plugin entry → plugin manifest
```

**设计智慧**:
- 逐步发现，每层可独立缓存
- 支持企业私有 marketplace
- 策略检查在每层都有

### 7. Hooks 热重载

```typescript
settingsChangeDetector.subscribe(source => {
  if (source === 'policySettings') {
    void loadPluginHooks()  // 重新加载
  }
})
```

**设计智慧**:
- 策略变更立即生效
- 无需重启 CLI
- 清晰的订阅模型

---

## 完整示例：插件安装与启用

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    插件安装与启用完整流程                                     │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [1] 用户运行 /plugin 命令                                                  │
│      ───────────────────────────────────────────────────────────────────── │
│      Plugin UI 显示 marketplace catalog                                    │
│      用户选择 "my-plugin@claude-code-marketplace"                           │
│                                                                             │
│  [2] 插件下载                                                               │
│      ───────────────────────────────────────────────────────────────────── │
│      resolvePluginPath()                                                    │
│      ├── GitHub source → git clone                                         │
│      ├── NPM source → npm install                                          │
│      └── URL source → git clone                                            │
│                                                                             │
│      copyPluginToVersionedCache()                                           │
│      → ~/.claude/plugins/cache/claude-code-marketplace/my-plugin/1.0.0/    │
│                                                                             │
│  [3] Manifest 验证                                                          │
│      ───────────────────────────────────────────────────────────────────── │
│      validateManifest(plugin.json)                                          │
│      ├── Schema validation (Zod strict)                                    │
│      ├── Path traversal check                                              │
│      └── Content validation                                                │
│                                                                             │
│  [4] 用户配置（如果 userConfig 定义）                                        │
│      ───────────────────────────────────────────────────────────────────── │
│      PluginOptionsFlow 显示配置 UI                                          │
│      用户填写 apiToken (sensitive: true)                                    │
│      → 存储到 keychain                                                      │
│                                                                             │
│  [5] 启用插件                                                               │
│      ───────────────────────────────────────────────────────────────────── │
│      settings.enabledPlugins["my-plugin@claude-code-marketplace"] = true   │
│      → 写入 settings.json                                                  │
│                                                                             │
│  [6] 组件加载                                                               │
│      ───────────────────────────────────────────────────────────────────── │
│      loadAllPluginsCacheOnly()                                              │
│      ├── getPluginCommands() → commands 注册                               │
│      ├── loadPluginHooks() → hooks 注册                                    │
│      ├── extractMcpServers() → MCP servers 启动                            │
│      └── loadPluginAgents() → agents 可用                                  │
│                                                                             │
│  [7] 运行时                                                                  │
│      ───────────────────────────────────────────────────────────────────── │
│      用户: /my-plugin:build                                                 │
│      → createPluginCommand().getPromptForCommand()                         │
│      → ${user_config.apiToken} 替换                                        │
│      → 内容注入对话                                                         │
│      → Agent 执行命令                                                       │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 总结

Claude Code 的插件系统是一个完整的扩展生态基础设施：

| 特性 | 实现方式 | 效果 |
|------|---------|------|
| **身份唯一性** | `name@marketplace` 格式 | 跨 marketplace 无冲突 |
| **缓存分离** | cache (版本化) + data (持久化) | 更新不丢失用户数据 |
| **组件丰富** | Commands, Skills, Hooks, Agents, MCP, LSP | 多维度扩展能力 |
| **类型安全** | PluginError 判别联合 | 编译时错误检查 |
| **安全机制** | 官方名称保护、策略阻断、Agent限制 | 防止滥用 |
| **用户配置** | sensitive/non-sensitive 分离 | API token 加密存储 |
| **热重载** | settingsChangeDetector 订阅 | 策略变更即时生效 |

**核心架构洞察**:

1. **Marketplace 层次化发现**:
   - `known_marketplaces.json` → marketplace catalog → plugin entry → plugin manifest
   - 每层独立缓存，策略检查贯穿全流程

2. **版本化缓存管理**:
   - `cache/{marketplace}/{plugin}/{version}/` 结构
   - 更新插件时旧版本自动 orphaned
   - GC 定期清理孤立缓存

3. **组件注册并行化**:
   - `loadAllPluginsCacheOnly()` 返回后
   - Commands, Hooks, Agents, MCP, LSP 并行加载
   - 减少启动延迟

4. **安全边界设计**:
   - 安装时：manifest 验证 + 用户配置 + 策略检查
   - 执行时：Agent 限制 + Hooks 热重载 + 路径验证
   - 双重防护，纵深防御

这个设计让 Claude Code 能够安全、可控地集成第三方扩展，形成丰富的插件生态系统。