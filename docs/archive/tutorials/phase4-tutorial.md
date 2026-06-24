# Phase 4 开发手册 · MCP + Tool Calling + 记忆系统 + 反馈学习

> 目标：在 Phase 3 通用框架基础上，让 Agent 变聪明——能调用外部 MCP 工具、拥有长期记忆、从对话中学习成长。
>
> 这份教程**只给思路、接口和自检清单，不给完整实现**。每一步留给你自己写。
>
> **前置状态**：Phase 3 通用框架已完成（`AgentResponse` / `EventBus` / I/O 适配器 / Skill 生命周期就绪）。

---

## 你需要先有的认知

- **MCP（Model Context Protocol）**：Anthropic 的模型上下文协议。MCP Server 暴露工具，Client 通过 stdio 或 HTTP 连接后 `tools/list` 发现工具、`tools/call` 调用工具。
- **Tool Calling / Function Calling**：LLM 不只能返回文本，还能返回 `tool_calls`——Agent 执行函数后把结果回传，LLM 再生成最终回复。
- **语义记忆**：把对话摘要 embed 成向量，用户提到相关话题时检索最相关的历史记忆——本质上和知识库 RAG 原理相同，只是检索对象变成了对话摘要。
- **摘要压缩**：对话超过窗口时，让 LLM 总结旧消息为一段摘要。用摘要替代原始消息，省 token 又不丢上下文。
- **用户画像**：从对话中提取结构化信息（偏好、习惯、关系），存为 profile，后续注入 system prompt。
- **反馈学习**：收集 👍/👎 和纠错文本，分析模式，自动调整行为。

---

## 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                          Agent（Phase 4 扩展）                    │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────┐      │
│  │   Skill Pipeline     │  │     Tool Calling Loop        │      │
│  │   (预处理)            │  │                              │      │
│  │                      │  │  tools = Registry.list()     │      │
│  │  PersonaSkill        │  │  while (max 5 rounds):       │      │
│  │  RetrievalSkill      │  │    resp = LLM(messages+tools)│      │
│  │  MemorySkill ──┐     │  │    if resp.text → break      │      │
│  │  EmotionSkill  │     │  │    if resp.tool_calls:       │      │
│  └────────────────┼─────┘  │      for each tc:             │      │
│                   │        │        result = Registry      │      │
│                   │        │          .execute(name,args)  │      │
│                   ▼        │        messages += result     │      │
│  ┌──────────────────────┐  └──────────────┬───────────────┘      │
│  │   MemoryManager      │                 │                      │
│  │                      │                 ▼                      │
│  │  ┌────────────────┐  │  ┌──────────────────────────────┐      │
│  │  │ MemoryStore    │  │  │      ToolRegistry            │      │
│  │  │ (SQLite)       │  │  │                              │      │
│  │  ├────────────────┤  │  │  local_tools {}              │      │
│  │  │ Summarizer     │  │  │  mcp_tools {}                │      │
│  │  │ (LLM 摘要压缩)  │  │  │                              │      │
│  │  ├────────────────┤  │  │  list_tools() → OpenAI fmt   │      │
│  │  │ Retriever      │  │  │  execute(name, args) → Result│      │
│  │  │ (语义记忆检索)   │  │  └──────────────┬───────────────┘      │
│  │  ├────────────────┤  │                 │                      │
│  │  │ ProfileManager │  │        ┌────────┼────────┐             │
│  │  │ (用户画像)      │  │        │        │        │             │
│  │  └────────────────┘  │        ▼        ▼        ▼             │
│  └──────────────────────┘  ┌──────────┐┌──────────┐┌──────────┐  │
│                            │ 本地工具  ││MCP Srv A ││MCP Srv B │  │
│                            │(LocalTool)││(Web搜索)  ││(数据库)   │  │
│                            └──────────┘└──────────┘└──────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                  LearningController                       │    │
│  │                                                          │    │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │    │
│  │  │FeedbackCollector│PreferenceLearner│KBExpander  │      │    │
│  │  │  👍/👎 收集   │ │ 自动偏好推断  │ │ 知识库扩充  │      │    │
│  │  │  纠错记录      │ │ 画像更新     │ │ 增量索引    │      │    │
│  │  └──────────────┘ └──────────────┘ └──────────────┘      │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

**一句话总结**：Skill Pipeline 做预处理，MemoryManager 管长期记忆，ToolRegistry 管工具（本地+MCP），Tool Calling Loop 让 LLM 动态调用工具，LearningController 从反馈中改进。

---

## 总览：你要新建 / 修改的组件

本阶段分三部分，**建议按顺序做**。

### Part A · MCP + Tool Calling

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| A1 | `animate/tools/__init__.py` | **新建**：tools 包入口 |
| A2 | `animate/tools/base.py` | **新建**：`LocalTool` ABC + `ToolResult` |
| A3 | `animate/mcp/__init__.py` | **新建**：mcp 包入口 |
| A4 | `animate/mcp/client.py` | **新建**：MCP 协议客户端（stdio/HTTP） |
| A5 | `animate/tools/registry.py` | **新建**：ToolRegistry 统一管理本地+MCP 工具 |
| A6 | `animate/agent.py` | **修改**：chat() 加入 Tool Calling 循环 |

### Part B · 记忆系统升级

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| B1 | `animate/memory/store.py` | **新建**：SQLite 持久化存储 |
| B2 | `animate/memory/summarizer.py` | **新建**：LLM 驱动的摘要压缩 |
| B3 | `animate/memory/retrieval.py` | **新建**：语义记忆检索（embed 历史摘要） |
| B4 | `animate/memory/profile.py` | **新建**：用户画像提取、存储、注入 |
| B5 | `animate/memory/manager.py` | **新建**：MemoryManager 统一门面 |
| B6 | `animate/agent.py` | **修改**：Agent 集成 MemoryManager |

### Part C · 反馈学习

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| C1 | `animate/learning/__init__.py` | **新建**：learning 包入口 |
| C2 | `animate/learning/feedback.py` | **新建**：用户反馈收集与分析 |
| C3 | `animate/learning/preference.py` | **新建**：自动偏好推断 |
| C4 | `animate/learning/kb_expander.py` | **新建**：知识库自动扩充 |
| C5 | `animate/learning/controller.py` | **新建**：LearningController 统一入口 |
| C6 | `animate/agent.py` / `cli.py` | **修改**：集成反馈 + `/like` `/dislike` 命令 |

---

# Part A · MCP + Tool Calling

---

## Step A1 · `animate/tools/__init__.py`

空文件，标记为包。

---

## Step A2 · `animate/tools/base.py` — 本地工具接口

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class ToolResult:
    success: bool
    content: str           # 回传给 LLM 的文本

class LocalTool(ABC):
    name: str               # 工具名（LLM 据此决定调哪个）
    description: str        # 工具描述（LLM 据此判断何时调用）
    parameters: dict        # JSON Schema 格式的参数定义

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """执行工具。kwargs 由 LLM tool_call arguments 映射而来。"""
```

**示例——把检索能力暴露为工具**：

```python
class SearchKnowledgeTool(LocalTool):
    name = "search_knowledge"
    description = "搜索祥子的知识库，获取与给定关键词相关的背景信息。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要在知识库中搜索的关键词"}
        },
        "required": ["query"],
    }

    def __init__(self, vector_store, keyword_store): ...
    def execute(self, query: str) -> ToolResult:
        # 执行双路检索...
        return ToolResult(success=True, content="\n\n".join(chunks))
```

**自检**：子类化 `LocalTool` 并实现 `execute`，不报错。

---

## Step A3 · `animate/mcp/__init__.py`

空文件。

---

## Step A4 · `animate/mcp/client.py` — MCP 协议客户端

```python
import json, subprocess
from animate.tools.base import ToolResult

class MCPServerConfig:
    def __init__(self, name: str, transport: str = "stdio",
                 command: str | None = None, args: list[str] | None = None,
                 url: str | None = None): ...

class MCPClient:
    def __init__(self, servers: list[MCPServerConfig] | None = None): ...

    def connect_all(self) -> dict[str, bool]:
        """依次连接所有 Server。失败不阻塞。"""

    def discover_tools(self) -> list[dict]:
        """向所有 Server 发送 tools/list，返回 OpenAI 兼容的 tool 定义列表。"""

    def call_tool(self, server_name: str, tool_name: str,
                  arguments: dict) -> ToolResult: ...

    def close_all(self) -> None: ...
```

**MCP 核心交互**（JSON-RPC 2.0 over stdio）：

```python
# 1. 启动子进程
proc = subprocess.Popen([cmd] + args, stdin=PIPE, stdout=PIPE)

# 2. initialize 握手
send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...}})
resp = read_response()

# 3. 获取工具列表
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
tools = resp["result"]["tools"]

# 4. 调用工具
send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
      "params": {"name": tool_name, "arguments": args}})
result = resp["result"]
```

**MCP tool schema → OpenAI format**：MCP 返回 `inputSchema` → OpenAI 要 `parameters`，改名即可。

**自检**：写一个 echo MCP server → `connect_all()` → `discover_tools()` 返回 echo 工具 → `call_tool` 返回正确结果。

---

## Step A5 · `animate/tools/registry.py` — 工具注册中心

```python
class ToolRegistry:
    def __init__(self, mcp_client: MCPClient | None = None): ...

    def register_local(self, tool: LocalTool) -> None: ...

    def register_from_skill(self, skill) -> None:
        """如果 Skill 有 get_tools() → list[LocalTool]，批量注册。"""

    def discover_mcp_tools(self) -> int:
        """从 MCP Client 发现并注册远端工具。返回发现数量。"""

    def list_tools(self) -> list[dict]:
        """返回所有工具的 OpenAI function-calling 格式定义。"""

    def execute(self, tool_name: str, arguments: dict) -> ToolResult:
        """执行工具。本地优先，再查 MCP。找不到返回 success=False。"""

    @property
    def tool_count(self) -> int: ...
```

**关键决策**：本地工具优先于 MCP（同名覆盖）；`list_tools()` 返回 `[]` 时 Agent 跳过 Tool Calling；`execute()` 内部 try/except 防崩溃。

**自检**：注册 2 本地 + 1 MCP → `tool_count=3`；`list_tools()` 返回 3 个 OpenAI 格式定义。

---

## Step A6 · `animate/agent.py` — Tool Calling 循环

```python
def chat(self, user_input: str) -> AgentResponse:
    # ── Phase 1: Skill Pipeline 预处理 ──
    ctx = SkillContext(...)
    for skill in self.skills: ctx = skill.run(ctx)
    messages = [system_prompt] + history + [user_msg]

    # ── Phase 2: Tool Calling 循环 ──
    tools = self._tool_registry.list_tools()
    tool_round, max_rounds = 0, 5

    while tool_round < max_rounds:
        kwargs = {"model": ..., "messages": messages}
        if tools: kwargs["tools"] = tools

        resp = get_llm_client().chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        if msg.content and not msg.tool_calls:    # → 文本，结束
            response_text = msg.content; break

        if msg.tool_calls:                        # → 工具调用
            messages.append({...})  # assistant msg with tool_calls
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = self._tool_registry.execute(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": result.content})
            tool_round += 1; continue

        response_text = ""; break

    # ── Phase 3: 构建响应 ──
    result = ctx.response or AgentResponse()
    result.text = response_text
    # 记录记忆 + 发送事件
    return result
```

**`max_tool_rounds=5`**：防止 LLM 在工具间反复横跳无限循环。

**自检**：无工具时行为不变；注册 echo 工具 → LLM 调用 → 回复含 echo 结果。

---

# Part B · 记忆系统升级

---

## Step B1 · `animate/memory/store.py` — SQLite 持久化

**数据库 schema**：

```sql
CREATE TABLE sessions (id TEXT PRIMARY KEY, label TEXT, created_at TIMESTAMP);
CREATE TABLE messages (id INTEGER PK, session_id TEXT, role TEXT,
                       content TEXT, created_at TIMESTAMP);
CREATE TABLE summaries (id INTEGER PK, session_id TEXT,
                        start_msg_id INT, end_msg_id INT,
                        content TEXT, created_at TIMESTAMP);
CREATE TABLE profile (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP);
```

**接口**：

```python
class MemoryStore:
    def __init__(self, db_path=Path("data/memory.db")): ...
    def create_session(self, label="") -> str: ...
    def list_sessions(self, limit=20) -> list[dict]: ...
    def load_session(self, session_id) -> list[dict]: ...
    def add_message(self, session_id, role, content) -> None: ...
    def get_messages(self, session_id, limit=40, offset=0) -> list[dict]: ...
    def save_summary(self, session_id, start, end, summary) -> None: ...
    def get_summaries(self, session_id) -> list[dict]: ...
```

**自检**：创建 session → add 5 条消息 → 重启进程 → 消息仍在。

---

## Step B2 · `animate/memory/summarizer.py` — 摘要压缩

```python
class MemorySummarizer:
    def summarize(self, messages: list[dict]) -> str:
        """将对话压缩为 1~3 句摘要（含话题、关键信息、用户偏好）。"""

    def compress_session(self, store, session_id,
                         max_messages=40, compress_count=20) -> int:
        """会话超出 max_messages 时自动压缩最早的 compress_count 条。"""
```

**摘要 prompt 示例**：

> 请将以下对话片段压缩为一段中文摘要（不超过 3 句话）：包含话题和关键信息、用户表达的偏好或个人信息、角色的回应要点。

**自检**：10 轮对话 → `summarize()` 返回 2~3 句摘要。

---

## Step B3 · `animate/memory/retrieval.py` — 语义记忆检索

```python
class MemoryRetriever:
    """复用 VectorStore + embed()，检索对象为历史摘要。"""

    def __init__(self, memory_store, vector_store=None): ...

    def index_summaries(self, session_id) -> int:
        """将会话摘要 embed 后加入向量库。"""

    def search(self, query, top_k=3) -> list[str]: ...

    def search_and_format(self, query, top_k=3) -> str:
        """检索并格式化为可注入 system prompt 的文本。"""
```

**思路**：和知识库 RAG 完全相同的原理，只是检索对象从文档 chunks 换成了对话摘要。

**自检**：生成 5 条摘要 → index → search("钢琴比赛") → 返回最相关摘要。

---

## Step B4 · `animate/memory/profile.py` — 用户画像

```python
@dataclass
class UserProfile:
    name: str = ""
    preferences: dict = {}   # {"topics": ["钢琴"], "style": "简洁"}
    facts: list[str] = []    # ["用户是大学生", "学过3年钢琴"]
    relationship: str = ""
    interaction_count: int = 0

class ProfileManager:
    def __init__(self, memory_store): ...
    def load(self) -> UserProfile: ...
    def save(self, profile) -> None: ...

    def extract_from_conversation(self, messages) -> dict:
        """用 LLM 从对话中提取用户事实/偏好，返回新信息 dict。"""

    def update_from_conversation(self, messages) -> UserProfile: ...

    def to_system_prompt(self) -> str:
        """将画像转为可注入 system prompt 的文本。"""
```

**LLM 提取 prompt**：只提取明确提到的内容，不要推测。返回 JSON `{name, facts, interests, relationship_clue}`。

**自检**：用户聊到"我是大学生，学钢琴三年" → `extract` 返回对应 facts。

---

## Step B5 · `animate/memory/manager.py` — MemoryManager 统一入口

```python
class MemoryManager:
    def __init__(self, db_path=Path("data/memory.db")): ...
    # 内含 store, summarizer, retriever, profile_manager

    def start_session(self, label="") -> str: ...
    def resume_session(self, session_id) -> list[dict]: ...

    def add_message(self, role, content) -> None: ...
    def get_context_messages(self, max=20) -> list[dict]:
        """近 20 条原始消息 + 旧消息摘要，合并返回。"""

    def inject_memories(self, ctx: SkillContext) -> None:
        """语义检索 + 用户画像 → 注入 ctx.system_prompt_parts。"""

    def post_turn_maintenance(self) -> None:
        """每轮后：检查压缩 + 更新画像 + 索引摘要。"""
```

**自检**：add 30 条 → `get_context_messages` 返回 20 近消息 + 早期摘要。

---

## Step B6 · Agent 集成 MemoryManager

**MemorySkill 升级**（替代旧版）：

```python
class MemorySkill(Skill):
    name = "memory"
    def __init__(self, memory_manager: MemoryManager): ...
    def run(self, ctx):
        ctx.history = self._manager.get_context_messages()
        self._manager.inject_memories(ctx)
        return ctx
    def on_register(self, agent):
        agent.set_memory_manager(self._manager)
```

**Agent.chat() 末尾**：

```python
if self._memory_manager:
    self._memory_manager.add_message("user", user_input)
    self._memory_manager.add_message("assistant", response_text)
    self._memory_manager.post_turn_maintenance()
```

---

# Part C · 反馈学习

---

## Step C1 · `animate/learning/__init__.py`

空文件。

---

## Step C2 · `animate/learning/feedback.py` — 反馈收集

```python
@dataclass
class Feedback:
    session_id: str
    user_input: str
    assistant_response: str
    rating: int | None = None       # 1=赞, -1=踩
    correction: str | None = None   # 用户纠错文本

class FeedbackCollector:
    def __init__(self, memory_store): ...
    def record_rating(self, session_id, user_input, response, rating): ...
    def record_correction(self, session_id, user_input, response, correction): ...
    def get_recent_feedback(self, limit=50) -> list[Feedback]: ...
    def analyze_patterns(self) -> dict:
        """分析：哪些话题容易得 👎？哪些风格得 👍？"""
```

---

## Step C3 · `animate/learning/preference.py` — 自动偏好推断

```python
class PreferenceLearner:
    """
    不依赖显式反馈，观察交互信号：
    - 用户连续追问 → 上一个回答不够好
    - 用户很快结束话题 → 不感兴趣
    - 用户消息越来越长 → 喜欢当前话题
    """

    def analyze_session(self, session_id) -> dict:
        """返回 {engaged_topics, disengaged_topics, preferred_style, ...}"""

    def update_profile(self, session_id) -> None:
        """分析并更新画像。"""
```

**思路**：用启发式规则（不用 LLM，省 token）。多轮确认后才写入画像，避免噪音。

---

## Step C4 · `animate/learning/kb_expander.py` — 知识库自动扩充

```python
class KnowledgeBaseExpander:
    def __init__(self, learned_dir=Path("data/learned")): ...

    def handle_correction(self, original_query, original_response, correction) -> str | None:
        """从纠错中提取事实 → 格式化为 Markdown → 保存到 data/learned/。
           去重检测（embedding 相似度 > 0.9 则跳过）。"""

    def handle_new_fact(self, user_input) -> str | None:
        """检测用户输入中是否包含值得记录的新事实。"""

    def rebuild_indexes(self) -> None:
        """增量重建向量库和关键词库（追加新文档 chunks）。"""
```

---

## Step C5 · `animate/learning/controller.py` — 统一入口

```python
class LearningController:
    def __init__(self, memory_store, profile_manager, kb_expander=None): ...

    def on_rating(self, rating, user_input, response) -> None: ...
    def on_correction(self, correction, user_input, response) -> str | None: ...
    def end_of_session(self, session_id) -> None:
        """分析交互模式 → 更新画像 → 建议 KB 更新。"""
```

---

## Step C6 · CLI 集成

```python
# 主循环新增命令：
elif line == "/like":
    agent.record_feedback(rating=1)
elif line == "/dislike":
    agent.record_feedback(rating=-1)
    correction = input("纠正内容（回车跳过）: ")
    if correction.strip():
        new_knowledge = agent.handle_correction(correction)
elif line == "/reindex":
    agent.rebuild_knowledge_indexes()
```

---

## 完成 Phase 4 的判定

- [ ] 连接 MCP Server → Agent 发现并调用远端工具；MCP 不可用 → 降级正常对话
- [ ] 对话 20 轮 → 关闭重启 → 恢复会话 → Agent 记得上下文
- [ ] 早期对话被自动压缩为摘要，语义检索能命中历史话题
- [ ] profile 表中有正确的用户画像信息
- [ ] `/like` `/dislike` + 纠错 → 反馈记录 + KB 自动扩充
- [ ] `/reindex` → 新知识可被检索到
