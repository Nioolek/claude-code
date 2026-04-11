# Claude Code 支持的命令完整列表

本文档收集了 Claude Code 当前支持的所有内置命令。

## 命令分类

### 📁 项目与文件管理

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/add-dir` | 添加目录到工作区 | `commands/add-dir/index.ts` |
| `/branch` | 管理 Git 分支 | `commands/branch/index.ts` |
| `/chrome` | 浏览器相关操作 | `commands/chrome/index.ts` |
| `/compact` | 压缩对话上下文 | `commands/compact/index.ts` |
| `/copy` | 复制内容到剪贴板 | `commands/copy/index.ts` |
| `/desktop` | 桌面截图/操作 | `commands/desktop/index.ts` |
| `/diff` | 查看代码差异 | `commands/diff/index.ts` |
| `/export` | 导出会话/数据 | `commands/export/index.ts` |
| `/files` | 文件操作 | `commands/files/index.ts` |
| `/init` | 初始化项目 | `commands/init.ts` |
| `/memory` | 管理长期记忆 | `commands/memory/index.ts` |
| `/mobile` | 移动端相关 | `commands/mobile/index.ts` |
| `/plan` | 查看/管理计划 | `commands/plan/index.ts` |
| `/rename` | 重命名会话 | `commands/rename/index.ts` |
| `/resume` | 恢复之前的会话 | `commands/resume/index.ts` |
| `/rewind` | 回退到之前的状态 | `commands/rewind/index.ts` |
| `/tag` | 给会话添加标签 | `commands/tag/index.ts` |
| `/tasks` | 任务管理 | `commands/tasks/index.ts` |

### ⚙️ 配置与设置

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/color` | 颜色主题设置 | `commands/color/index.ts` |
| `/config` | 查看/修改配置 | `commands/config/index.ts` |
| `/effort` | 设置努力程度 | `commands/effort/index.ts` |
| `/fast` | 快速模式切换 | `commands/fast/index.ts` |
| `/keybindings` | 键盘快捷键设置 | `commands/keybindings/index.ts` |
| `/model` | 切换模型 | `commands/model/index.ts` |
| `/output-style` | 输出样式设置 | `commands/output-style/index.ts` |
| `/passes` | 设置传递次数 | `commands/passes/index.ts` |
| `/permissions` | 权限管理 | `commands/permissions/index.ts` |
| `/privacy-settings` | 隐私设置 | `commands/privacy-settings/index.ts` |
| `/rate-limit-options` | 速率限制选项 | `commands/rate-limit-options/index.ts` |
| `/sandbox` | 沙盒模式切换 | `commands/sandbox-toggle/index.ts` |
| `/theme` | 主题切换 | `commands/theme/index.ts` |
| `/vim` | Vim 模式切换 | `commands/vim/index.ts` |

### 🔧 工具与集成

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/agents` | 多智能体管理 | `commands/agents/index.ts` |
| `/btw` | 附加上下文信息 | `commands/btw/index.ts` |
| `/ide` | IDE 集成 | `commands/ide/index.ts` |
| `/install-github-app` | 安装 GitHub 应用 | `commands/install-github-app/index.ts` |
| `/install-slack-app` | 安装 Slack 应用 | `commands/install-slack-app/index.ts` |
| `/mcp` | MCP 服务器管理 | `commands/mcp/index.ts` |
| `/plugin` | 插件管理 | `commands/plugin/index.ts` |
| `/reload-plugins` | 重新加载插件 | `commands/reload-plugins/index.ts` |
| `/remote-env` | 远程环境配置 | `commands/remote-env/index.ts` |
| `/skills` | 技能管理 | `commands/skills/index.ts` |
| `/terminal-setup` | 终端设置 | `commands/terminalSetup/index.ts` |

### 📊 分析与统计

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/cost` | 查看 API 成本 | `commands/cost/index.ts` |
| `/extra-usage` | 额外用量统计 | `commands/extra-usage/index.ts` |
| `/heapdump` | 堆转储分析 | `commands/heapdump/index.ts` |
| `/stats` | 会话统计 | `commands/stats/index.ts` |
| `/status` | 查看状态 | `commands/status/index.ts` |
| `/usage` | 用量统计 | `commands/usage/index.ts` |
| `/usage-report` | 用量报告 | - |

### 🔐 认证与会话

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/clear` | 清除当前会话 | `commands/clear/index.ts` |
| `/exit` | 退出应用 | `commands/exit/index.ts` |
| `/help` | 显示帮助信息 | `commands/help/index.ts` |
| `/login` | 登录 | `commands/login/index.ts` |
| `/logout` | 登出 | `commands/logout/index.ts` |
| `/session` | 会话管理 | `commands/session/index.ts` |
| `/statusline` | 状态行设置 | `commands/statusline.tsx` |

### 📝 代码审查与提交

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/commit` | 提交代码 | `commands/commit.ts` |
| `/commit-push-pr` | 提交并推送 PR | `commands/commit-push-pr.ts` |
| `/pr-comments` | PR 评论处理 | `commands/pr_comments/index.ts` |
| `/release-notes` | 生成发布说明 | `commands/release-notes/index.ts` |
| `/review` | 代码审查 | `commands/review.ts` |
| `/security-review` | 安全审查 | `commands/security-review.ts` |
| `/ultrareview` | 深度代码审查 | `commands/review.ts` |

### 🧠 AI 增强功能

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/advisor` | 顾问模式 | `commands/advisor.ts` |
| `/context` | 查看上下文 | `commands/context/index.ts` |
| `/feedback` | 提交反馈 | `commands/feedback/index.ts` |
| `/think-back` | 回顾分析 | `commands/thinkback/index.ts` |
| `/thinkback-play` | 回顾演练 | `commands/thinkback-play/index.ts` |

### 🏥 诊断与维护

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/break-cache` | 清除缓存 | `commands/break-cache/index.ts` |
| `/doctor` | 诊断问题 | `commands/doctor/index.ts` |
| `/hooks` | Hook 管理 | `commands/hooks/index.ts` |
| `/upgrade` | 升级应用 | `commands/upgrade/index.ts` |
| `/version` | 查看版本 | `commands/version.ts` |

---

## 条件启用的命令（特性标志控制）

以下命令仅在特定特性标志启用时可用：

| 命令 | 特性标志 | 描述 |
|------|---------|------|
| `/brief` | `KAIROS` / `KAIROS_BRIEF` | 简报功能 |
| `/assistant` | `KAIROS` | 助手功能 |
| `/bridge` | `BRIDGE_MODE` | 桥接模式 |
| `/remote-control` | `DAEMON` + `BRIDGE_MODE` | 远程控制 |
| `/voice` | `VOICE_MODE` | 语音模式 |
| `/force-snip` | `HISTORY_SNIP` | 强制截断历史 |
| `/workflows` | `WORKFLOW_SCRIPTS` | 工作流脚本 |
| `/web-setup` | `CCR_REMOTE_SETUP` | 远程设置 |
| `/fork` | `FORK_SUBAGENT` | 子代理分叉 |
| `/buddy` | `BUDDY` | Buddy 功能 |
| `/peers` | `UDS_INBOX` | 同行通信 |
| `/torch` | `TORCH` | Torch 功能 |
| `/ultraplan` | `ULTRAPLAN` | 超级计划 |
| `/subscribe-pr` | `KAIROS_GITHUB_WEBHOOKS` | PR 订阅 |

---

## 内部专用命令（仅 Anthropic 员工可用）

以下命令仅在 `USER_TYPE=ant` 且非演示环境时可用：

| 命令 | 描述 | 源代码 |
|------|------|--------|
| `/backfill-sessions` | 回填会话数据 | `commands/backfill-sessions/index.ts` |
| `/bughunter` | Bug 猎人模式 | `commands/bughunter/index.ts` |
| `/ctx_viz` | 上下文可视化 | `commands/ctx_viz/index.ts` |
| `/good-claude` | Good Claude 模式 | `commands/good-claude/index.ts` |
| `/init-verifiers` | 初始化验证器 | `commands/init-verifiers.ts` |
| `/issue` | Issue 管理 | `commands/issue/index.ts` |
| `/onboarding` | 入职引导 | `commands/onboarding/index.ts` |
| `/share` | 分享会话 | `commands/share/index.ts` |
| `/summary` | 生成摘要 | `commands/summary/index.ts` |
| `/teleport` | 瞬移功能 | `commands/teleport/index.ts` |
| `/autofix-pr` | 自动修复 PR | `commands/autofix-pr/index.ts` |
| `/bridge-kick` | 桥接踢出 | `commands/bridge-kick.ts` |
| `/env` | 环境变量 | `commands/env/index.ts` |
| `/oauth-refresh` | OAuth 刷新 | `commands/oauth-refresh/index.ts` |
| `/debug-tool-call` | 调试工具调用 | `commands/debug-tool-call/index.ts` |
| `/agents-platform` | 智能体平台 | `commands/agents-platform/index.ts` |
| `/ant-trace` | 追踪功能 | `commands/ant-trace/index.js` |
| `/perf-issue` | 性能问题 | `commands/perf-issue/index.ts` |
| `/mock-limits` | 模拟限制 | `commands/mock-limits/index.ts` |
| `/reset-limits` | 重置限制 | `commands/reset-limits/index.ts` |

---

## 命令总数统计

| 类别 | 数量 |
|------|------|
| **核心命令** | ~60 个 |
| **条件启用命令** | ~12 个 |
| **内部专用命令** | ~20 个 |
| **总计** | **~92 个** |

---

## 命令注册机制

命令在 `src/commands.ts` 中注册，通过 `COMMANDS` 数组统一管理：

```typescript
const COMMANDS = memoize((): Command[] => [
  addDir,
  advisor,
  agents,
  branch,
  btw,
  // ... 更多命令
  ...(process.env.USER_TYPE === 'ant' && !process.env.IS_DEMO
    ? INTERNAL_ONLY_COMMANDS
    : []),
])
```

### 命令接口

```typescript
interface Command {
  name: string
  description?: string
  getPromptForCommand: (args: string[], context: CommandContext) => Promise<Prompt>
  isEnabled?: () => boolean
  isHidden?: boolean
}
```

---

## 使用方式

在 Claude Code 中输入 `/` 后跟命令名即可执行命令：

```
/compact          # 压缩当前会话
/config           # 查看配置
/help             # 显示帮助
/doctor           # 诊断问题
```

某些命令支持参数：

```
/compact manual   # 手动压缩
/config set key value   # 设置配置项
```

---

## 相关文件

| 文件 | 描述 |
|------|------|
| `src/commands.ts` | 命令注册和导出 |
| `src/types/command.ts` | 命令类型定义 |
| `src/commands/*/index.ts` | 各命令的具体实现 |

---

*文档生成时间：2026-04-06*
*基于代码版本：G:\code\claude-code*
