---
name: animate-dev
description: Use this skill when working on the AniMate Animal Character Agent repo. Covers Phase 1 conventions — pure OpenAI/DashScope SDK (no LangChain/LlamaIndex/Chroma/FAISS), self-built numpy cosine-similarity vector store, single cat persona loaded from prompts/cat_persona.txt, and the two-layer "skill" distinction (animate/skills/ for runtime agent capabilities vs .claude/skills/ for IDE assistance). Trigger when editing animate/, data/, prompts/, or answering questions about RAG retrieval, the cat persona, or how to add a new agent capability in this repo.
---

# AniMate Development Skill

Conventions for working on the **AniMate Animal Character Agent** project. Read this before adding code or proposing architecture changes.

## Project state

- **Phase 1 only**: simple RAG Q&A demo. A single cat character. CLI interface. No memory, no emotions, no tool use.
- Anything beyond Phase 1 (multi-turn memory, emotion state machine, multi-animal switching, TTS / Live2D) is **out of scope** — note it in README's roadmap, don't implement it.

## Hard rules — do not violate

1. **No RAG frameworks.** Don't add `langchain`, `llama-index`, `chromadb`, `faiss-cpu`, `qdrant-client`, etc. The whole point of Phase 1 is to keep retrieval transparent. The vector store is `numpy` arrays + cosine similarity, persisted via `pickle` to `data/index.pkl`.
2. **Single LLM/embedding entry point.** All LLM calls go through `animate.config.get_llm_client()`. All embedding calls go through `animate.rag.embedder.embed()`. Do **not** `import openai` or `import dashscope` from business code (agent / skills / cli).
3. **Persona lives in `prompts/cat_persona.txt`.** Do not hardcode the cat's voice into Python strings. The `persona` skill loads the file at runtime.
4. **Two skill layers, don't conflate them:**
   - `animate/skills/` = **runtime capabilities** the agent uses to answer (Python classes inheriting `Skill`).
   - `.claude/skills/` = **IDE helpers** (this file). Has nothing to do with runtime.
5. **No secrets in code or commits.** API keys come from `.env` (gitignored). Add new config keys to `.env.example` with placeholder values.

## Where things go

| Adding... | Put it in... |
| --- | --- |
| A new agent capability (e.g. summarize, translate) | New file under `animate/skills/`, subclass `Skill`, register in `animate/skills/__init__.py` |
| A new knowledge file for the cat | `data/*.md` — then re-run `python -m animate.rag.loader` |
| A change to how documents are chunked | `animate/rag/loader.py` |
| A change to how vectors are scored | `animate/rag/store.py` |
| A new LLM provider | `animate/config.py` (extend `get_llm_client()` switch) + `animate/rag/embedder.py` |
| Persona tweaks | `prompts/cat_persona.txt` (not Python) |

## Style

- Python 3.10+. Type hints on public functions. `from __future__ import annotations` at file top.
- Async is **not** required for Phase 1 — the CLI is synchronous, keep it simple.
- Logging via `logging.getLogger(__name__)`, not `print` (except inside `cli.py` for user-facing output).
- Tests under `tests/`, use `pytest`. The retrieval logic should have tests with a tiny fixture corpus.

## Common pitfalls to flag in review

- Someone reaching for LangChain "just for the splitter" → reject, write a 20-line splitter.
- Persona text leaking into agent.py → move it to the prompt file.
- `os.getenv("OPENAI_API_KEY")` scattered across files → consolidate in `config.py`.
- A new "skill" added under `animate/skills/` without subclassing `Skill` or being registered → fix.
- README roadmap claiming Phase 2 features as done → revert.

## When the user asks "how do I add X?"

1. Check the table above — most additions have a designated file.
2. If X is a new capability the agent should use at runtime → it's a `Skill` subclass.
3. If X is a development workflow / lint rule / dependency policy → update **this file**, not the README.
4. If X requires breaking a hard rule above, push back and ask the user to confirm they want to leave Phase 1 territory.
