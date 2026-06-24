# Phase 1 手把手搭建教程

> 目标：从空仓库出发，用大约 200 行 Python 写出一个**会用猫人设回答问题**的本地 RAG demo。
>
> 这份教程**只给思路、接口和自检清单，不给完整实现**。每一步留给你自己写。

---

## 你需要先有的认知

- **RAG 三件事**：把文档切成块 → 把块变成向量 → 提问时找最近的几块塞进 prompt。
- **Embedding** = 把一段文字变成一个固定长度的向量（比如 1536 维）。语义相近的文字，向量在空间里也靠近。
- **余弦相似度** = 两个向量夹角的 cos 值。值越接近 1，越相似。
- **为什么不用 LangChain**：因为上面这三件事各自只要 10~30 行 Python，框架反而把你和「真正在发生什么」隔开。Phase 1 就是要把这层窗户纸捅破。

如果上面任何一条你觉得模糊，**先去查清楚再继续**，不然后面每一步都会卡。

---

## 总览：你要建的 11 个组件

按依赖顺序排列。**不要跳着写**，每一步都依赖前一步。

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| 0 | `.env` / `requirements.txt` | 准备环境 |
| 1 | `animate/config.py` | LLM / embedding 单一入口 |
| 2 | `animate/rag/embedder.py` | 把文本变成向量 |
| 3 | `animate/rag/loader.py` | 读 `data/*.md`，切块 |
| 4 | `animate/rag/store.py` | 内存向量库 + 余弦检索 |
| 5 | `python -m animate.rag.loader` | 把 3+4 串起来，生成 `data/index.pkl` |
| 6 | `animate/skills/base.py` | Skill 基类 |
| 7 | `animate/skills/retrieval.py` | RAG 检索 skill |
| 8 | `animate/skills/persona.py` | 猫人设包装 skill |
| 9 | `animate/agent.py` | 把 skill 串起来跑一轮对话 |
| 10 | `animate/cli.py` | 命令行 REPL |
| 11 | 跑通 & 调优 | 改 prompt、调 top-k、看 bug |

---

## Step 0 · 准备环境

**你要做的：**

1. 在仓库根目录建 `requirements.txt`，先只列三样：
   - `openai` 或 `dashscope`（按你买了哪个 API 决定）
   - `numpy`
   - `python-dotenv`
2. 建 `.env.example`，写出占位的 `OPENAI_API_KEY=` 或 `DASHSCOPE_API_KEY=`。
3. 复制成 `.env`，把真 key 填进去。**`.env` 已经在 `.gitignore` 里**，确认一下不会被提交。
4. `pip install -r requirements.txt`。

**自检：** `python -c "import openai, numpy, dotenv; print('ok')"` 不报错。

---

## Step 1 · `animate/config.py` — 单一入口

**为什么有这个文件**：以后可能换 provider（OpenAI ↔ DashScope），可能改模型名。如果到处 `import openai`，迁移就是噩梦。所有外部调用必须从这里出。

**你要导出的接口（只看签名，自己实现）：**

```python
def get_llm_client(): ...        # 返回一个能调 chat completion 的对象
def get_embedding_client(): ...  # 返回一个能调 embedding 的对象
def llm_model_name() -> str: ...
def embedding_model_name() -> str: ...
```

**思路：**
- 在文件顶用 `dotenv.load_dotenv()` 把 `.env` 读进来。
- 用一个环境变量 `ANIMATE_PROVIDER`（值为 `openai` 或 `dashscope`）控制返回哪个 client。
- 模型名也走环境变量，给默认值，比如 `ANIMATE_LLM_MODEL=gpt-4o-mini`。

**自检：**
- `from animate.config import get_llm_client; c = get_llm_client()` 能拿到对象。
- 整个仓库里**只有这个文件 import openai/dashscope**。后面写其他文件时，回头检查这条。

---

## Step 2 · `animate/rag/embedder.py` — 文本 → 向量

**接口：**

```python
def embed(texts: list[str]) -> np.ndarray: ...
# 输入 N 条文本，输出 shape=(N, dim) 的 float32 数组
```

**思路：**
- 调 `get_embedding_client()` 拿 client，调它的 embeddings 接口。
- 注意 OpenAI 一次最多支持几千条（看文档），DashScope 限制更严，**写一个 batch_size 循环**，比如 64 一批。
- 返回前用 `np.array(..., dtype=np.float32)`。

**自检：**
- `embed(["hello", "world"]).shape` 应该是 `(2, 1536)` 之类。
- 同一句话调两次，向量应该完全相同（embedding API 是确定性的）。

---

## Step 3 · `animate/rag/loader.py` — 读文档、切块

**这一步做两件事：**

### 3a. 读 `data/` 下所有 `.md` / `.txt`

```python
def load_documents(data_dir: Path) -> list[tuple[str, str]]: ...
# 返回 [(文件名, 全文), ...]
```

`pathlib.Path(data_dir).rglob("*.md")` 即可。

### 3b. 切块

```python
def chunk_text(text: str, max_chars: int = 600, overlap: int = 80) -> list[str]: ...
```

**朴素切法（够用）：**
1. 先按空行 `\n\n` 切成段落。
2. 累积段落直到长度逼近 `max_chars`，作为一块。
3. 下一块的开头复制上一块末尾 `overlap` 个字符（避免边界处把语义切断）。

**为什么不用 token 切**：因为还要装个 tokenizer，复杂度暴涨。Demo 阶段按字符近似就行。

**自检：**
- 给 1500 字符的文本，应切出 ~3 块。
- 相邻两块拼接时，去掉 overlap 应能还原原文。

---

## Step 4 · `animate/rag/store.py` — 向量库

**接口：**

```python
class VectorStore:
    def __init__(self): ...
    def add(self, chunks: list[str], vectors: np.ndarray) -> None: ...
    def search(self, query_vec: np.ndarray, top_k: int = 4) -> list[tuple[str, float]]: ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "VectorStore": ...
```

**思路：**
- 内部维护两个东西：`self.chunks: list[str]` 和 `self.vectors: np.ndarray`（shape `(N, dim)`）。
- `search` 的核心一行：
  ```python
  scores = (self.vectors @ query_vec) / (norms_v * norm_q)
  ```
  也就是矩阵乘法直接算所有 chunk 的 cos 相似度。归一化只是除以模长。
- `save` / `load` 直接 `pickle.dump((self.chunks, self.vectors), f)`。Demo 阶段够用。

**自检：**
- 加 5 条 chunk，搜索其中一条的原文，top-1 得分应 ≈ 1.0 且就是它自己。
- 保存后 load 回来，搜索结果和保存前一致。

---

## Step 5 · 串起来：`python -m animate.rag.loader`

在 `loader.py` 末尾加一个 `if __name__ == "__main__":` 块：

1. `load_documents("data/")` → 拿到 `(filename, text)` 列表
2. 对每个 text 调 `chunk_text` → 全部 chunk 平铺成一个大 list
3. `embed(chunks)` → 拿到向量
4. `VectorStore().add(chunks, vectors).save("data/index.pkl")`

**自检：** 跑完命令行后，`data/index.pkl` 文件应该出现，大小几十 KB ~ 几 MB。

⚠️ **这一步会真消耗 API 额度**。先放一篇短文章测试，再喂全量。

---

## Step 6 · `animate/skills/base.py` — Skill 基类

**为什么要基类**：以后 Phase 2 加更多 skill（记忆、情绪、工具调用），需要统一接口。Phase 1 一次定型。

**接口：**

```python
@dataclass
class SkillContext:
    user_input: str
    retrieved_chunks: list[str] = field(default_factory=list)
    system_prompt_parts: list[str] = field(default_factory=list)
    # 后续 Phase 可以往这里加字段，不影响已有 skill

class Skill(ABC):
    name: str
    @abstractmethod
    def run(self, ctx: SkillContext) -> SkillContext: ...
```

**思路：**
- `SkillContext` 是流过所有 skill 的「公文包」。每个 skill 拿到它，**修改它**，传给下一个。
- 不让 skill 直接调 LLM —— LLM 调用统一放在 `agent.py` 里，避免每个 skill 都自己调一次。

**自检：** 写一个 `EchoSkill` 把 `user_input` 抄到 `system_prompt_parts` 里，确认基类逻辑通畅。

---

## Step 7 · `animate/skills/retrieval.py` — RAG 检索 skill

```python
class RetrievalSkill(Skill):
    name = "retrieval"
    def __init__(self, store: VectorStore, top_k: int = 4): ...
    def run(self, ctx: SkillContext) -> SkillContext:
        # 1. embed(ctx.user_input)
        # 2. store.search(...)
        # 3. ctx.retrieved_chunks = [chunk for chunk, score in results]
        # 4. 把 chunks 拼成一段「相关知识」附加到 ctx.system_prompt_parts
```

**关键决策：**
- 拼接时给每块加个分隔符，比如 `--- 知识片段 1 ---\n{chunk}\n`，让 LLM 知道这是检索结果不是用户输入。
- 不要把 score 给 LLM 看，没意义还干扰。

**自检：** 单独跑这个 skill，给一个跟猫相关的问题，`ctx.retrieved_chunks` 里应该确实是猫相关的内容。

---

## Step 8 · `animate/skills/persona.py` — 猫人设包装

**先建 `prompts/cat_persona.txt`**，里面写人设，比如：

```
你是一只名叫"咕咕"的橘猫，性格慵懒但礼貌。
回答问题时：
- 自称"咱"
- 句末偶尔加"喵"，但不要每句都加
- 对鱼类、晒太阳、纸箱话题表现出额外兴趣
- 事实必须正确；如果检索结果里没有答案，就如实说"咱不知道"，不要瞎编
```

**Skill 实现思路：**

```python
class PersonaSkill(Skill):
    name = "persona"
    def __init__(self, persona_path: Path): ...  # 在 __init__ 里读文件，存到 self.persona_text
    def run(self, ctx: SkillContext) -> SkillContext:
        # 把 self.persona_text 插到 ctx.system_prompt_parts 的最前面
```

**关键决策：** persona 必须放在 system prompt **最前**，知识检索结果在后。LLM 对开头的指令更敏感。

---

## Step 9 · `animate/agent.py` — 编排器

**这是把所有 skill 串起来跑一轮对话的地方。**

```python
class Agent:
    def __init__(self, skills: list[Skill]): ...
    def chat(self, user_input: str) -> str:
        # 1. ctx = SkillContext(user_input=user_input)
        # 2. for skill in self.skills: ctx = skill.run(ctx)
        # 3. system_prompt = "\n\n".join(ctx.system_prompt_parts)
        # 4. 调 get_llm_client().chat.completions.create(
        #        model=llm_model_name(),
        #        messages=[
        #            {"role": "system", "content": system_prompt},
        #            {"role": "user", "content": user_input},
        #        ],
        #    )
        # 5. 返回 response.choices[0].message.content
```

**关键决策：**
- skill 的执行顺序是 `[PersonaSkill, RetrievalSkill]`。persona 在前，检索补充在后。
- 不在这里做多轮历史 —— Phase 1 是单轮。

**自检：** 写个 5 行的临时脚本，构造 Agent 调一次 `chat("猫为什么爱吃鱼？")`，应该能拿到一段带猫语气的回答。

---

## Step 10 · `animate/cli.py` — REPL

```python
def main():
    # 1. 加载 VectorStore.load("data/index.pkl")
    # 2. 实例化 PersonaSkill, RetrievalSkill
    # 3. agent = Agent([persona, retrieval])
    # 4. while True:
    #        line = input("> ")
    #        if line in {"exit", "quit"}: break
    #        print("🐱", agent.chat(line))

if __name__ == "__main__":
    main()
```

加个 `try/except KeyboardInterrupt` 让 Ctrl-C 优雅退出。

---

## Step 11 · 跑通后会想做的事

按重要性排序：

1. **看 prompt 对不对**：在 `agent.chat` 里临时 `print(system_prompt)`，确认 persona 在前、知识片段在后、格式干净。
2. **检索准不准**：拿你知道答案在哪一块的 query 去试，看 top-1 是不是那一块。不准就调 chunk 大小 / overlap。
3. **猫味够不够**：如果回答太干，加强 persona 文件里的语气示例（few-shot）。
4. **省钱**：embedding 缓存 —— 同一段 chunk 不要每次跑 loader 都重新 embed。可以在 `index.pkl` 里也存一份 chunk → vector 的映射，下次 loader 时复用。
5. **错答处理**：检索 top-k 的最高分如果低于某阈值（比如 0.3），就让 persona 说"咱不知道"，不要让 LLM 瞎编。

---

## 卡住时的诊断顺序

| 症状 | 先怀疑 |
| --- | --- |
| 回答完全没猫味 | persona 文件没读到 / system prompt 拼接顺序反了 |
| 回答里没用到知识库 | retrieval skill 没跑 / chunk 拼接没进 system prompt |
| 检索出来的 chunk 不相关 | embedding model 不一致（建索引和查询用了不同模型）|
| `top-1` 自查得分不到 1.0 | 向量没归一化或归一化错了 |
| API 报 rate limit | 把 batch_size 调小、loader 加 sleep |
| 启动慢 | `index.pkl` 没建好 / 每次都重新 embed 了 |

---

## 完成 Phase 1 的判定

满足以下三条就算 Phase 1 done：

- [ ] `python -m animate.cli` 能进 REPL，输入"猫为什么爱吃鱼"等问题，给出带猫人设的回答。
- [ ] 回答内容与 `data/cat_knowledge.md` 中的事实一致。
- [ ] 整个仓库 `grep -r "import openai\|import dashscope"` 只在 `animate/config.py` 和 `animate/rag/embedder.py` 出现。

完成后回到 README 把 Phase 1 状态从 🚧 改成 ✅，然后我们再聊 Phase 2。
