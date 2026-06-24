# Phase 2 手把手搭建教程

> 目标：在 Phase 1 的单轮问答基础上，加入**多轮对话记忆**和**情绪状态机**，让祥子能记住这次聊天的上下文，并根据对话内容在"平静 / 愉快 / 冷漠"三种情绪间切换。
>
> 这份教程**只给思路、接口和自检清单，不给完整实现**。每一步留给你自己写。

---

## 你需要先有的认知

- **多轮对话**：LLM 的 `messages` 参数本身就是一个列表，把历史 `{"role": "user/assistant", "content": "..."}` 追加进去就能实现上下文连贯。
- **状态机**：一个有限的状态集合 + 转移规则。Phase 2 的情绪状态机只有 3 个状态，转移条件由简单规则或 LLM 判断驱动。
- **SkillContext 扩展**：Phase 1 已经把 `SkillContext` 设计成可扩展的 dataclass，Phase 2 只需要加字段，不需要改已有 skill 的代码。

如果上面任何一条你觉得模糊，先去查清楚再继续。

---

## 总览：你要新建 / 修改的组件

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| 1 | `animate/memory.py` | 对话历史管理，存储多轮消息 |
| 2 | `animate/emotion.py` | 情绪状态机，定义状态和转移规则 |
| 3 | `animate/skills/base.py` | 扩展 `SkillContext`，加入 `history` 和 `emotion` 字段 |
| 4 | `animate/skills/memory_skill.py` | 把历史消息注入 context 的 skill |
| 5 | `animate/skills/emotion_skill.py` | 读取情绪状态、附加情绪指令到 system prompt 的 skill |
| 6 | `animate/agent.py` | 改造为多轮：保存每轮对话，更新情绪状态 |
| 7 | `animate/cli.py` | 显示当前情绪，支持 `/reset` 命令清空记忆 |
| 8a | `animate/rag/loader.py` | 按 Markdown 标题切块（Header-aware Chunking） |
| 8b | `animate/rag/loader.py` | 句子级边界对齐，避免从句子中间截断 |
| 8c | `buildVecLibrary.py` | 换用新切块函数，重建向量库 |
| 9a | `animate/rag/keyword_index.py` | jieba 分词倒排索引，补充关键词检索 |
| 9b | `animate/skills/retrieval.py` | 两路检索结果用 RRF 重排序后注入 context |
| 10 | 跑通 & 调优 | 验证记忆连贯性、情绪切换、检索准确度 |

**不要跳着写**。步骤 1-2 是纯数据结构，先把它们写对，后面才能顺。

---

## Step 1 · `animate/memory.py` — 对话历史

### 为什么单独一个文件

对话历史的增删查逻辑集中在这里，Agent 只调接口，不直接操作列表。以后做持久化（存到文件/数据库）也只改这一处。

### 接口

```python
class ConversationMemory:
    def __init__(self, max_turns: int = 20): ...
    def add(self, role: str, content: str) -> None: ...
    # role 只允许 "user" 或 "assistant"
    def get_messages(self) -> list[dict]: ...
    # 返回 [{"role": "user", "content": "..."}, ...]
    def clear(self) -> None: ...
    def __len__(self) -> int: ...
    # 返回当前存储的消息条数
```

### 思路

- 内部用一个 `list[dict]` 存储，每条消息是 `{"role": ..., "content": ...}`。
- `max_turns` 控制最多保留多少轮（1 轮 = 1 user + 1 assistant）。超出时从头部丢弃最旧的一轮。
- **为什么要截断**：LLM 有 context 长度上限，无限追加历史会报错，也浪费 token。

### 自检

- `add` 10 条后，`len()` 返回 10。
- 如果 `max_turns=3`，add 了 8 条（4 轮），`get_messages()` 只返回最近 6 条（3 轮）。
- `clear()` 后 `len()` 返回 0。

---

## Step 2 · `animate/emotion.py` — 情绪状态机

### 情绪状态定义

Phase 2 只做 3 种情绪，够用且不复杂：

| 状态 | 说明 | 触发条件（示例） |
| --- | --- | --- |
| `CALM` | 平静（默认） | 初始状态；对话平淡无特别触发 |
| `PLEASED` | 愉快 | 用户提到钢琴、古典音乐、茶、猫 |
| `COLD` | 冷漠 | 用户态度粗鲁、或话题涉及家族/父亲 |

### 接口

```python
from enum import Enum

class Emotion(Enum):
    CALM = "calm"
    PLEASED = "pleased"
    COLD = "cold"

class EmotionStateMachine:
    def __init__(self): ...
    @property
    def current(self) -> Emotion: ...
    def update(self, user_input: str) -> Emotion: ...
    # 根据 user_input 决定是否切换情绪，返回新状态
    def reset(self) -> None: ...
```

### 思路

`update` 的实现可以从简单规则开始：

```python
PLEASED_KEYWORDS = {"钢琴", "古典", "音乐", "茶", "猫", "演奏", "肖邦"}
COLD_KEYWORDS = {"家族", "祖父", "父亲", "丰川集团", "滚", "闭嘴", "烦"}

def update(self, user_input: str) -> Emotion:
    if any(kw in user_input for kw in COLD_KEYWORDS):
        self._current = Emotion.COLD
    elif any(kw in user_input for kw in PLEASED_KEYWORDS):
        self._current = Emotion.PLEASED
    else:
        # 情绪有惯性：不触发时缓慢回归 CALM
        if self._current != Emotion.CALM:
            self._current = Emotion.CALM
    return self._current
```

**关键决策**：情绪不要每句话都剧烈变化，加入"惯性"——只有明确触发才切换，否则缓慢回归 CALM。

### 自检

- 输入"你喜欢钢琴吗"，状态变为 `PLEASED`。
- 紧接着输入"今天天气怎么样"（无触发词），状态回归 `CALM`。
- 输入"你祖父真差劲"，状态变为 `COLD`。

---

## Step 3 · `animate/skills/base.py` — 扩展 SkillContext

在原有 `SkillContext` 上加两个字段：

```python
@dataclass
class SkillContext:
    user_input: str
    retrieved_chunks: list[str] = field(default_factory=list)
    system_prompt_parts: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)   # ← 新增：对话历史
    emotion: Emotion = Emotion.CALM                      # ← 新增：当前情绪
```

**注意**：`Emotion` 需要从 `animate.emotion` import。`base.py` 依赖 `emotion.py`，确保没有循环 import。

### 自检

- 原有的 `PersonaSkill` 和 `RetrievalSkill` 不需要改动，仍能正常运行。
- 新建一个临时脚本，构造带 `history` 字段的 `SkillContext`，确认不报错。

---

## Step 4 · `animate/skills/memory_skill.py` — 记忆注入 Skill

```python
class MemorySkill(Skill):
    name = "memory"
    def __init__(self, memory: ConversationMemory): ...
    def run(self, ctx: SkillContext) -> SkillContext:
        # 把 memory.get_messages() 赋给 ctx.history
```

这个 skill 本身很简单，只是把外部的 `ConversationMemory` 对象和 `SkillContext` 打通。

**关键决策**：`MemorySkill` 只负责读取历史注入 context，**不负责写入**。写入（保存本轮对话）由 `Agent` 在 LLM 返回后统一做，保持职责单一。

### 自检

- 构造一个有 3 条历史的 `ConversationMemory`，经过 `MemorySkill.run()` 后，`ctx.history` 长度为 3。

---

## Step 5 · `animate/skills/emotion_skill.py` — 情绪 Skill

```python
class EmotionSkill(Skill):
    name = "emotion"
    def __init__(self, state_machine: EmotionStateMachine): ...
    def run(self, ctx: SkillContext) -> SkillContext:
        # 1. state_machine.update(ctx.user_input) 更新情绪
        # 2. ctx.emotion = state_machine.current
        # 3. 根据 ctx.emotion 生成情绪指令，append 到 ctx.system_prompt_parts
```

情绪指令示例（你来写具体文案）：

```python
EMOTION_PROMPTS = {
    Emotion.CALM:    "你现在心情平静，回答简洁克制。",
    Emotion.PLEASED: "你现在心情愉快，可以比平时多说一两句，语气略微温和。",
    Emotion.COLD:    "你现在情绪冷淡，回答更加简短，语气疏离，不想多谈。",
}
```

**关键决策**：情绪指令追加在 system prompt **末尾**，优先级低于 persona，但高于检索结果。调整顺序：`[PersonaSkill, MemorySkill, RetrievalSkill, EmotionSkill]`。

### 自检

- 触发 `PLEASED` 后，`ctx.system_prompt_parts` 最后一条包含愉快相关的指令。

---

## Step 6 · `animate/agent.py` — 改造为多轮

这是改动最大的一步。

### 新的 `chat` 接口

```python
class Agent:
    def __init__(self, skills: list[Skill], memory: ConversationMemory): ...
    def chat(self, user_input: str) -> str:
        # 1. ctx = SkillContext(user_input=user_input)
        # 2. for skill in self.skills: ctx = skill.run(ctx)
        # 3. system_prompt = "\n\n".join(ctx.system_prompt_parts)
        # 4. 构造 messages：
        #    [{"role": "system", "content": system_prompt}]
        #    + ctx.history                   ← 历史消息插在这里
        #    + [{"role": "user", "content": user_input}]
        # 5. 调 LLM，拿到 response_text
        # 6. memory.add("user", user_input)
        #    memory.add("assistant", response_text)
        # 7. return response_text
    def reset(self) -> None:
        # memory.clear() + emotion_state_machine.reset()
```

### 思路
- `memory` 对象由外部（cli.py）创建后注入，Agent 不负责实例化。
- `MemorySkill` 需要持有同一个 `memory` 对象的引用，确保 `Agent` 写入的历史能被下次 `MemorySkill.run()` 读到。

### 自检

- 连续问两个问题，第二个问题里引用第一个问题的内容（比如"你刚才说的那首曲子叫什么"），LLM 应该能正确回答。
- 调用 `agent.reset()` 后，第三个问题不再记得前两轮内容。

---

## Step 7 · `animate/cli.py` — 显示情绪与 /reset 命令

在 REPL 里加两个东西：

### 显示当前情绪

每次回答前（或提示符里）显示当前情绪，便于调试：

```python
emotion_icons = {
    Emotion.CALM:    "😶",
    Emotion.PLEASED: "🌸",
    Emotion.COLD:    "❄️",
}
print(f"Saki {emotion_icons[agent.emotion_state.current]}:", response)
```

### /reset 命令

```python
if line.strip() == "/reset":
    agent.reset()
    print("（对话记忆已清空）")
    continue
```

### 自检

- 输入"你喜欢钢琴吗"，提示符前出现 🌸。
- 输入 `/reset`，下一轮对话不记得之前的内容。

---

## Step 8 · 升级切块：语义感知分块

> Phase 1 的 `chunk_text` 按 `\n\n` 硬切段落，碰到 Markdown 标题、表格、列表时会把同一个语义单元拆散，导致检索时拿到半截内容。Phase 2 改成能识别文档结构的切块方式。

### 现有方案的问题

| 场景 | 问题 |
| --- | --- |
| `## 标题\n内容` | 标题和正文可能切进不同的块，检索结果是没有标题的孤立段落 |
| Markdown 表格 | 表格行被 `\n\n` 分开后每行单独成块，失去行间关联 |
| 列表项 `- xxx` | 多个列表项被拆散，单项语义不完整 |
| 超长单段落 | 硬按字符截断，句子从中间断开 |

### Step 8a · 按标题分段（Header-aware Chunking）

**思路：**

Markdown 文档有天然层级结构，`##` / `###` 标题是最好的语义边界。先按标题切出"节"，再对过长的节做二次切块：

```python
# animate/rag/loader.py 新增函数

import re

def chunk_by_headers(text: str, max_chars: int = 500, overlap: int = 100) -> list[str]:
    """
    按 Markdown 标题（# / ## / ###）切块。
    每个标题连同其下的内容作为一个单元，过长时调用 chunk_text 二次切分。
    没有标题时退化为原来的 chunk_text。
    """
    header_pattern = re.compile(r'^(#{1,3} .+)$', re.MULTILINE)
    splits = [m.start() for m in header_pattern.finditer(text)]

    if not splits:
        return chunk_text(text, max_chars, overlap)

    sections = []
    for i, start in enumerate(splits):
        end = splits[i + 1] if i + 1 < len(splits) else len(text)
        sections.append(text[start:end].strip())

    chunks = []
    for section in sections:
        if not section:
            continue
        if len(section) <= max_chars:
            chunks.append(section)
        else:
            chunks.extend(chunk_text(section, max_chars, overlap))
    return chunks
```

**关键决策**：标题本身保留在 chunk 里，不要只取标题下的正文。这样检索结果自带上下文标签，LLM 能知道这段内容归属于哪个部分，回答更准确。

**自检：**
- 对 `toyokawa_shoko_profile.md` 切块，每块开头应带有 `##` 或 `###` 标题。
- `## 兴趣爱好` 下的内容不应与 `## 性格特点` 的内容混在同一块。

---

### Step 8b · 句子级边界对齐

硬按字符数截断会从句子中间切断。在 `chunk_text` 做硬切时，加一个"向前找最近句子结束符"的修正：

```python
SENTENCE_ENDINGS = ('。', '！', '？', '…', '.', '!', '?')

def find_sentence_boundary(text: str, pos: int, search_range: int = 50) -> int:
    """
    在 pos 向前搜索 search_range 个字符，找最近的句子结束符位置。
    找不到时直接返回 pos（兜底硬切）。
    """
    start = max(0, pos - search_range)
    segment = text[start:pos]
    for i in range(len(segment) - 1, -1, -1):
        if segment[i] in SENTENCE_ENDINGS:
            return start + i + 1
    return pos
```

在 `chunk_text` 里，把超长段落的硬切 `end` 替换成 `find_sentence_boundary(para, end)`，切出来的每块结尾就是完整句子。

**自检：** 每个 chunk 的最后一个字符应该是句号/问号/感叹号之类的标点，而不是汉字或字母中间截断。

---

### Step 8c · 更新 `buildVecLibrary.py`

把切块函数从 `chunk_text` 换成 `chunk_by_headers`：

```python
from animate.rag.loader import load_documents, chunk_by_headers

# ...
all_chunks = chunk_by_headers(combined, max_chars=500, overlap=100)
```

⚠️ **切块方式改变后，向量库必须重新构建**，旧的 `store.pkl` 不能复用，否则 embedding 和 chunk 内容对不上。

---

## Step 9 · 升级检索：关键词检索 + 重排序

> Phase 1 的 `RetrievalSkill` 只做了向量相似度检索。纯向量检索对语义相近的问题效果好，但对精确词匹配（人名、专有名词、歌曲名）效果差。Phase 2 加入关键词检索并对两路结果做重排序，覆盖两种场景。

### 为什么要两路检索

| 检索方式 | 擅长 | 不擅长 |
| --- | --- | --- |
| 向量检索（当前） | 语义相似、换词表达 | 精确词匹配、专有名词 |
| 关键词检索（新增） | 精确词命中、歌名/人名 | 同义词、语义泛化 |

两路合并后取并集，再重排序，兼顾两者优势。

### Step 9a · 关键词检索

**思路：**

不引入额外依赖，用 `jieba` 做中文分词后构建倒排索引：

```python
# animate/rag/keyword_index.py

import jieba
from collections import defaultdict

class KeywordStore:
    def __init__(self):
        self._index: dict[str, list[int]] = defaultdict(list)
        # token → [chunk_idx, ...]
        self._chunks: list[str] = []

    def build(self, chunks: list[str]) -> None:
        # 对每个 chunk 分词，建立 token → chunk_idx 的倒排索引
        self._chunks = chunks
        for idx, chunk in enumerate(chunks):
            tokens = set(jieba.cut(chunk))
            for token in tokens:
                if len(token.strip()) > 1:   # 过滤单字和空格
                    self._index[token].append(idx)

    def search(self, query: str, top_k: int = 4) -> list[tuple[str, float]]:
        # 1. 对 query 分词
        # 2. 统计每个 chunk 命中的 token 数量（hit_count）
        # 3. 按 hit_count 降序返回 top_k，score = hit_count / len(query_tokens)
        ...

    def save(self, path) -> None: ...   # pickle 序列化
    @classmethod
    def load(cls, path) -> "KeywordIndex": ...
```

**接入方式：**

- `buildVecLibrary.py` 里在保存 `VectorStore` 后，同步构建并保存 `KeywordIndex`：
  ```python
  from animate.rag.keyword_index import KeywordIndex
  keyword_index = KeywordIndex()
  keyword_index.build(all_chunks)
  keyword_index.save(Path("animate/rag/vectorlibrary/keyword_index.pkl"))
  ```
- `RetrievalSkill.__init__` 新增 `keyword_index: KeywordIndex | None = None` 参数，可选传入。

**自检：** 查询"春日影"，关键词检索 top-1 应该是包含《春日影》的 chunk；向量检索可能排在第 2-3 位。

---

### Step 9b · 重排序（Reciprocal Rank Fusion）

两路检索结果合并后需要统一排序。最简单且效果不错的方法是 **RRF（倒数排名融合）**：

```python
def reciprocal_rank_fusion(
    vector_results: list[tuple[str, float]],
    keyword_results: list[tuple[str, float]],
    k: int = 60,
    top_n: int = 4,
) -> list[tuple[str, float]]:
    """
    RRF score = Σ 1 / (k + rank_i)
    两路结果各自贡献一个排名分，相加后重新排序。
    k=60 是经验值，防止头名分数过高。
    """
    scores: dict[str, float] = {}

    for rank, (chunk, _) in enumerate(vector_results):
        scores[chunk] = scores.get(chunk, 0) + 1 / (k + rank + 1)

    for rank, (chunk, _) in enumerate(keyword_results):
        scores[chunk] = scores.get(chunk, 0) + 1 / (k + rank + 1)

    sorted_chunks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_chunks[:top_n]
```

**接入位置**：在 `RetrievalSkill.run()` 里，向量检索结果和关键词检索结果都拿到后，调用 `reciprocal_rank_fusion` 合并，再过 0.3 分数阈值过滤。

**自检：**
- 查询"《春日影》是谁写的"，合并排序后 top-1 应该比纯向量检索更准确命中包含"春日影"的 chunk。
- 查询"祥子的性格"这类语义问题，合并结果与纯向量检索结果应该基本一致（关键词路贡献较少）。

---

## Step 10 · 跑通后会想做的事

按重要性排序：

1. **验证记忆窗口**：连续聊超过 `max_turns` 轮，确认最旧的内容被正确丢弃，不报 token 超限。
2. **情绪调优**：关键词表覆盖不到的场景，考虑用一个轻量的 LLM 调用来判断情绪（增加延迟但更准确）。
3. **情绪对回答的影响**：实际聊几轮，看不同情绪下的回答语气差异够不够明显，不够就加强 `EMOTION_PROMPTS` 里的指令。
4. **历史压缩**：`max_turns` 太小会丢失重要上下文，太大会超 token。可以做「摘要压缩」——把旧轮次的内容让 LLM 压缩成一段摘要，用摘要替换原始消息。Phase 3 再做。
5. **持久化**：目前记忆在进程结束后消失。如果想跨次对话保留，把 `ConversationMemory` 序列化到文件（json 或 pickle）。

---

## 卡住时的诊断顺序

| 症状 | 先怀疑 |
| --- | --- |
| 第二轮不记得第一轮内容 | `ctx.history` 没有被正确传入 `messages` / `MemorySkill` 没有加入 skill 列表 |
| 记忆混乱、答非所问 | `memory.add` 的顺序写反了（user/assistant 顺序错误） |
| 情绪从不切换 | `EmotionSkill` 没有加入 skill 列表 / 关键词表未命中 |
| 情绪切换太频繁 | 缺少"惯性"逻辑，每句话都在重置状态 |
| token 超限报错 | `max_turns` 设太大，或检索结果 + 历史 + system prompt 合计超了模型上限 |
| `/reset` 后仍然记得历史 | `agent.reset()` 没有同时调 `memory.clear()` |

---

## 完成 Phase 2 的判定

满足以下四条就算 Phase 2 done：

- [ ] 连续对话 5 轮以上，第 5 轮能正确引用第 2 轮的内容。
- [ ] 提到钢琴/茶/猫，情绪切换为 PLEASED；提到家族/祖父，切换为 COLD；平淡话题回归 CALM。
- [ ] `/reset` 命令能清空记忆和情绪，下一轮回到初始状态。
- [ ] 对知识库文档切块后，每块开头带标题，结尾是完整句子，不从词语中间截断。
- [ ] 查询"《春日影》是谁写的"，检索 top-1 命中包含春日影的 chunk，得分高于纯向量检索。

完成后回到 README 把 Phase 2 状态从 ⏳ 改成 ✅，然后我们再聊 Phase 3。
