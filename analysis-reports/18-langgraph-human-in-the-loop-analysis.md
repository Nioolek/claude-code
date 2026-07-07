# LangGraph Human in the Loop 实现机制分析

**仓库**: https://github.com/langchain-ai/langgraph  
**解读日期**: 2026-04-13  
**核心文件**: `langgraph/types.py`, `langgraph_api/api/runs.py`, `langgraph_sdk/_sync/runs.py`

---

## 1. 系统概述

LangGraph 实现了一套基于 **Checkpoint + Interrupt + Resume** 机制的 Human in the Loop (HITL) 系统。与 CoPaw 的 Tool Guard 模式不同，LangGraph 采用 **图执行中断** 的方式，允许在任意节点暂停执行并等待人类输入。

### 1.1 核心设计目标

```
┌─────────────────────────────────────────────────────────────┐
│              LangGraph HITL 设计目标                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 灵活性：可在任意节点中断，不局限于工具调用               │
│  2. 持久化：基于 Checkpoint 保存状态，支持长时间等待         │
│  3. 可恢复：从中断点精确恢复，支持多次中断                   │
│  4. 多中断：单个节点可包含多个 interrupt 调用                 │
│  5. API 集成：通过 REST API 实现远程审批                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心架构

### 2.1 组件图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    LangGraph HITL 架构概览                           │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│   StateGraph         │
│   (用户定义图)        │
└──────────┬───────────┘
           │
           │ interrupt(value)
           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  GraphInterrupt      │────►│  CheckpointSaver     │
│  Exception           │     │  • 保存状态           │
│  • 携带 Interrupt    │     │  • 记录 pending_writes│
└──────────┬───────────┘     └──────────────────────┘
           │
           │ 抛出异常中断执行
           ▼
┌──────────────────────┐
│  Pregel Loop         │
│  • 检测中断           │
│  • 保存 checkpoint    │
│  • 返回 __interrupt__ │
└──────────┬───────────┘
           │
           │ 等待 Command(resume=...)
           ▼
┌──────────────────────┐
│  LangGraph API       │
│  • /runs/stream      │
│  • /runs/wait        │
│  • interrupt_before  │
│  • interrupt_after   │
└──────────┬───────────┘
           │
           │ SDK 调用
           ▼
┌──────────────────────┐
│   User (Client)      │
│   • 接收中断通知      │
│   • 发送 resume 值     │
└──────────────────────┘
```

---

### 2.2 核心类与文件

| 文件 | 类/函数 | 职责 |
|------|---------|------|
| `langgraph/types.py` | `Interrupt` | 中断数据类，包含 value 和 id |
| `langgraph/types.py` | `interrupt(value)` | 节点内调用，抛出 GraphInterrupt |
| `langgraph/types.py` | `Command` | 恢复执行的命令，包含 resume 值 |
| `langgraph/errors.py` | `GraphInterrupt` | 中断异常，携带 Interrupt 元组 |
| `langgraph/pregel/main.py` | `Pregel` | 图执行引擎，处理中断逻辑 |
| `langgraph/checkpoint/base/__init__.py` | `BaseCheckpointSaver` | Checkpoint 保存器 |
| `langgraph/serde/types.py` | `INTERRUPT`, `RESUME` | 特殊通道类型 |
| `langgraph_api/api/runs.py` | `stream()` | 流式执行 API |
| `langgraph_sdk/_sync/runs.py` | `SyncRunsClient` | SDK 客户端 |

---

## 3. 执行流程详解

### 3.1 完整 HITL 流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    LangGraph Human in the Loop 完整流程                  │
└─────────────────────────────────────────────────────────────────────────┘

用户启动图执行
        │
        ▼
┌─────────────────────────────────┐
│ Pregel.stream()                 │
│ 输入：{"messages": [...]}       │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ 执行节点 A                      │
│ 调用 interrupt("确认继续？")     │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ 抛出 GraphInterrupt 异常        │
│ 携带：Interrupt(value, id)      │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ Pregel 捕获异常                 │
│ 1. 保存 checkpoint              │
│ 2. 记录 pending_writes          │
│ 3. 标记状态为 interrupted       │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ 返回 __interrupt__ 事件          │
│ {"__interrupt__": (Interrupt,)} │
└───────────────┬─────────────────┘
                │
                │ 等待用户输入
                ▼
┌─────────────────────────────────┐
│ 用户发送 Command(resume="是")   │
│ 通过 API: /runs/stream          │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ Pregel 恢复执行                 │
│ 1. 加载 checkpoint              │
│ 2. 注入 resume 值到 scratchpad  │
│ 3. 重新执行节点 A               │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ interrupt() 返回 resume 值       │
│ 节点继续执行                     │
└───────────────┬─────────────────┘
```

---

### 3.2 interrupt() 函数实现

```python
def interrupt(value: Any) -> Any:
    """Interrupt the graph with a resumable exception from within a node.
    
    Args:
        value: The value to surface to the client when the graph is interrupted.
        
    Returns:
        On subsequent invocations within the same node, returns the resume value.
        
    Raises:
        GraphInterrupt: On the first invocation, halts execution.
    """
    from langgraph._internal._constants import (
        CONFIG_KEY_CHECKPOINT_NS,
        CONFIG_KEY_SCRATCHPAD,
        CONFIG_KEY_SEND,
        RESUME,
    )
    from langgraph.config import get_config
    from langgraph.errors import GraphInterrupt

    conf = get_config()["configurable"]
    
    # 1. 获取 scratchpad (跟踪中断索引)
    scratchpad = conf[CONFIG_KEY_SCRATCHPAD]
    idx = scratchpad.interrupt_counter()
    
    # 2. 检查是否有 resume 值 (恢复执行)
    if scratchpad.resume:
        if idx < len(scratchpad.resume):
            conf[CONFIG_KEY_SEND]([(RESUME, scratchpad.resume)])
            return scratchpad.resume[idx]
    
    # 3. 获取当前 resume 值 (首次恢复)
    v = scratchpad.get_null_resume(True)
    if v is not None:
        assert len(scratchpad.resume) == idx
        scratchpad.resume.append(v)
        conf[CONFIG_KEY_SEND]([(RESUME, scratchpad.resume)])
        return v
    
    # 4. 无 resume 值 → 抛出中断异常
    raise GraphInterrupt(
        (
            Interrupt.from_ns(
                value=value,
                ns=conf[CONFIG_KEY_CHECKPOINT_NS],
            ),
        )
    )
```

---

### 3.3 多次中断处理

```python
def node_with_multiple_interrupts(state: State):
    """单个节点可包含多个 interrupt 调用."""
    
    # 第一次中断
    answer1 = interrupt("问题 1: 你的年龄？")
    print(f"年龄：{answer1}")
    
    # 第二次中断
    answer2 = interrupt("问题 2: 你的城市？")
    print(f"城市：{answer2}")
    
    # 第三次中断
    answer3 = interrupt("问题 3: 确认提交？")
    print(f"确认：{answer3}")
    
    return {"responses": [answer1, answer2, answer3]}

# 恢复时需要提供所有中断的值
command = Command(resume=["25", "上海", "是"])
```

---

## 4. Interrupt 数据结构

### 4.1 Interrupt 类定义

```python
@dataclass
class Interrupt:
    """Represents an interrupt in the graph execution."""
    
    value: Any
    """The value associated with the interrupt (shown to user)."""
    
    id: str
    """The ID of the interrupt. Can be used to resume directly."""
    
    def __init__(
        self,
        value: Any,
        id: str = _DEFAULT_INTERRUPT_ID,
        **deprecated_kwargs,
    ):
        self.value = value
        # 如果提供了 ns (namespace), 使用 hash 生成 ID
        if ns := deprecated_kwargs.get("ns", MISSING):
            self.id = xxh3_128_hexdigest("|".join(ns).encode())
        else:
            self.id = id
    
    @classmethod
    def from_ns(cls, value: Any, ns: str) -> Interrupt:
        """Create interrupt from namespace."""
        return cls(value=value, id=xxh3_128_hexdigest(ns.encode()))
```

### 4.2 中断 ID 生成

```
命名空间 (ns) → xxh3_128 哈希 → 中断 ID

示例:
ns = ["graph_id:agent", "thread_id:xxx", "checkpoint_ns:node"]
id = xxh3_128_hexdigest("graph_id:agent|thread_id:xxx|checkpoint_ns:node")
   = "45fda8478b2ef754419799e10992af06"
```

---

## 5. Command 恢复机制

### 5.1 Command 类定义

```python
@dataclass
class Command:
    """Command to execute after an interrupt or node completion.
    
    Args:
        resume: Value to resume execution with.
            - Single value for next interrupt
            - List of values for multiple interrupts
            - Dict mapping interrupt IDs to values
        update: State updates to apply before resuming.
        goto: Nodes to navigate to directly (bypass normal flow).
    """
    resume: dict[str, Any] | Any | None = None
    update: dict[str, Any] | None = None
    goto: str | Sequence[str] | None = None
```

### 5.2 恢复模式

```python
# 模式 1: 单个值恢复 (按顺序匹配)
command = Command(resume="用户输入")

# 模式 2: 列表恢复 (匹配多个 interrupt)
command = Command(resume=["输入 1", "输入 2", "输入 3"])

# 模式 3: 字典恢复 (按 ID 匹配)
command = Command(resume={
    "45fda8478b2ef754419799e10992af06": "输入 1",
    "abc123...": "输入 2"
})

# 模式 4: 恢复 + 状态更新
command = Command(
    resume="用户输入",
    update={"human_feedback": "已确认"}
)

# 模式 5: 恢复 + 跳转节点
command = Command(
    resume="用户输入",
    goto="skip_node"  # 跳过某些节点
)
```

---

## 6. LangGraph API 集成

### 6.1 API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/runs/stream` | POST | 流式执行，实时接收中断事件 |
| `/runs/wait` | POST | 阻塞执行，返回最终状态 |
| `/runs/create` | POST | 后台执行，异步运行 |
| `/threads/{thread_id}/runs` | GET | 列出历史运行 |
| `/threads/{thread_id}/runs/{run_id}` | GET | 获取运行详情 |

### 6.2 流式执行 API

```python
# POST /runs/stream
{
    "assistant_id": "agent",
    "input": {"messages": [{"role": "user", "content": "hello"}]},
    "interrupt_before": ["sensitive_node"],  # 在节点前中断
    "interrupt_after": ["review_node"],      # 在节点后中断
    "stream_mode": ["values", "updates"],
    "durability": "sync"  # 同步保存 checkpoint
}

# 响应 (SSE 流)
event: values
data: {"messages": [...]}

event: __interrupt__
data: [{"value": "确认继续？", "id": "45fda847..."}]

event: end
data: null
```

### 6.3 SDK 调用示例

```python
from langgraph_sdk import get_client

# 创建客户端
client = get_client(url="http://localhost:2024")

# 启动执行 (会中断)
async for chunk in client.runs.stream(
    thread_id=None,
    assistant_id="agent",
    input={"messages": [{"role": "user", "content": "hello"}]},
    interrupt_before=["human_review"],
    stream_mode=["values", "updates"]
):
    if chunk.event == "__interrupt__":
        print(f"中断：{chunk.data}")
        # chunk.data = [{"value": "确认继续？", "id": "..."}]

# 恢复执行
async for chunk in client.runs.stream(
    thread_id=None,
    assistant_id="agent",
    command={"resume": "是的，继续"},  # 恢复值
    stream_mode=["values"]
):
    print(chunk)
```

---

## 7. 静态中断点 (interrupt_before/after)

### 7.1 配置方式

```python
# 方式 1: 编译时配置
graph = builder.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_review", "deploy_node"],
    interrupt_after=["generate_plan"]
)

# 方式 2: API 调用时配置
client.runs.stream(
    thread_id="xxx",
    assistant_id="agent",
    interrupt_before=["human_review"],
    interrupt_after=["generate_plan"]
)

# 方式 3: 特殊值 "*" (所有节点)
graph = builder.compile(
    checkpointer=checkpointer,
    interrupt_before="*"  # 在每个节点前中断
)
```

### 7.2 与 interrupt() 函数的区别

| 特性 | `interrupt()` 函数 | `interrupt_before/after` |
|------|-------------------|-------------------------|
| **定义位置** | 节点代码内部 | 图编译/API 调用时 |
| **中断条件** | 代码执行到调用点 | 节点执行前/后 |
| **自定义消息** | ✅ 可自定义 value | ❌ 仅通知中断 |
| **灵活性** | 高 (动态条件) | 低 (静态配置) |
| **适用场景** | 需要上下文的中断 | 固定审批点 |

---

## 8. Checkpoint 机制

### 8.1 Checkpoint 结构

```python
{
    "v": 3,  # version
    "id": "1ef4a9b8-d7da-679a-a45a-872054341df2",
    "ts": "2024-01-01T00:00:00.000000+00:00",
    "channel_values": {
        "__root__": {...},  # 状态
        "__interrupt__": [...],  # 中断信息
        "__resume__": [...]  # 恢复值
    },
    "metadata": {
        "thread_id": "xxx",
        "checkpoint_ns": "node:xxx",
        "step": 5
    }
}
```

### 8.2 Pending Writes

```python
# 当发生中断时，checkpointer 记录 pending_writes
pending_writes = [
    (task_id, channel, value),
    # 示例:
    ("task_123", "__interrupt__", Interrupt(value="确认？", id="...")),
    ("task_123", "__resume__", None),  # 等待恢复值
]

# 恢复时，pending_writes 被注入到 scratchpad
scratchpad.resume = ["用户输入"]
```

### 8.3 Checkpointer 接口

```python
class BaseCheckpointSaver:
    async def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
    ) -> RunnableConfig:
        """保存 checkpoint."""
        
    async def get_tuple(
        self,
        config: RunnableConfig,
    ) -> CheckpointTuple:
        """获取 checkpoint 元组."""
        
    async def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """保存 pending writes (包括中断和恢复值)."""
```

---

## 9. Scratchpad 机制

### 9.1 Scratchpad 作用

```
┌─────────────────────────────────────────────────────────────┐
│                  Scratchpad 机制                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Scratchpad 是任务级别的临时存储，用于：                     │
│  • 跟踪 interrupt 调用次数 (interrupt_counter)              │
│  • 存储 resume 值列表 (resume: list[Any])                   │
│  • 匹配 resume 值到对应的 interrupt                         │
│  • 跨调用持久化 (保存在 checkpoint 中)                      │
│                                                             │
│  生命周期：                                                  │
│  • 任务开始时创建                                            │
│  • 任务结束时持久化到 checkpoint                            │
│  • 恢复时从 checkpoint 加载                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 工作流程

```
第一次调用 interrupt("问题 1"):
┌─────────────────────────────┐
│ scratchpad = {              │
│   interrupt_counter: 1,     │
│   resume: []                │
│ }                           │
│                             │
│ → 抛出 GraphInterrupt       │
└─────────────────────────────┘

用户发送 Command(resume="答案 1"):
┌─────────────────────────────┐
│ scratchpad = {              │
│   interrupt_counter: 0,     │
│   resume: ["答案 1"]        │
│ }                           │
│                             │
│ → 重新执行节点              │
└─────────────────────────────┘

第二次调用 interrupt("问题 2"):
┌─────────────────────────────┐
│ scratchpad = {              │
│   interrupt_counter: 1,     │
│   resume: ["答案 1"]        │
│ }                           │
│                             │
│ → scratchpad.resume[0]      │
│ → 返回 "答案 1"             │
│                             │
│ scratchpad = {              │
│   interrupt_counter: 2,     │
│   resume: ["答案 1"]        │
│ }                           │
└─────────────────────────────┘
```

---

## 10. 超时与错误处理

### 10.1 超时配置

```python
# API 级别超时
client.runs.stream(
    ...,
    timeout=300  # 5 分钟超时
)

# Checkpoint TTL (时间到期限)
thread = client.threads.create(
    metadata={"user_id": "123"},
    ttl=3600  # 1 小时后自动过期
)
```

### 10.2 错误处理

```python
from langgraph.errors import GraphInterrupt, GraphRuntimeError

try:
    for chunk in graph.stream(input, config):
        if "__interrupt__" in chunk:
            # 处理中断
            handle_interrupt(chunk["__interrupt__"])
except GraphInterrupt as e:
    # 显式中断
    print(f"中断：{e.args[0].value}")
except GraphRuntimeError as e:
    # 运行时错误
    print(f"错误：{e}")
```

---

## 11. 多任务策略

### 11.1 MultitaskStrategy

```python
# 当新运行与现有运行冲突时的策略
multitask_strategy = "reject"     # 拒绝新运行 (默认)
multitask_strategy = "interrupt"  # 中断现有运行
multitask_strategy = "rollback"   # 回滚现有运行
multitask_strategy = "enqueue"    # 排队等待
```

### 11.2 使用场景

```python
# 场景 1: 拒绝并发 (安全优先)
client.runs.stream(
    ...,
    multitask_strategy="reject"
)

# 场景 2: 中断旧运行 (用户取消)
client.runs.stream(
    ...,
    multitask_strategy="interrupt"
)

# 场景 3: 回滚旧运行 (撤销)
client.runs.stream(
    ...,
    multitask_strategy="rollback"
)

# 场景 4: 队列 (批处理)
client.runs.stream(
    ...,
    multitask_strategy="enqueue"
)
```

---

## 12. 实际使用示例

### 12.1 基础示例

```python
import uuid
from typing import Optional
from typing_extensions import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.types import interrupt, Command


class State(TypedDict):
    foo: str
    human_value: Optional[str]


def node(state: State):
    answer = interrupt("你的年龄是多少？")
    return {"human_value": answer}


builder = StateGraph(State)
builder.add_node("node", node)
builder.add_edge(START, "node")

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": uuid.uuid4()}}

# 第一次执行 - 会中断
for chunk in graph.stream({"foo": "abc"}, config):
    print(chunk)
# 输出：{'__interrupt__': (Interrupt(value='你的年龄是多少？', id='...'),)}

# 恢复执行
for chunk in graph.stream(Command(resume="25"), config):
    print(chunk)
# 输出：{'node': {'human_value': '25'}}
```

### 12.2 多中断示例

```python
def human_review_node(state: State):
    # 中断 1: 确认内容
    confirmed = interrupt({
        "type": "confirmation",
        "content": state["draft_content"]
    })
    
    if not confirmed:
        return {"status": "rejected"}
    
    # 中断 2: 选择发布渠道
    channel = interrupt({
        "type": "selection",
        "options": ["twitter", "linkedin", "email"]
    })
    
    return {"status": "approved", "channel": channel}


# 恢复时需要提供两个值
command = Command(resume=[True, "twitter"])
```

### 12.3 API 集成示例

```python
from langgraph_sdk import get_async_client

client = get_async_client(url="http://localhost:2024")

async def run_with_approval():
    # 启动执行
    async for chunk in client.runs.stream(
        thread_id=None,
        assistant_id="content_generator",
        input={"topic": "AI trends"},
        interrupt_before=["human_review"],
        stream_mode=["values"]
    ):
        if chunk.event == "__interrupt__":
            # 显示审批请求
            print(f"需要审批：{chunk.data}")
            
            # 获取用户输入
            user_input = await get_user_approval(chunk.data)
            
            # 恢复执行
            async for resume_chunk in client.runs.stream(
                thread_id=None,
                assistant_id="content_generator",
                command={"resume": user_input},
                stream_mode=["values"]
            ):
                print(resume_chunk)
```

---

## 13. 与 CoPaw 对比

| 特性 | LangGraph | CoPaw |
|------|-----------|-------|
| **中断方式** | `interrupt()` 函数 | Tool Guard 拦截 |
| **中断粒度** | 任意节点 | 工具调用级别 |
| **恢复机制** | `Command(resume=...)` | `/daemon approve` |
| **状态保存** | Checkpoint 完整状态 | 审批记录 + 记忆 |
| **多中断** | ✅ 单节点多 interrupt | ❌ 单工具单审批 |
| **API 支持** | ✅ 原生 REST API | ⚠️ 需要自定义 |
| **静态中断点** | ✅ `interrupt_before/after` | ❌ 无 |
| **超时处理** | 手动实现 | ✅ 自动超时 |
| **预批准** | ❌ 无 | ✅ Token 机制 |

---

## 14. 设计亮点

### 14.1 基于异常的中断

```
┌─────────────────────────────────────────────────────────────┐
│              基于异常的中断机制                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  优点：                                                      │
│  • 自然集成到 Python 执行流                                  │
│  • 不需要特殊语法或装饰器                                    │
│  • 可以在任何代码位置调用                                    │
│  • 支持条件中断 (if 条件：interrupt())                       │
│                                                             │
│  实现：                                                      │
│  • GraphInterrupt 异常携带 Interrupt 数据                    │
│  • Pregel 循环捕获异常并保存状态                             │
│  • 恢复时重新执行节点，interrupt() 返回 resume 值             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 14.2 Scratchpad 匹配机制

```
┌─────────────────────────────────────────────────────────────┐
│              Scratchpad 顺序匹配机制                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  匹配规则：                                                  │
│  • interrupt 按调用顺序编号 (0, 1, 2, ...)                  │
│  • resume 值列表按顺序匹配                                   │
│  • 支持字典恢复 (按 ID 精确匹配)                             │
│                                                             │
│  优势：                                                      │
│  • 简单直观，易于理解                                        │
│  • 支持动态数量的中断                                        │
│  • 不依赖硬编码的变量名                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 14.3 Checkpoint 驱动恢复

```
┌─────────────────────────────────────────────────────────────┐
│              Checkpoint 驱动的恢复机制                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  保存内容：                                                  │
│  • 完整状态 (channel_values)                                │
│  • 中断信息 (__interrupt__)                                 │
│  • 恢复值 (__resume__)                                      │
│  • pending_writes (待处理的写入)                            │
│                                                             │
│  恢复流程：                                                  │
│  1. 加载 checkpoint                                          │
│  2. 注入 resume 值到 scratchpad                              │
│  3. 从断点重新执行                                           │
│  4. interrupt() 检测到 resume 值并返回                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 15. 总结

### 15.1 核心创新点

| 创新 | 说明 |
|------|------|
| **interrupt() 函数** | 基于异常的优雅中断机制 |
| **Command 恢复** | 统一的恢复原语 (resume/update/goto) |
| **Checkpoint 持久化** | 支持长时间等待和服务器重启 |
| **多中断支持** | 单节点可包含多个 interrupt 调用 |
| **静态中断点** | interrupt_before/after 配置 |
| **API 原生支持** | REST API 和 SDK 完整集成 |

### 15.2 适用场景

✅ **推荐使用**:
- 需要灵活中断点的场景
- 长时间等待人类输入
- 多步骤审批流程
- 需要状态持久化
- 远程 API 调用场景

⚠️ **谨慎考虑**:
- 高频低延迟场景 (checkpoint 开销)
- 无状态图 (需要 checkpointer)
- 简单工具审批 (可能过度设计)

### 15.3 可借鉴的设计

```
┌─────────────────────────────────────────────────────────────┐
│              可借鉴到其他 Agent 系统的设计                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 基于异常中断                                             │
│     • 自然集成到执行流                                       │
│     • 不需要特殊语法                                         │
│                                                             │
│  2. 顺序匹配机制                                             │
│     • interrupt 按顺序编号                                    │
│     • resume 值列表按序匹配                                   │
│                                                             │
│  3. Command 统一原语                                         │
│     • resume: 恢复值                                         │
│     • update: 状态更新                                       │
│     • goto: 节点跳转                                         │
│                                                             │
│  4. 静态中断点配置                                           │
│     • interrupt_before: 节点前中断                           │
│     • interrupt_after: 节点后中断                            │
│                                                             │
│  5. API 原生集成                                             │
│     • REST API 完整支持                                      │
│     • SDK 封装易用                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 16. ContextVar 机制分析

### 16.1 ContextVar 定义位置

LangGraph 借用 LangChain Core 的 ContextVar 机制：

**文件**: `langchain_core/runnables/config.py:144-145`

```python
var_child_runnable_config: ContextVar[RunnableConfig | None] = ContextVar(
    "child_runnable_config", default=None
)
```

LangGraph **自身不定义独立的 ContextVar**，而是复用 LangChain Core 的机制。

### 16.2 Context 设置机制

**文件**: `langgraph/_internal/_runnable.py:104-112`

```python
@contextmanager
def set_config_context(config: RunnableConfig, run: Any = None):
    ctx = copy_context()  # ← 复制当前 context
    config_token = ctx.run(_set_config_context, config, run)  # ← 在复制的 context 中设置
    try:
        yield ctx
    finally:
        ctx.run(_unset_config_context, config_token, run)  # ← 退出时重置
```

### 16.3 节点执行时的 Context 流程

**文件**: `langgraph/_internal/_runnable.py:395-397`

```python
# RunnableCallable.invoke() 中
if self.trace:
    with set_config_context(child_config, run) as context:
        ret = context.run(self.func, *args, **kwargs)  # ← 在独立 context 中执行节点函数
else:
    ret = self.func(*args, **kwargs)  # ← trace=False 时，不设置 context！
```

### 16.4 多线程/异步执行

**文件**: `langgraph/pregel/_executor.py:61-67`

```python
# BackgroundExecutor.submit()
def submit(self, fn, ...):
    ctx = copy_context()  # ← 每个 task 复制 context
    task = self.executor.submit(ctx.run, fn, *args, **kwargs)  # ← task 在复制的 context 中运行
```

### 16.5 ContextVar 流转图

```
主线程 Context（初始状态）
│
│ var_child_runnable_config = None（或之前设置的值）
│
├──────────────────────────────────────────────┐
│                                              │
│  Pregel.stream() 调用                         │
│  ├── 确保顶层 config                         │
│  └─────────────────────────────────────────┐│
│                                            ││
│  for task in tasks:                        ││
│      │                                     ││
│      ├── ctx = copy_context() ← 复制主 context│
│      │   ctx.var_child_runnable_config = 主 context 的值│
│      │                                     ││
│      ├── ctx.run(_set_config_context, config)│
│      │   → var_child_runnable_config.set(config)│
│      │   → config 包含 scratchpad 等       ││
│      │                                     ││
│      ├── executor.submit(ctx.run, fn, ...) ││
│      │   → 新线程/异步 task                 ││
│      │                                     ││
│      └── task 执行：                        ││
│          │                                 ││
│          ├── fn(...)                       ││
│          │   ├── 内部调用 get_config()     ││
│          │   │   → var_child_runnable_config.get()│
│          │   │   → 返回 task 的 config      ││
│          │   │                             ││
│          │   ├── interrupt()               ││
│          │   │   → get_config()["configurable"][CONFIG_KEY_SCRATCHPAD]│
│          │   │   → 返回 scratchpad          ││
│          │   │                             ││
│          │   └── task 完成                  ││
│          │                                 ││
│          └── context.run(...) 结束         ││
│              → _unset_config_context()     ││
│              → var_child_runnable_config.reset()│
│              → ctx 被销毁                   ││
│                                            ││
│  下一个 task 执行：                         ││
│      │                                     ││
│      ├── ctx = copy_context() ← 再次复制主 context│
│      │   ctx.var_child_runnable_config = 主 context 的值（可能是 None）│
│      │                                     ││
│      ├── ctx.run(_set_config_context, NEW_config)│
│      │   → 设置新的 config（包含新的 scratchpad）│
│      │                                     ││
│      └── 执行节点...                        ││
│                                            ││
└────────────────────────────────────────────┘
```

### 16.6 关键结论

| 问题 | 答案 |
|------|------|
| **节点流转时 ContextVar 是否被重置？** | **是的**，每个节点在独立 context 中执行，完成后销毁 |
| **ContextVar 重置会影响 scratchpad 吗？** | **不会**，scratchpad 通过 checkpoint 传递，不是 ContextVar |
| **不同节点间 ContextVar 值共享吗？** | **不共享**，每个节点从主 context 复制，独立设置 |
| **trace=False 时 get_config() 会失败吗？** | **可能**，因为没有设置 context |
| **多线程执行时 ContextVar 安全吗？** | **安全**，每个 task 有独立的 context 副本 |

### 16.7 scratchpad 传递机制

```
┌─────────────────────────────────────────────────────────────┐
│              scratchpad 传递机制                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  scratchpad 存储位置：                                       │
│  • config["configurable"][CONFIG_KEY_SCRATCHPAD]            │
│  • config 是 RunnableConfig（字典），不是 ContextVar        │
│                                                             │
│  传递方式：                                                  │
│  • 第一次执行：创建 scratchpad，存入 config                 │
│  • 中断时：config 保存到 checkpoint                         │
│  • 恢复时：从 checkpoint 加载 config                        │
│  • scratchpad 通过 checkpoint 传递，不是 ContextVar         │
│                                                             │
│  ContextVar 的作用：                                         │
│  • 只是让 get_config() 能够获取 config                      │
│  • scratchpad 是 config 的内容，不是 ContextVar 的值        │
│                                                             │
│  所以：中断恢复时 ContextVar 被重置没关系，                   │
│       scratchpad 通过 checkpoint 传递！                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 17. 自定义节点基类实现（自动注入上下文）

### 17.1 问题背景

用户希望在 State 中存储 session_id 等上下文，并在 Logger Formatter 中自动打印。由于 ContextVar 在节点间会重置，需要一种机制在节点执行时自动注入上下文。

### 17.2 解决方案：继承 RunnableCallable

```
┌─────────────────────────────────────────────────────────────┐
│              自定义节点基类设计                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  继承 RunnableCallable                                      │
│  ├── 重写 invoke() / ainvoke()                              │
│  ├── 在执行 self.func 前，从 input/state 获取上下文         │
│  ├── 设置到 ContextVar                                      │
│  ├── 执行节点函数                                           │
│  └── 执行完成后清理 ContextVar                              │
│                                                             │
│  优势：                                                      │
│  • 所有继承的节点自动获得上下文注入                          │
│  • 无需手动设置 ContextVar                                  │
│  • 无需装饰器包装                                           │
│  • 一处修改，全局生效                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 17.3 完整实现代码

```python
import asyncio
import inspect
import logging
from contextvars import ContextVar, Token, copy_context
from typing import Any, Callable, Awaitable, Sequence, cast

from langchain_core.runnables import RunnableConfig
from langchain_core.callbacks import get_callback_manager_for_config
from langchain_core.tracers.langchain import LangChainTracer

from langgraph._internal._runnable import RunnableCallable
from langgraph._internal._config import patch_config, ensure_config
from langgraph._internal._constants import CONF, CONFIG_KEY_RUNTIME
from langgraph._internal._typing import MISSING

# ============================================================
# ContextVar 定义
# ============================================================

session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


class ContextVarsManager:
    """管理多个 ContextVar 的设置和清理"""
    
    def __init__(self):
        self.tokens: dict[str, Token] = {}
    
    def set(self, name: str, value: Any):
        """设置 ContextVar"""
        var = globals().get(f"{name}_var")
        if var and isinstance(var, ContextVar):
            self.tokens[name] = var.set(value)
    
    def reset_all(self):
        """重置所有 ContextVar"""
        for name, token in self.tokens.items():
            var = globals().get(f"{name}_var")
            if var and isinstance(var, ContextVar):
                var.reset(token)


# ============================================================
# 自定义节点基类
# ============================================================

class ContextAwareRunnableCallable(RunnableCallable):
    """自动注入上下文的节点基类
    
    使用方式：
    1. 继承此类创建节点
    2. 节点函数的 input 必须是包含上下文字段的 dict（如 State）
    3. 会自动从 input 中提取 session_id、user_id 等并设置到 ContextVar
    """
    
    # 从 input/state 中提取的字段名 → ContextVar 名
    CONTEXT_FIELDS: dict[str, str] = {
        "session_id": "session_id",
        "user_id": "user_id",
        "trace_id": "trace_id",
    }
    
    def __init__(
        self,
        func: Callable[..., Any] | None = None,
        afunc: Callable[..., Awaitable[Any]] | None = None,
        context_fields: dict[str, str] | None = None,
        **kwargs,
    ):
        super().__init__(func, afunc, **kwargs)
        if context_fields:
            self.CONTEXT_FIELDS = context_fields
    
    def _extract_context_from_input(self, input: Any) -> dict[str, Any]:
        """从 input/state 中提取上下文值"""
        context_values = {}
        if isinstance(input, dict):
            for state_field, var_name in self.CONTEXT_FIELDS.items():
                if state_field in input:
                    context_values[var_name] = input[state_field]
        return context_values
    
    def _set_context_vars(self, context_values: dict[str, Any]) -> ContextVarsManager:
        """设置 ContextVar"""
        manager = ContextVarsManager()
        for var_name, value in context_values.items():
            if value is not None:
                manager.set(var_name, value)
        return manager
    
    def _get_kw_value(self, kw, runtime_key, default, config, runtime):
        """获取 kw 参数值"""
        kw_value = MISSING
        if kw == "config":
            kw_value = config
        elif runtime:
            if kw == "runtime":
                kw_value = runtime
            else:
                try:
                    kw_value = getattr(runtime, runtime_key)
                except AttributeError:
                    pass
        if kw_value is MISSING:
            if default is inspect.Parameter.empty:
                raise ValueError(
                    f"Missing required config key '{runtime_key}' for '{self.name}'."
                )
            kw_value = default
        return kw_value
    
    def invoke(
        self, 
        input: Any, 
        config: RunnableConfig | None = None, 
        **kwargs
    ) -> Any:
        if config is None:
            config = ensure_config()
        
        # 处理参数
        if self.explode_args:
            args, _kwargs = input
            kwargs = {**self.kwargs, **_kwargs, **kwargs}
        else:
            args = (input,)
            kwargs = {**self.kwargs, **kwargs}
        
        # 处理 runtime 注入
        runtime = config.get(CONF, {}).get(CONFIG_KEY_RUNTIME)
        for kw, (runtime_key, default) in self.func_accepts.items():
            if kw in kwargs:
                continue
            kw_value = self._get_kw_value(kw, runtime_key, default, config, runtime)
            if kw_value is not inspect.Parameter.empty:
                kwargs[kw] = kw_value
        
        # ═══════════════════════════════════════════════════════════
        # 关键：提取上下文并设置 ContextVar
        # ═══════════════════════════════════════════════════════════
        context_values = self._extract_context_from_input(input)
        context_manager = self._set_context_vars(context_values)
        
        try:
            if self.trace:
                callback_manager = get_callback_manager_for_config(config, self.tags)
                run_manager = callback_manager.on_chain_start(
                    None,
                    input,
                    name=config.get("run_name") or self.name,
                    run_id=config.pop("run_id", None),
                )
                
                try:
                    child_config = patch_config(config, callbacks=run_manager.get_child())
                    
                    run = None
                    for h in run_manager.handlers:
                        if isinstance(h, LangChainTracer):
                            run = h.run_map.get(str(run_manager.run_id))
                            break
                    
                    # 复制 context 并执行
                    ctx = copy_context()
                    for var_name, value in context_values.items():
                        var = globals().get(f"{var_name}_var")
                        if var:
                            ctx.run(var.set, value)
                    
                    ret = ctx.run(self.func, *args, **kwargs)
                    
                except BaseException as e:
                    run_manager.on_chain_error(e)
                    raise
                else:
                    run_manager.on_chain_end(ret)
            else:
                ret = self.func(*args, **kwargs)
            
            if self.recurse and isinstance(ret, Runnable):
                return ret.invoke(input, config)
            
            return ret
            
        finally:
            context_manager.reset_all()
    
    async def ainvoke(
        self, 
        input: Any, 
        config: RunnableConfig | None = None, 
        **kwargs
    ) -> Any:
        """异步版本"""
        if not self.afunc:
            return self.invoke(input, config)
        
        if config is None:
            config = ensure_config()
        
        if self.explode_args:
            args, _kwargs = input
            kwargs = {**self.kwargs, **_kwargs, **kwargs}
        else:
            args = (input,)
            kwargs = {**self.kwargs, **kwargs}
        
        runtime = config.get(CONF, {}).get(CONFIG_KEY_RUNTIME)
        for kw, (runtime_key, default) in self.func_accepts.items():
            if kw in kwargs:
                continue
            kw_value = self._get_kw_value(kw, runtime_key, default, config, runtime)
            if kw_value is not inspect.Parameter.empty:
                kwargs[kw] = kw_value
        
        context_values = self._extract_context_from_input(input)
        context_manager = self._set_context_vars(context_values)
        
        try:
            if self.trace:
                from langchain_core.callbacks import get_async_callback_manager_for_config
                from langgraph._internal._runnable import ASYNCIO_ACCEPTS_CONTEXT
                
                callback_manager = get_async_callback_manager_for_config(config, self.tags)
                run_manager = await callback_manager.on_chain_start(
                    None,
                    input,
                    name=config.get("run_name") or self.name,
                    run_id=config.pop("run_id", None),
                )
                
                try:
                    child_config = patch_config(config, callbacks=run_manager.get_child())
                    coro = cast(asyncio.Coroutine, self.afunc(*args, **kwargs))
                    
                    run = None
                    for h in run_manager.handlers:
                        if isinstance(h, LangChainTracer):
                            run = h.run_map.get(str(run_manager.run_id))
                            break
                    
                    if ASYNCIO_ACCEPTS_CONTEXT:
                        ctx = copy_context()
                        for var_name, value in context_values.items():
                            var = globals().get(f"{var_name}_var")
                            if var:
                                ctx.run(var.set, value)
                        ret = await asyncio.create_task(coro, context=ctx)
                    else:
                        ret = await coro
                        
                except BaseException as e:
                    await run_manager.on_chain_error(e)
                    raise
                else:
                    await run_manager.on_chain_end(ret)
            else:
                ret = await self.afunc(*args, **kwargs)
            
            if self.recurse and isinstance(ret, Runnable):
                return await ret.ainvoke(input, config)
            
            return ret
            
        finally:
            context_manager.reset_all()


# ============================================================
# Logger Formatter
# ============================================================

class ContextFormatter(logging.Formatter):
    """从 ContextVar 获取上下文的 Formatter"""
    
    def format(self, record):
        session_id = session_id_var.get() or "unknown"
        user_id = user_id_var.get() or "unknown"
        trace_id = trace_id_var.get() or "unknown"
        
        record.session_id = session_id
        record.user_id = user_id
        record.trace_id = trace_id
        
        return super().format(record)


# 设置日志格式
formatter = ContextFormatter(
    "[%(session_id)s][%(user_id)s] %(asctime)s %(levelname)s %(name)s: %(message)s"
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)
```

### 17.4 使用示例

```python
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START
from langgraph.checkpoint.memory import InMemorySaver


# State 定义
class State(TypedDict):
    session_id: str
    user_id: str
    trace_id: str
    messages: list
    result: dict


# 节点函数
def analyze_node_func(state: State, config):
    logging.info("分析节点开始执行")
    # 输出：[abc123][user001] 2024-01-01 10:00:00 INFO analyze: 分析节点开始执行
    return {"result": {"analysis": "done"}}


def interrupt_node_func(state: State, config):
    from langgraph.types import interrupt
    
    logging.info("需要用户确认")
    # 输出：[abc123][user001] 2024-01-01 10:00:02 INFO interrupt: 需要用户确认
    
    answer = interrupt("是否继续？")
    
    logging.info(f"用户回复：{answer}")
    # 恢复后：[abc123][user001] 2024-01-01 10:00:05 INFO interrupt: 用户回复：是
    return {"messages": [f"user: {answer}"]}


# 使用自定义基类包装节点
analyze_node = ContextAwareRunnableCallable(analyze_node_func, name="analyze")
interrupt_node = ContextAwareRunnableCallable(interrupt_node_func, name="interrupt")


# 构建图
builder = StateGraph(State)
builder.add_node("analyze", analyze_node)
builder.add_node("interrupt", interrupt_node)
builder.add_edge(START, "analyze")
builder.add_edge("analyze", "interrupt")

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)


# 执行
import uuid
config = {"configurable": {"thread_id": uuid.uuid4()}}

# 第一次执行（会中断）
for chunk in graph.stream({
    "session_id": "abc123",
    "user_id": "user001",
    "trace_id": "trace001",
    "messages": [],
    "result": {}
}, config):
    print(chunk)

# 恢复执行
from langgraph.types import Command
for chunk in graph.stream(Command(resume="是"), config):
    print(chunk)
```

### 17.5 自定义 StateGraph（自动包装）

```python
class ContextAwareStateGraph(StateGraph):
    """自动使用 ContextAwareRunnableCallable 的 StateGraph"""
    
    def add_node(self, key: str, node: Callable, context_fields=None):
        if not isinstance(node, RunnableCallable):
            node = ContextAwareRunnableCallable(
                func=node,
                name=key,
                context_fields=context_fields,
            )
        return super().add_node(key, node)


# 使用
builder = ContextAwareStateGraph(State)
builder.add_node("analyze", analyze_node_func)  # 自动包装
builder.add_node("interrupt", interrupt_node_func)  # 自动包装
```

### 17.6 执行流程图

```
invoke(input, config)
        │
        │ input = {"session_id": "abc123", "user_id": "user001", ...}
        │
        ▼
┌─────────────────────────────────────┐
│ 1. _extract_context_from_input()    │
│    → {"session_id": "abc123",       │
│       "user_id": "user001"}         │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ 2. _set_context_vars()              │
│    → session_id_var.set("abc123")   │
│    → user_id_var.set("user001")     │
│    → 保存 tokens 用于重置           │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ 3. 执行节点函数                      │
│    if trace:                        │
│        ctx = copy_context()         │
│        ctx.run(var.set, value)      │
│        ctx.run(self.func, ...)      │
│    else:                            │
│        self.func(...)               │
│                                     │
│    节点内部：                        │
│    logging.info("xxx")              │
│    → Formatter 从 ContextVar 获取   │
│    → 输出：[abc123][user001] xxx    │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ 4. finally:                         │
│    context_manager.reset_all()      │
│    → session_id_var.reset(token)    │
│    → user_id_var.reset(token)       │
└─────────────────────────────────────┘

恢复执行时：
invoke(input, config) 再次执行
→ _extract_context_from_input()
→ input 包含 session_id（从 checkpoint 加载的 State）
→ 重新设置 ContextVar ✓
→ 执行节点函数，logging.info() 带上下文 ✓
```

### 17.7 方案对比

| 方案 | 可行性 | 优点 | 缺点 |
|------|--------|------|------|
| **装饰器** | ✅ | 简单 | 每个节点需要包装 |
| **RunnableCallable 基类** | ✅✅ | 一处修改，自动生效；恢复时自动重设 | 需要重写 invoke/ainvoke |
| **自定义 StateGraph** | ✅✅✅ | 最优雅，add_node 自动包装 | 需要继承 StateGraph |

---

## 参考文献

1. LangGraph GitHub: https://github.com/langchain-ai/langgraph
2. LangGraph Docs: https://langchain-ai.github.io/langgraph/
3. Human in the Loop: https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/
4. Interrupt API: `langgraph/types.py:interrupt()`
5. Command API: `langgraph/types.py:Command`
6. LangGraph SDK: `langgraph_sdk/_sync/runs.py`
7. LangGraph API: `langgraph_api/api/runs.py`
8. RunnableCallable: `langgraph/_internal/_runnable.py`
9. ContextVar 定义: `langchain_core/runnables/config.py:144`
10. set_config_context: `langgraph/_internal/_runnable.py:104`
