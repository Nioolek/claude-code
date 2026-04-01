# Claude Code 入口启动流程 FAQ

## 1. Worktree 作用是什么？

**Worktree** 是 Git 的一种特性，允许在同一个仓库中创建多个工作目录。在 Claude Code 中，worktree 用于：

### 核心功能
- **会话隔离**：为每个开发会话创建独立的 git worktree，使不同会话的工作互不干扰
- **分支隔离**：可以在不同的 worktree 中同时处理不同的分支，无需频繁切换
- **安全沙箱**：worktree 创建后，会话在独立的目录中运行，保护主工作目录

### 代码位置
```typescript
// src/setup.ts:288-291
if (worktreeEnabled) {
  const worktreeSession = await createWorktreeForSession(...);
  process.chdir(worktreeSession.worktreePath);
}
```

### 启用方式
用户可以通过 `--worktree` 参数启用此功能。

---

## 2. 起这么多子进程会不会有问题？

Claude Code 在启动时会启动多个子进程，这是**有意为之的性能优化设计**：

### 子进程类型

| 子进程 | 用途 | 运行时机 |
|--------|------|----------|
| **MDM 设置读取** | 读取 macOS 的 `plutil` 或 Windows 的注册表 | 模块评估阶段 |
| **Keychain 预取** | 读取 macOS 钥匙串中的 OAuth 凭证和 API 密钥 | 模块评估阶段 |
| **API 预连接** | 建立 TCP+TLS 连接 | 初始化阶段 |

### 为什么不会有问题？

1. **并行执行，而非串行**
   - 子进程在模块导入的同步阻塞期间**并行**运行
   - 总启动时间 = max(子进程时间, 模块导入时间)，而非累加

2. **性能收益明显**
   ```
   MDM 设置读取：~20ms（与导入并行）
   Keychain 读取：~65ms（原本串行，现在并行）
   ```

3. **优雅降级**
   - 子进程失败不会阻塞启动
   - 使用 Promise 封装，可等待也可忽略

### 代码示例
```typescript
// src/main.tsx:12-20
import { startMdmRawRead } from './utils/settings/mdm/rawRead.js';
startMdmRawRead();  // 立即启动，不等待

import { startKeychainPrefetch } from './utils/secureStorage/keychainPrefetch.js';
startKeychainPrefetch();  // 并行启动

// 后续在 preAction 钩子中等待结果
await Promise.all([ensureMdmSettingsLoaded(), ensureKeychainPrefetchCompleted()]);
```

---

## 3. OpenTelemetry 起什么作用？

**OpenTelemetry** 是一个可观测性框架，用于分布式追踪、指标收集和日志记录。

### 在 Claude Code 中的作用

1. **分布式追踪**
   - 记录请求在各个组件间的流转
   - 追踪 LLM API 调用的延迟和性能

2. **性能指标收集**
   - 监控启动时间、响应延迟
   - 追踪工具调用的执行时间

3. **问题诊断**
   - 当出现性能问题时，可以通过追踪数据定位瓶颈
   - 帮助开发者理解系统行为

### 懒加载原因
OpenTelemetry 模块体积约 **400KB**，为了优化启动性能，采用懒加载策略：

```typescript
// src/entrypoints/init.ts:305-309
void Promise.all([
  import('../services/analytics/firstPartyEventLogger.js'),
  import('../services/analytics/growthbook.js'),
]).then(/* ... */);
```

---

## 4. 懒加载了哪些模块？

Claude Code 采用**懒加载策略**来优化启动性能，以下模块被延迟加载：

### 懒加载模块列表

| 模块 | 体积 | 懒加载原因 |
|------|------|-----------|
| **OpenTelemetry** | ~400KB | 可观测性功能非启动必需 |
| **firstPartyEventLogger** | 较大 | 事件日志可在后台初始化 |
| **growthbook** | 较大 | Feature flags 可稍后加载 |
| **JetBrains 检测** | 中等 | IDE 集成功能非必需 |
| **远程设置加载** | 中等 | 可在后台异步获取 |
| **LSP 管理器** | 较大 | 语言服务器仅在需要时启动 |
| **插件 Hooks** | 可变 | 用户自定义 hooks 延迟加载 |

### 懒加载实现方式

```typescript
// 1. void 关键字表示"火即忘"（fire-and-forget）
void populateOAuthAccountInfoIfNeeded();
void initJetBrainsDetection();

// 2. 动态 import
void import('./utils/plugins/loadPluginHooks.js')
  .then(m => m.loadPluginHooks());

// 3. Promise.all 并行懒加载
void Promise.all([
  import('../services/analytics/firstPartyEventLogger.js'),
  import('../services/analytics/growthbook.js'),
]).then(/* ... */);
```

### 特性标志控制的条件加载

某些模块通过编译时特性标志决定是否加载：

```typescript
// 编译时死代码消除
const coordinatorModeModule = feature('COORDINATOR_MODE')
  ? require('./coordinator/coordinatorMode.js')
  : null;

const assistantModule = feature('KAIROS')
  ? require('./assistant/index.js')
  : null;
```

---

## 5. 性能分析的作用是什么？

Claude Code 内置了**启动性能分析器** (`src/utils/startupProfiler.ts`)，用于：

### 核心功能

1. **性能瓶颈定位**
   - 记录各个启动阶段的时间戳
   - 帮助开发者找到需要优化的代码路径

2. **持续优化追踪**
   - 比较不同版本的性能变化
   - 验证优化措施是否有效

### 使用方式

```typescript
// src/main.tsx:9-11
import { profileCheckpoint } from './utils/startupProfiler.js';
profileCheckpoint('main_tsx_entry');
// ... 模块导入 ...
profileCheckpoint('main_tsx_imports_loaded');
```

### 分析的检查点

| 检查点 | 含义 |
|--------|------|
| `main_tsx_entry` | 入口文件开始评估 |
| `main_tsx_imports_loaded` | 所有静态导入完成 |
| `main_function_start` | main() 函数开始执行 |
| `init_complete` | 初始化完成 |
| `repl_ready` | REPL 界面就绪 |

### 输出方式

- **采样日志**：部分会话会上报性能数据用于分析
- **详细分析**：可通过特定标志启用详细模式

### 设计收益

```
性能优化循环：
分析 → 发现瓶颈 → 优化 → 验证 → 分析
```

通过这个分析器，Claude Code 实现了**亚秒级启动**，典型启动时间在 200-500ms 范围内。

---

## 附录：Worktree 和 Branch 的关系（通俗解释）

### 一句话总结

> **Branch 是"平行宇宙"，Worktree 是"同时进入多个平行宇宙的入口"。**

### 用游戏来理解

想象你在玩一个 RPG 游戏：

| 概念 | 游戏类比 | Git 含义 |
|------|----------|----------|
| **Branch** | 存档槽 | 代码的不同版本线 |
| **Worktree** | 打开的游戏窗口 | 一个可操作的工作目录 |

**没有 Worktree 时：**
- 你只能同时打开一个存档（当前分支）
- 想玩另一个存档？必须先退出，再读取

**有了 Worktree：**
- 你可以同时打开多个游戏窗口
- 窗口 A 玩存档 1（main 分支）
- 窗口 B 玩存档 2（feature 分支）
- 互不干扰，随时切换

### 图解

```
┌─────────────────────────────────────────────────────────┐
│                    Git 仓库 (.git)                       │
│                                                         │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐            │
│   │ branch: │    │ branch: │    │ branch: │            │
│   │  main   │    │ feature │    │  bugfix │            │
│   └────┬────┘    └────┬────┘    └────┬────┘            │
│        │              │              │                  │
└────────│──────────────│──────────────│──────────────────┘
         │              │              │
         ▼              ▼              ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │ worktree│    │ worktree│    │ worktree│
    │   (主)   │    │   (A)   │    │   (B)   │
    │         │    │         │    │         │
    │ 你在这   │    │ 同事在那 │    │ 暂时没人 │
    └─────────┘    └─────────┘    └─────────┘
         │              │              │
         ▼              ▼              ▼
      main/         feature/       bugfix/
     代码文件        代码文件        代码文件
```

### 没有 Worktree 的痛点

```bash
# 你正在 feature 分支开发新功能
git checkout feature
# ... 写了一半代码 ...

# 突然！生产环境有 bug 需要紧急修复
# 你只能：
git stash              # 暂存当前工作
git checkout main       # 切换分支
# ... 修复 bug ...
git checkout feature    # 切回来
git stash pop           # 恢复工作
# 希望 stash 没有冲突...
```

### 有 Worktree 的优雅

```bash
# 你正在 feature 分支开发
cd ~/project-feature/

# 突然！生产环境有 bug
# 打开另一个终端窗口
cd ~/project-main/
# ... 直接修复 bug，不用 stash ...

# 两个窗口互不影响
```

### Claude Code 中的 Worktree 用途

Claude Code 用 Worktree 做**会话隔离**：

```
会话 A (main 分支)
    │
    └──► worktree: ~/.claude/worktrees/session-abc/
              │
              └──► 独立的代码副本，安全的实验环境

会话 B (feature 分支)
    │
    └──► worktree: ~/.claude/worktrees/session-xyz/
              │
              └──► 另一个独立环境
```

**好处：**
1. AI 修改代码不会弄乱你的主工作目录
2. 多个 Claude 会话可以同时运行
3. 出问题直接删掉 worktree，主目录完好无损

### 关键区别总结

| | Branch | Worktree |
|---|--------|----------|
| **是什么** | 版本历史的一条线 | 一个可操作的目录 |
| **数量关系** | 一个 branch 可以被多个 worktree 检出 | 一个 worktree 只能检出一个 branch |
| **物理存在** | 在 `.git` 里（抽象的） | 在磁盘上（实实在在的文件夹） |
| **切换成本** | 需要 stash、切分支、恢复 | 直接 `cd` 到另一个目录 |
| **典型用途** | 管理不同版本的开发线 | 同时操作多个分支 |

### 一句话再总结

> **Branch 是存档，Worktree 是你打开存档的那个窗口。一个存档可以在多个窗口打开，但一个窗口只能显示一个存档。**