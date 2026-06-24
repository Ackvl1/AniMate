# Phase 3 开发手册 · 通用 Agent 框架基础

> 目标：将当前紧耦合的 Agent 重构为通用框架——引入结构化输出、Skill 生命周期、I/O 适配器接口和事件系统。**本阶段只做架构重构，不引入新功能（MCP/Tool Calling 见 Phase 4）。**
>
> 这份教程**只给思路、接口和自检清单，不给完整实现**。每一步留给你自己写。
>
> **前置状态**：Phase 1（RAG+角色+CLI）和 Phase 2（记忆+情绪+双路检索）已完成并跑通。

---

## 你需要先有的认知

- **紧耦合 vs 松耦合**：当前 `Agent.__init__` 用 `isinstance(skill, MemorySkill)` 探测具体类型。每加一个 Skill 就要改 Agent 代码。松耦合的做法是让 Skill 主动向 Agent 注册自己的能力，Agent 不关心具体类型。
- **结构化输出**：当前 `Agent.chat()` 返回纯 `str`。后续语音需要音频字节、Live2D 需要动作标签。解决：返回一个 dataclass，各模块按需取用。
- **适配器模式**：定义统一的 I/O 接口，CLI 文字模式和后续语音/Unity 模式各自实现同一套接口。
- **事件总线**：发布/订阅机制，让模块间解耦——情绪变化时发事件，Live2D 订阅响应，两者不需要互相 import。

如果上面任何一条你觉得模糊，先去查清楚再继续。

---

## 整体架构图

```
┌──────────────────────────────────────────────────────────────┐
│                       cli.py                                 │
│  main(): 解析参数 → 创建适配器 → 创建 Agent → 对话主循环       │
│                                                              │
│  python cli.py              # 文字模式                        │
│  python cli.py --unity      # Unity UI 模式（Phase 5）        │
│  python cli.py --voice      # 语音模式（Phase 6）              │
└──────────┬───────────────────────────────┬───────────────────┘
           │ InputAdapter                  │ OutputAdapter
           │ ┌────────────┐               │ ┌────────────┐
           │ │ConsoleInput│               │ │ConsoleOutput│
           │ │(P6: ASR)   │               │ │(P6: TTS)   │
           │ └────────────┘               │ └────────────┘
           ▼                               ▲
┌──────────────────────────────────────────────────────────────┐
│                         Agent                                │
│                                                              │
│  ┌──────────────────────┐  ┌──────────────────────┐         │
│  │   Skill Pipeline     │  │      EventBus        │         │
│  │   (预处理，有序执行)   │  │                      │         │
│  │                      │  │  chat.before         │         │
│  │  PersonaSkill        │  │  chat.after          │         │
│  │  RetrievalSkill      │  │  emotion.changed     │         │
│  │  MemorySkill         │  │  agent.reset         │         │
│  │  EmotionSkill        │  │                      │         │
│  └──────────┬───────────┘  └──────────┬───────────┘         │
│             │                         │                      │
│             ▼                         │                      │
│  ┌──────────────────────┐             │                      │
│  │    SkillContext       │             │                      │
│  │    (数据传递)          │             │                      │
│  │    - user_input       │             │                      │
│  │    - chunks           │             │                      │
│  │    - prompt_parts     │             │                      │
│  │    - history          │             │                      │
│  │    - emotion          │             │                      │
│  │    - response         │             │                      │
│  └──────────────────────┘             │                      │
│                                        │                      │
└────────────────────────────────────────┼──────────────────────┘
                                         │
                                         ▼
                                  ┌────────────┐
                                  │  LLM API   │
                                  │  (OpenAI)  │
                                  └────────────┘
```

**数据流**：

```
用户输入 → InputAdapter.receive() → str
  → Agent.chat(user_input)
    → emit(chat.before)
    → Skill Pipeline 预处理（依次 run Persona → Retrieval → Memory → Emotion）
    → 组装 messages（system_prompt + history + user_input）
    → LLM 调用
    → 构建 AgentResponse（text + emotion）
    → 记录对话历史
    → emit(chat.after)
    → 返回 AgentResponse
  → OutputAdapter.send(response) → 呈现给用户
```

---

## 总览：你要新建 / 修改的组件

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| 1 | `animate/response.py` | **新建**：结构化输出 dataclass |
| 2 | `animate/skills/base.py` | **修改**：Skill ABC 加生命周期钩子，SkillContext 加 response 字段 |
| 3 | `animate/events.py` | **新建**：最小事件总线 |
| 4 | `animate/io/__init__.py` | **新建**：io 包入口 |
| 5 | `animate/io/base.py` | **新建**：I/O 适配器抽象接口 |
| 6 | `animate/io/console.py` | **新建**：控制台输入/输出适配器 |
| 7 | `animate/skills/memory_skill.py` | **修改**：加 `on_register` 自注册 |
| 8 | `animate/skills/emotion_skill.py` | **修改**：加 `on_register` + `on_reset`，向 ctx.response 写情绪 |
| 9 | `animate/agent.py` | **修改**：去 isinstance、返回 AgentResponse、事件发送、reset 遍历 Skill |
| 10 | `cli.py` | **修改**：换用 I/O 适配器 |
| 11 | 跑通 & 回归验证 | 确认 CLI 行为不变，新模块可导入 |

---

## Step 1 · `animate/response.py` — 结构化输出

**接口**：

```python
from dataclasses import dataclass, field
from animate.emotion import Emotion

@dataclass
class AgentResponse:
    text: str = ""                            # 核心文本回复
    emotion: Emotion = Emotion.CALM            # 当前情绪
    motion_tags: list[str] = field(default_factory=list)  # Live2D 动作（Phase 7）
    audio_data: bytes | None = None           # TTS 音频（Phase 6）
    metadata: dict = field(default_factory=dict)  # 扩展用
```

**思路**：纯数据容器，所有字段有默认值。

**自检**：`from animate.response import AgentResponse` 可导入，`AgentResponse(text="你好")` 不报错。

---

## Step 2 · `animate/skills/base.py` — Skill 生命周期扩展

### 2a. Skill ABC 加可选钩子

```python
class Skill(ABC):
    name: str

    @abstractmethod
    def run(self, ctx: SkillContext) -> SkillContext: ...

    def on_register(self, agent) -> None:
        """注册到 Agent 时回调。Skill 可在此向 Agent 暴露自己的能力。"""
        pass

    def on_reset(self) -> None:
        """Agent.reset() 时回调。"""
        pass
```

### 2b. SkillContext 加 response 字段

```python
@dataclass
class SkillContext:
    user_input: str
    retrieved_chunks: list[str] = field(default_factory=list)
    system_prompt_parts: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    emotion: Emotion = Emotion.CALM
    response: "AgentResponse | None" = None   # ← 新增，forward reference 避免循环 import
```

**自检**：原有 4 个 Skill 不改代码仍能正常运行。

---

## Step 3 · `animate/events.py` — 事件总线

**接口**：

```python
from collections import defaultdict
from typing import Callable, Any

EVENT_CHAT_BEFORE = "chat.before"
EVENT_CHAT_AFTER = "chat.after"
EVENT_EMOTION_CHANGED = "emotion.changed"
EVENT_AGENT_RESET = "agent.reset"

class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable[..., None]) -> None: ...

    def emit(self, event_type: str, **data: Any) -> None:
        """发送事件。callback 抛异常时 catch 并 warning，不中断其他订阅者。"""

    def unsubscribe(self, event_type: str, callback: Callable[..., None]) -> None: ...

    def clear(self) -> None: ...
```

**自检**：订阅 → emit → callback 被调用；一个 callback 抛异常不阻塞其他。

---

## Step 4 · `animate/io/__init__.py`

空文件，标记为 Python 包。

---

## Step 5 · `animate/io/base.py` — I/O 适配器接口

```python
from abc import ABC, abstractmethod
from animate.response import AgentResponse

class InputAdapter(ABC):
    @abstractmethod
    def receive(self) -> str:
        """阻塞等待用户输入，返回文本。"""

class OutputAdapter(ABC):
    @abstractmethod
    def send(self, response: AgentResponse) -> None:
        """将 Agent 回复呈现给用户。"""
```

**自检**：子类化并实现抽象方法，不报错。

---

## Step 6 · `animate/io/console.py` — 控制台适配器

```python
from animate.io.base import InputAdapter, OutputAdapter
from animate.emotion import Emotion

DEFAULT_EMOTION_ICONS = {
    Emotion.CALM:    "😶",
    Emotion.PLEASED: "🌸",
    Emotion.COLD:    "❄️",
}

class ConsoleInput(InputAdapter):
    def __init__(self, prompt: str = "> "): ...
    def receive(self) -> str:
        # 显示 prompt，调 input()，EOFError/KeyboardInterrupt 往上抛

class ConsoleOutput(OutputAdapter):
    def __init__(self, character_name: str = "Saki",
                 emotion_icons: dict | None = None): ...
    def send(self, response: AgentResponse) -> None:
        # 打印：角色名 + 情绪图标 + response.text
```

**自检**：`ConsoleInput().receive()` 等待输入；`ConsoleOutput().send(...)` 打印带图标回复。

---

## Step 7 · `animate/skills/memory_skill.py` — 自注册

```python
def on_register(self, agent) -> None:
    agent.set_memory_provider(self._memory)
```

---

## Step 8 · `animate/skills/emotion_skill.py` — 自注册 + 写入响应

```python
def on_register(self, agent) -> None:
    agent.set_emotion_provider(self.state_machine)

def on_reset(self) -> None:
    self.state_machine.reset()

# run() 末尾：
if ctx.response is None:
    from animate.response import AgentResponse
    ctx.response = AgentResponse(emotion=ctx.emotion)
else:
    ctx.response.emotion = ctx.emotion
```

---

## Step 9 · `animate/agent.py` — 核心重构

### 9a. 构造函数——去 isinstance

```python
class Agent:
    def __init__(self, skills: list[Skill], event_bus: EventBus | None = None):
        self.skills = skills
        self._memory: ConversationMemory | None = None
        self._emotion_state: EmotionStateMachine | None = None
        self._event_bus = event_bus or EventBus()

        for skill in self.skills:
            skill.on_register(self)
```

### 9b. 注册接口

```python
def set_memory_provider(self, memory: ConversationMemory) -> None:
    self._memory = memory

def set_emotion_provider(self, state_machine: EmotionStateMachine) -> None:
    self._emotion_state = state_machine
```

保留 `emotion_state` 和 `memory` 的 property getter（向后兼容）。

### 9c. chat() ——返回 AgentResponse + 发事件

```python
def chat(self, user_input: str) -> AgentResponse:
    self._event_bus.emit(EVENT_CHAT_BEFORE, user_input=user_input)

    ctx = SkillContext(user_input=user_input)
    for skill in self.skills:
        ctx = skill.run(ctx)

    system_prompt = "\n\n".join(ctx.system_prompt_parts) + "\n\n"
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(ctx.history)
    messages.append({"role": "user", "content": user_input})

    resp = get_llm_client().chat.completions.create(
        model=llm_model_name(),
        messages=messages,
    )
    response_text = resp.choices[0].message.content

    result = ctx.response or AgentResponse()
    result.text = response_text

    if self._memory:
        self._memory.add("user", user_input)
        self._memory.add("assistant", response_text)

    self._event_bus.emit(EVENT_CHAT_AFTER, response=result)
    return result
```

### 9d. reset()

```python
def reset(self) -> None:
    for skill in self.skills:
        skill.on_reset()
    self._event_bus.emit(EVENT_AGENT_RESET)
```

**关键变化**：返回 `AgentResponse` 而非 `str`；删除 `isinstance` 探测；事件在关键节点发送。

**自检**：`agent.chat("你好")` 返回 `AgentResponse`；连续对话正常；`reset()` 清空记忆。

---

## Step 10 · `cli.py` — 适配器化

```python
from animate.io.console import ConsoleInput, ConsoleOutput
from animate.response import AgentResponse

def main(input_adapter=None, output_adapter=None):
    input_adapter = input_adapter or ConsoleInput("> ")
    output_adapter = output_adapter or ConsoleOutput("Saki", emotion_icons)

    # ... 加载向量库、创建 Skills 和 Agent（同原来）...

    output_adapter.send(AgentResponse(text="Saki 已就绪，输入 'exit' 或 'quit' 退出。"))

    try:
        while True:
            try:
                line = input_adapter.receive()
            except EOFError:
                break

            if line.strip() == "/reset":
                agent.reset()
                output_adapter.send(AgentResponse(text="（对话记忆已清空）"))
                continue

            if line in {"exit", "quit"}:
                break

            if not line.strip():
                continue

            response = agent.chat(line)
            output_adapter.send(response)

    except KeyboardInterrupt:
        pass
    finally:
        output_adapter.send(AgentResponse(text="再见！"))
```

**关键决策**：系统提示也走 `output_adapter.send()`——后续语音/Unity 模式下这些提示也能被正确处理。`main()` 接受可选适配器参数，为后续阶段留插口。

**自检**：`python cli.py` 行为与重构前完全一致——多轮记忆、情绪切换、`/reset`、`exit`、`Ctrl+C` 均正常。

---

## Step 11 · 跑通后会想做的事

1. **grep 检查**：`grep -r "isinstance.*Skill" animate/` 确认 Agent 中无残留
2. **循环 import 检查**：`response.py` → `emotion.py`、`io/base.py` → `response.py`，单向无环
3. **EventBus 压测**：两个订阅者同时订阅 `chat.after`，确认都收到
4. **预留接口验证**：`AgentResponse.motion_tags`、`audio_data`、`metadata` 字段存在

---

## 卡住时的诊断顺序

| 症状 | 先怀疑 |
| --- | --- |
| 循环 import 报错 | `base.py` 没用 forward reference 而直接 import AgentResponse |
| `chat()` 返回了 str 而非 AgentResponse | return 语句没改过来 |
| 情绪不显示 | EmotionSkill 未向 ctx.response 写入 emotion |
| reset 后记忆仍在 | MemorySkill 没实现 on_reset，Agent 也没兜底 clear |
| 事件 callback 不触发 | emit 和 subscribe 的事件类型字符串不一致 |

---

## 完成 Phase 3 的判定

- [ ] `python cli.py` 一切功能与重构前一致
- [ ] `agent.chat("...")` 返回 `AgentResponse`（不是 str）
- [ ] `Agent.__init__` 不再包含 `isinstance(skill, ...)` 探测
- [ ] `InputAdapter` / `OutputAdapter` 可被子类化
- [ ] `EventBus` 发布/订阅正常工作
- [ ] 整个重构只涉及架构改动，无新功能
