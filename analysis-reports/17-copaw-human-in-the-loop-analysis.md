# CoPaw Human in the Loop 实现机制分析

**仓库**: https://github.com/agentscope-ai/CoPaw  
**解读日期**: 2026-04-13  
**核心文件**: `src/qwenpaw/agents/tool_guard_mixin.py`

---

## 1. 系统概述

CoPaw 实现了一套完整的 **Human in the Loop (HITL)** 机制，通过 **Tool Guard 系统** 在敏感工具执行前拦截并请求用户审批。这套系统的核心设计目标是：

```
┌─────────────────────────────────────────────────────────────┐
│              CoPaw Human in the Loop 设计目标                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 安全优先：敏感操作必须经过用户确认                        │
│  2. 最小干扰：低风险操作自动放行，不打断 Agent 执行流           │
│  3. 可扩展：支持自定义风险检测规则 (Guardians)                │
│  4. 会话隔离：每个 session 独立管理审批队列                   │
│  5. 超时保护：审批超时自动拒绝，避免无限等待                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心架构

### 2.1 组件图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CoPaw HITL 架构概览                               │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│   ReActAgent         │
│   (with ToolGuard    │
│   Mixin)              │
└──────────┬───────────┘
           │
           │ _acting(tool_call)
           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  ToolGuardMixin      │────►│  ToolGuardEngine     │
│  • _tool_guard_lock  │     │  • guardians[]       │
│  • _tool_guard_engine│     │  • guard()           │
│  • _approval_service │     │  • is_guarded()      │
└──────────┬───────────┘     │  • is_denied()       │
           │                └──────────┬───────────┘
           │                           │
           │                           │ guard(tool_name, tool_input)
           │                           ▼
           │                ┌──────────────────────┐
           │                │  BaseToolGuardian    │
           │                │  • RuleBasedGuardian │
           │                │  • FilePathGuardian  │
           │                └──────────────────────┘
           │
           │ needs_approval
           ▼
┌──────────────────────┐
│  ApprovalService     │
│  • _pending{}        │
│  • _completed{}      │
│  • create_pending()  │
│  • resolve_request() │
└──────────┬───────────┘
           │
           │ /daemon approve
           ▼
┌──────────────────────┐
│   User (Channel)     │
│   • DingTalk         │
│   • iMessage         │
│   • Console          │
└──────────────────────┘
```

---

### 2.2 核心类与文件

| 文件 | 类/函数 | 职责 |
|------|---------|------|
| `tool_guard_mixin.py` | `ToolGuardMixin` | Agent 拦截层，重写 `_acting()` 和 `_reasoning()` |
| `tool_guard_mixin.py` | `_GuardAction` | 轻量级决策容器 (kind, tool_name, tool_input, guard_result) |
| `engine.py` | `ToolGuardEngine` | 协调所有 Guardians，执行风险检测 |
| `guardians/rule_guardian.py` | `RuleBasedToolGuardian` | 基于 YAML 规则的风险检测 |
| `guardians/file_guardian.py` | `FilePathToolGuardian` | 文件路径风险检测 |
| `models.py` | `GuardFinding` | 单个风险发现记录 |
| `models.py` | `ToolGuardResult` | 风险检测汇总结果 |
| `approval.py` | `ApprovalDecision` | 审批结果枚举 (APPROVED/DENIED/TIMEOUT) |
| `approvals/service.py` | `ApprovalService` | 审批记录管理 (pending/completed) |
| `daemon_commands.py` | `run_daemon_approve()` | 处理 `/daemon approve` 命令 |

---

## 3. 执行流程详解

### 3.1 完整 HITL 流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CoPaw Human in the Loop 完整流程                      │
└─────────────────────────────────────────────────────────────────────────┘

Agent 生成 tool_call
        │
        ▼
┌─────────────────────────────────┐
│ ToolGuardMixin._acting()        │  ◄── 拦截点
│ (acquire _tool_guard_lock)      │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ _decide_guard_action()          │
│ 1. 检查是否在 denied_tools      │
│ 2. 检查是否有预批准 (pre-approve)│
│ 3. 运行 Guardians 检测风险       │
└───────────────┬─────────────────┘
                │
        ┌───────┴────────┬────────────────┐
        │                │                │
        ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ auto_denied  │ │ preapproved  │ │ needs_approval│
│ (自动拒绝)    │ │ (预批准放行)  │ │ (需要审批)    │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       │                │                ▼
       │                │      ┌─────────────────────────┐
       │                │      │ _acting_with_approval() │
       │                │      │ 1. 创建 PendingApproval │
       │                │      │ 2. 发送拒绝消息给用户   │
       │                │      │ 3. 等待用户审批         │
       │                │      │ 4. await future         │
       │                │      └───────────┬─────────────┘
       │                │                  │
       │                │                  │ 用户发送 /daemon approve
       │                │                  │
       │                │                  ▼
       │                │      ┌─────────────────────────┐
       │                │      │ ApprovalService.        │
       │                │      │ resolve_request()       │
       │                │      │ future.set_result()     │
       │                │      └───────────┬─────────────┘
       │                │                  │
       │                │                  ▼
       │                │      ┌─────────────────────────┐
       │                │      │ _run_approved_tool_call()│
       │                │      │ super()._acting()       │
       │                │      │ 执行实际工具调用         │
       │                │      └───────────┬─────────────┘
       │                │                  │
       │                │                  ▼
       │                │      ┌─────────────────────────┐
       │                │      │ _reasoning()            │
       │                │      │ 检查 replay_done        │
       │                │      │ 继续下一个 tool_call    │
       │                │      └─────────────────────────┘
       │                │
       ▼                ▼
┌─────────────────────────────────┐
│ _acting_auto_denied()           │
│ 发送拦截消息，不执行工具         │
└─────────────────────────────────┘
```

---

### 3.2 _decide_guard_action() 决策逻辑

```python
async def _decide_guard_action(
    self,
    tool_call: dict[str, Any],
) -> "_GuardAction | None":
    """Decide what guard action to take (runs under lock).
    
    Returns:
        _GuardAction: 描述要执行的动作，或 None 表示放行到 super()._acting()
    """
    engine = self._tool_guard_engine
    tool_name = str(tool_call.get("name", ""))
    tool_input = tool_call.get("input", {})
    
    # 1. 工具未命名或 guard 未启用 → 放行
    if not tool_name or not engine.enabled:
        return None

    # 2. 工具在 denied_tools 列表 → 自动拒绝
    if engine.is_denied(tool_name):
        return _GuardAction("auto_denied", tool_name, tool_input)

    # 3. 检查是否有预批准 (one-shot approval token)
    guarded = engine.is_guarded(tool_name)
    if guarded and await self._consume_preapproval(tool_name, tool_input):
        return _GuardAction("preapproved", tool_name, tool_input)

    # 4. 运行 Guardians 检测风险
    guard_result = engine.guard(
        tool_name,
        tool_input,
        only_always_run=not guarded,  # 非 guarded 工具只运行 always_run guardians
    )
    
    # 5. 有风险发现且有 session_id → 需要审批
    if guard_result is not None and guard_result.findings:
        if self._should_require_approval():
            return _GuardAction(
                "needs_approval",
                tool_name,
                tool_input,
                guard_result=guard_result,
            )
    
    # 6. 无风险 → 放行
    return None
```

---

## 4. 风险检测机制 (Guardians)

### 4.1 Guardian 架构

```
┌─────────────────────────────────────────────────────────────┐
│                  Guardian 层次结构                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  BaseToolGuardian (抽象基类)                                 │
│  ├── guard() → ToolGuardResult                              │
│  └── always_run: bool (是否对所有工具运行)                    │
│                                                             │
│  ├── RuleBasedToolGuardian                                  │
│  │   • 加载 YAML 规则文件                                     │
│  │   • 正则匹配工具参数                                       │
│  │   • 支持 exclude_patterns                                 │
│  │                                                          │
│  └── FilePathToolGuardian                                   │
│      • 检测敏感文件路径                                       │
│      • 工作目录感知                                           │
│      • 路径遍历检测                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 风险分类 (GuardThreatCategory)

```python
class GuardThreatCategory(str, Enum):
    COMMAND_INJECTION = "command_injection"        # 命令注入
    DATA_EXFILTRATION = "data_exfiltration"        # 数据泄露
    PATH_TRAVERSAL = "path_traversal"              # 路径遍历
    SENSITIVE_FILE_ACCESS = "sensitive_file_access" # 敏感文件访问
    NETWORK_ABUSE = "network_abuse"                # 网络滥用
    CREDENTIAL_EXPOSURE = "credential_exposure"    # 凭证暴露
    RESOURCE_ABUSE = "resource_abuse"              # 资源滥用
    PROMPT_INJECTION = "prompt_injection"          # 提示注入
    CODE_EXECUTION = "code_execution"              # 代码执行
    PRIVILEGE_ESCALATION = "privilege_escalation"  # 权限提升
```

### 4.3 严重级别 (GuardSeverity)

```python
class GuardSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    SAFE = "SAFE"
```

### 4.4 YAML 规则示例

```yaml
# rules/dangerous_shell_commands.yaml
- id: SHELL_PIPE_TO_EXEC
  tool: execute_shell_command
  params: [command]
  category: command_injection
  severity: HIGH
  patterns:
    - "curl.*\\|.*(?:sh|bash)"
    - "wget.*\\|.*(?:sh|bash)"
  exclude_patterns:
    - "^#"
  description: "Piping downloaded content directly to a shell"
  remediation: "Download to a file first and inspect before execution"

- id: RM_ROOT
  tool: execute_shell_command
  params: [command]
  category: resource_abuse
  severity: CRITICAL
  patterns:
    - "^\\s*rm\\s+-(?:rf|fr)\\s+/"
    - "^\\s*rm\\s+-(?:rf|fr)\\s+\\*"
  description: "Attempting to delete root directory or all files"
  remediation: "Never use rm -rf / or rm -rf *"
```

---

## 5. 审批服务 (ApprovalService)

### 5.1 数据结构

```python
@dataclass
class PendingApproval:
    """In-memory record for one pending approval."""
    request_id: str              # UUID
    session_id: str              # 会话 ID
    user_id: str                 # 用户 ID
    channel: str                 # 渠道 (dingtalk/imessage/console)
    tool_name: str               # 工具名称
    created_at: float            # 创建时间戳
    future: asyncio.Future[ApprovalDecision]  # 异步等待句柄
    status: str = "pending"      # pending/approved/denied/timeout
    resolved_at: float | None = None
    result_summary: str = ""     # 风险摘要
    findings_count: int = 0      # 风险发现数量
    extra: dict[str, Any] = field(default_factory=dict)
```

### 5.2 核心方法

| 方法 | 职责 |
|------|------|
| `create_pending()` | 创建待审批记录，返回 `PendingApproval` |
| `resolve_request(request_id, decision)` | 解决审批请求，设置 future 结果 |
| `get_pending_by_session(session_id)` | 获取 session 的下一个待审批 (FIFO) |
| `consume_approval(session_id, tool_name, tool_params)` | 消费预批准 token |
| `_gc_pending_locked()` | 清理超时的 pending 记录 |
| `_gc_completed_locked()` | 清理已完成的记录 |

### 5.3 超时与垃圾回收

```python
# 超时配置
_GC_MAX_AGE_SECONDS = 3600.0        # 完成记录保留 1 小时
_GC_PENDING_MAX_AGE_SECONDS = 1800.0 # pending 记录 30 分钟超时
_GC_MAX_PENDING = 200               # 最多 200 个 pending 记录
_GC_MAX_COMPLETED = 500             # 最多 500 个完成记录

def _gc_pending_locked(self) -> None:
    """Evict stale pending records."""
    now = time.time()
    
    # 1. 超时清理
    expired = [
        k for k, v in self._pending.items()
        if now - v.created_at > _GC_PENDING_MAX_AGE_SECONDS
    ]
    for k in expired:
        pending = self._pending.pop(k)
        if not pending.future.done():
            pending.future.set_result(ApprovalDecision.TIMEOUT)
        pending.status = "timeout"
        pending.resolved_at = now
        self._completed[k] = pending

    # 2. 溢出清理 (FIFO)
    overflow = len(self._pending) - _GC_MAX_PENDING
    if overflow <= 0:
        return
    ordered = sorted(
        self._pending.items(),
        key=lambda item: item[1].created_at,
    )
    for key, pending in ordered[:overflow]:
        del self._pending[key]
        if not pending.future.done():
            pending.future.set_result(ApprovalDecision.TIMEOUT)
        pending.status = "timeout"
        self._completed[key] = pending
```

---

## 6. 用户交互流程

### 6.1 审批请求消息

当工具被拦截时，Agent 会发送如下消息给用户：

```markdown
⛔ **Tool Blocked / 工具已拦截**

- Tool / 工具: `execute_shell_command`
- Severity / 严重性: `HIGH`
- Findings / 发现: `2`

- [HIGH] Piping downloaded content directly to a shell
- [CRITICAL] Attempting to delete root directory

Remediation / 建议:
Download to a file first and inspect before execution

---
**等待审批 / Waiting for approval**
- 发送 `/daemon approve` 批准执行
- 发送 `/daemon deny` 拒绝执行
- 30 分钟后自动超时拒绝
```

### 6.2 批准命令

```bash
# 批准当前待审批的工具
/daemon approve

# 或使用短别名
/approve
```

### 6.3 批准后的执行

```python
# daemon_commands.py
async def run_daemon_approve(
    _context: DaemonContext,
    session_id: str = "",
) -> str:
    """Resolve the next pending tool-guard approval for *session_id*."""
    from ..approvals import get_approval_service
    from ...security.tool_guard.approval import ApprovalDecision

    svc = get_approval_service()
    pending = await svc.get_pending_by_session(session_id)
    
    if pending is None:
        return "**No pending approval**..."
    
    await svc.resolve_request(
        pending.request_id,
        ApprovalDecision.APPROVED,
    )
    
    return (
        f"**Tool execution approved** ✅\n\n"
        f"- Tool: `{pending.tool_name}`\n"
        f"- Request: `{pending.request_id[:8]}…`"
    )
```

---

## 7. 并发控制

### 7.1 锁机制

```python
class ToolGuardMixin:
    def _init_tool_guard(self) -> None:
        self._tool_guard_lock = asyncio.Lock()  # 决策锁
        
    async def _acting(self, tool_call) -> dict | None:
        action: _GuardAction | None = None
        
        # 决策阶段：串行执行，避免状态竞争
        async with self._tool_guard_lock:
            try:
                action = await self._decide_guard_action(tool_call)
            except Exception as exc:
                logger.warning("Tool guard check error: %s", exc)

        # 执行阶段：在锁外执行，支持真正的并行
        if action is not None:
            return await self._execute_guard_action(action, tool_call)

        # 无风险的工具体并行执行
        result = await super()._acting(tool_call)
        return result
```

### 7.2 并行工具调用处理

```
┌─────────────────────────────────────────────────────────────┐
│              parallel_tool_calls=True 处理                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Tool Call 1 ──► _tool_guard_lock ──► 决策 ──► 执行 (锁外)    │
│  Tool Call 2 ──► 等待锁 ──► 决策 ──► 执行 (锁外)              │
│  Tool Call 3 ──► 等待锁 ──► 决策 ──► 执行 (锁外)              │
│                                                             │
│  设计理由：                                                  │
│  • 决策阶段需要读写共享状态 (_tool_guard_pending_info 等)     │
│  • 执行阶段在锁外，真正的工具调用可以并行                     │
│  • 避免多个 tool_call 同时创建 pending 审批                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. 预批准机制 (Pre-approval)

### 8.1 一次性批准 Token

```python
async def _consume_preapproval(
    self,
    tool_name: str,
    tool_input: dict[str, Any],
) -> bool:
    """Consume one matching approval token if present."""
    session_id = str(self._request_context.get("session_id") or "")
    if not session_id:
        return False

    svc = self._tool_guard_approval_service
    consumed = await svc.consume_approval(
        session_id,
        tool_name,
        tool_params=tool_input,
    )
    if consumed:
        logger.info(
            "Tool guard: pre-approved '%s' (session %s), skipping",
            tool_name,
            session_id[:8],
        )
    return bool(consumed)
```

### 8.2 使用场景

1. 用户批准一个工具后，可以选择"记住此选择"
2. 后续相同的工具调用自动放行
3. Token 消费后失效，下次仍需审批

---

## 9. 超时处理

### 9.1 超时配置

```python
# constant.py
TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = max(
    300.0,  # 最小 5 分钟
    _get_env("QWENPAW_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS", "600"),  # 默认 10 分钟
)
```

### 9.2 超时流程

```
┌─────────────────────────────────────────────────────────────┐
│                  超时处理流程                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 创建 pending 记录时启动计时器                             │
│  2. _gc_pending_locked() 定期检查超时                        │
│  3. 超时后：                                                 │
│     • pending.future.set_result(ApprovalDecision.TIMEOUT)   │
│     • pending.status = "timeout"                            │
│     • 移动到 completed 记录                                  │
│  4. Agent 检测到 TIMEOUT 后：                                │
│     • 向用户发送超时通知                                     │
│     • 不执行工具调用                                         │
│     • 继续下一个 tool_call 或结束回合                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 10. 记忆清理

### 10.1 清理被拒绝的消息

```python
async def _cleanup_tool_guard_denied_messages(
    self,
    *,
    include_denial_response: bool = False,
) -> None:
    """Finds messages marked with TOOL_GUARD_DENIED_MARK and removes them.
    
    This prevents the approval process artifacts from polluting
    the conversation history after approval is granted.
    """
    if not self.memory.content:
        return
    
    new_content = []
    for msg, marks in self.memory.content:
        if TOOL_GUARD_DENIED_MARK in marks and msg.role == "system":
            continue  # Skip denied messages
        new_content.append((msg, marks))
    
    self.memory.content = new_content
```

### 10.2 清理时机

- 预批准成功时：清理之前的拒绝消息
- 用户批准后：清理拒绝消息，保留批准记录
- 会话结束时：保留完整历史

---

## 11. 与 CoPaw 其他机制的集成

### 11.1 与 Skill 系统的关系

```
┌─────────────────────────────────────────────────────────────┐
│              Tool Guard 与 Skill 系统集成                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Skill Scanner (静态分析)                                    │
│  • 扫描 Skill 代码中的敏感操作                                │
│  • 标记高风险 Skill                                          │
│  • 生成 SKILL.md 中的 security 字段                           │
│                                                             │
│  Tool Guard (运行时拦截)                                     │
│  • 拦截具体工具调用参数                                       │
│  • 动态风险评估                                              │
│  • 用户审批                                                  │
│                                                             │
│  协同工作：                                                  │
│  • Skill Scanner 发现的敏感工具 → 加入 guarded_tools          │
│  • Tool Guard 在运行时拦截这些工具的调用                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 与 Channel 系统的关系

```python
# approvals/service.py
def set_channel_manager(self, channel_manager: Any) -> None:
    """Store a reference for push notifications."""
    self._channel_manager = channel_manager

# _app.py
from .approvals import get_approval_service
get_approval_service().set_channel_manager(channel_manager)
```

- Channel Manager 用于推送审批通知
- 支持 DingTalk、iMessage、Console 等渠道
- 不同渠道的审批命令格式可能不同

---

## 12. 配置选项

### 12.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QWENPAW_TOOL_GUARD_ENABLED` | `true` | 是否启用 Tool Guard |
| `QWENPAW_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS` | `600` | 审批超时 (秒) |

### 12.2 config.json

```json
{
  "security": {
    "tool_guard": {
      "enabled": true,
      "denied_tools": ["execute_shell_command"],
      "guarded_tools": ["write_file", "delete_file"],
      "rules_dir": "./security/rules"
    }
  }
}
```

---

## 13. 设计亮点

### 13.1 分层决策

```
┌─────────────────────────────────────────────────────────────┐
│                  分层决策架构                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: denied_tools (最快)                               │
│  • 硬编码的禁止列表                                          │
│  • 无需检测，直接拒绝                                         │
│                                                             │
│  Layer 2: Pre-approval (次快)                               │
│  • 一次性批准 Token                                           │
│  • 消费后失效                                                │
│                                                             │
│  Layer 3: Guardians (动态检测)                               │
│  • RuleBased: YAML 规则匹配                                  │
│  • FilePath: 路径风险分析                                     │
│  • 可扩展自定义 Guardian                                     │
│                                                             │
│  Layer 4: User Approval (最终防线)                           │
│  • 人类判断                                                  │
│  • 上下文感知                                                │
│  • 超时保护                                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 13.2 非阻塞设计

```
┌─────────────────────────────────────────────────────────────┐
│                  非阻塞设计原则                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  • 决策错误不阻断执行：guard check error 只记录日志           │
│  • 锁只保护决策阶段：执行在锁外，支持并行                     │
│  • 超时自动降级：超时后自动拒绝，不无限等待                   │
│  • 会话隔离：一个 session 的审批不影响其他 session             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 13.3 可审计性

```
┌─────────────────────────────────────────────────────────────┐
│                  审计追踪能力                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  记录内容：                                                  │
│  • request_id: 唯一标识每次审批请求                          │
│  • session_id: 关联到具体会话                                │
│  • tool_name: 被拦截的工具                                   │
│  • findings: 风险发现详情                                    │
│  • decision: APPROVED/DENIED/TIMEOUT                        │
│  • created_at/resolved_at: 时间戳                           │
│                                                             │
│  用途：                                                      │
│  • 安全审计                                                  │
│  • 行为分析                                                  │
│  • 规则优化                                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 14. 与 Claude Code 对比

| 特性 | CoPaw | Claude Code |
|------|-------|-------------|
| **拦截点** | `_acting()` 方法 | `StreamingToolExecutor` |
| **风险检测** | Guardians (可扩展) | 内置权限系统 |
| **审批方式** | `/daemon approve` 命令 | 权限模式 (Plan/Act) |
| **预批准** | 一次性 Token | 会话级权限 |
| **超时处理** | 自动拒绝 | 用户主动取消 |
| **并发控制** | asyncio.Lock | 队列管理 |
| **记忆清理** | 自动清理拒绝消息 | 保留完整历史 |

---

## 15. 总结

### 15.1 核心创新点

| 创新 | 说明 |
|------|------|
| **Mixin 架构** | 通过 Mixin 类拦截，不侵入主 Agent 逻辑 |
| **Guardian 系统** | 可扩展的风险检测插件架构 |
| **异步审批** | asyncio.Future 实现非阻塞等待 |
| **分层决策** | denied → pre-approved → guarded → approval |
| **会话隔离** | 每个 session 独立管理审批队列 |
| **自动清理** | 审批完成后清理中间状态 |

### 15.2 适用场景

✅ **推荐使用**:
- 需要执行敏感操作的 Agent (文件/网络/Shell)
- 多用户共享的 Agent 环境
- 需要审计追踪的生产环境
- 高安全要求的场景

⚠️ **谨慎考虑**:
- 完全自动化的后台任务 (无人类干预)
- 低延迟要求的实时系统
- 简单的只读 Agent

### 15.3 可借鉴的设计

```
┌─────────────────────────────────────────────────────────────┐
│              可借鉴到其他 Agent 系统的设计                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Mixin 拦截模式                                          │
│     • 不侵入主逻辑，易于集成和移除                           │
│     • 通过 MRO 组合多个功能                                   │
│                                                             │
│  2. Guardian 插件架构                                        │
│     • 每个 Guardian 独立检测特定风险                          │
│     • 易于扩展新的检测规则                                   │
│                                                             │
│  3. 异步 Future 审批                                         │
│     • 非阻塞等待，资源利用率高                               │
│     • 支持超时自动处理                                       │
│                                                             │
│  4. 分层决策机制                                            │
│     • 快速路径 (denied/pre-approved) 减少延迟                │
│     • 慢速路径 (approval) 保证安全                           │
│                                                             │
│  5. 记忆清理机制                                            │
│     • 审批完成后清理中间状态                                 │
│     • 保持对话历史整洁                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 参考文献

1. CoPaw GitHub: https://github.com/agentscope-ai/CoPaw
2. Tool Guard Mixin: `src/qwenpaw/agents/tool_guard_mixin.py`
3. Tool Guard Engine: `src/qwenpaw/security/tool_guard/engine.py`
4. Approval Service: `src/qwenpaw/app/approvals/service.py`
5. Rule Guardian: `src/qwenpaw/security/tool_guard/guardians/rule_guardian.py`
6. Models: `src/qwenpaw/security/tool_guard/models.py`
7. Daemon Commands: `src/qwenpaw/app/runner/daemon_commands.py`
