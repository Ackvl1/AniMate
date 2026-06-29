"""Agent — 图引擎门面（完整版），替代旧的线性 Agent"""

from __future__ import annotations

import asyncio
import traceback
from typing import AsyncGenerator

from anima.core.engine.graph import Graph, GraphEngine
from anima.core.engine.context import RunContext
from anima.core.engine.node import NodeResult, AgentEvent
from anima.core.agent.nodes import ReactNode, AfterNode, ReflectNode
from anima.core.agent.nodes.rag_vector import RAGVectorNode
from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
from anima.core.agent.nodes.system_prompt import SystemPromptNode
from anima.core.agent.nodes.merge import MergeNode
from anima.core.agent.response import AgentResponse
from anima.core.tools.registry import ToolRegistry
from anima.core.tools.function.memory_tools import MemoryProviderToolWrapper
from anima.core.agent.logging import PhaseEventLogger
from anima.core.log import setup_logger, ChatLogDB

logger = setup_logger(__name__)


from anima.core.config import get_agent_config
MAX_GRAPH_STEPS = get_agent_config()["max_graph_steps"]


class Agent:
    """Anima Agent 内核门面。使用图引擎驱动 4-Phase Pipeline。

    职责：
      - 管理 Graph 构造 + GraphEngine 调度
      - 跨轮次的对话消息（self._messages）和日志持久化
      - chat() 同步接口 + chat_stream() 异步流式接口
      - 错误兜底：任何节点抛异常都返回保底回复
    """

    def __init__(
        self,
        llm,
        persona: str,
        vector_store,
        keyword_store,
        tools: ToolRegistry | None = None,
        mcp_clients: list | None = None,
        log_db: ChatLogDB | None = None,
        fact_llm=None,
        permission_manager=None,
        memory_provider=None,
        session_store=None,
    ):
        import uuid as _uuid

        self._llm = llm
        self._fact_llm = fact_llm
        self._persona = persona
        self._vector_store = vector_store
        self._keyword_store = keyword_store
        self._tools = tools or ToolRegistry()
        self._mcp_clients = mcp_clients or []
        self._log_db = log_db
        # 审计日志收集器（延迟初始化）
        self._log_collector = None

        self._permission_manager = permission_manager
        self._memory_provider = memory_provider
        self._phase_logger: PhaseEventLogger | None = None
        self._messages: list[dict] = []

        # Session store + rotation
        self._session_store = session_store
        self._diff_history = None  # DiffHistory 单例，跨 chat 复用
        self._session_id: str = str(_uuid.uuid4())[:8]
        if self._session_store:
            self._session_store.init_session(self._session_id, [])

        # Context manager (token tracking + compression)
        from anima.core.context.manager import ContextManager
        self._ctx_mgr = ContextManager(llm=self._llm, session_store=self._session_store)

        # Register memory tools（去重：同一 ToolRegistry 不重复注册）
        if self._memory_provider:
            for schema in self._memory_provider.get_tool_schemas():
                if self._tools.find(schema["name"]) is None:
                    self._tools.register_tool(MemoryProviderToolWrapper(schema, self._memory_provider))

        # Register session search tool（允许 LLM 检索历史对话）
        if self._session_store:
            from anima.core.tools.function.memory_tools import SessionSearchTool
            if self._tools.find("session_search") is None:
                self._tools.register_tool(
                    SessionSearchTool(self._session_store, self._session_id)
                )

        self._graph = self._build_graph(llm, persona, vector_store, keyword_store,
                                        self._tools, permission_manager, memory_provider)

    # ── Factory ────────────────────────────────────────

    @classmethod
    def create_default(
        cls,
        llm,
        persona: str,
        vector_store,
        keyword_store,
        enable_mcp: bool = True,
        permission_manager=None,
        log_db=None,
        memory_provider=None,
        session_store=None,
    ) -> "Agent":
        """工厂方法：创建标准 Agent 实例（注册 11 个内置工具）。"""
        try:
            from anima.core.tools.defaults import register_default_tools
            tools, mcp_clients = register_default_tools(enable_mcp=enable_mcp)
        except Exception:
            logger.warning("create_default: 工具注册失败，使用空工具集")
            tools, mcp_clients = None, None
        return cls(
            llm=llm,
            persona=persona,
            vector_store=vector_store,
            keyword_store=keyword_store,
            tools=tools,
            mcp_clients=mcp_clients,
            permission_manager=permission_manager,
            log_db=log_db,
            memory_provider=memory_provider,
            session_store=session_store,
        )

    # ── 属性 ───────────────────────────────────────────

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    # ── 图构造 ─────────────────────────────────────────

    @staticmethod
    def _build_graph(llm, persona, vector_store, keyword_store, tools,
                     permission_manager=None, memory_provider=None) -> Graph:
        """构造 Pipeline 图。

        __entry__ → MemoryNode → fan_out → [SystemPrompt, RAGVector, RAGKeyword]
                  → join → MergeNode → ReactNode → AfterNode → ReflectNode
        """
        g = Graph()

        g.add_node("rag_vector", RAGVectorNode(vector_store))
        g.add_node("rag_keyword", RAGKeywordNode(keyword_store))
        g.add_node("system_prompt", SystemPromptNode(persona))
        g.add_node("merge", MergeNode())

        g.add_node("react", ReactNode(llm, tools, permission_manager=permission_manager))
        g.add_node("after", AfterNode())
        g.add_node("reflect", ReflectNode(llm))

        # MemoryNode（长期记忆检索，在 fan_out 前面串行）
        if memory_provider:
            from anima.core.agent.nodes.memory_node import MemoryNode
            g.add_node("memory", MemoryNode(memory_provider))
            g.add_edge("__entry__", "memory")
            g.add_fan_out("memory", ["rag_vector", "rag_keyword", "system_prompt"])
        else:
            g.add_fan_out("__entry__", ["rag_vector", "rag_keyword", "system_prompt"])
        g.add_join(["rag_vector", "rag_keyword", "system_prompt"], "merge")

        g.add_edge("merge", "react")
        g.add_edge("react", "after")
        g.add_edge("after", "reflect")

        def reflect_router(result: NodeResult) -> str | None:
            return result.next_node

        g.add_conditional_edge("reflect", reflect_router, {
            "before": "memory" if memory_provider else "__entry__",
            "react": "react",
            None: None,
        })

        g.set_entry("__entry__")
        return g

    def build_graph(self) -> Graph:
        """返回底层图引用（供外部扩展/检验）。"""
        return self._graph

    # ── 压缩 / 恢复 ──────────────────────────────────

    def compact(self) -> dict:
        """手动触发压缩。始终尝试压缩，不检查阈值。"""
        # 前置检查：消息轮数过少时明确返回 skip，而非模糊的 error
        head_rounds = getattr(self._ctx_mgr, '_head_rounds', 5)
        tail_rounds = getattr(self._ctx_mgr, '_tail_rounds', 10)
        min_needed = (head_rounds + tail_rounds) * 2
        if len(self._messages) < min_needed:
            return {
                "status": "skip",
                "message": f"消息轮数过少（{len(self._messages)} < {min_needed}），跳过压缩",
                "compress_count": self._ctx_mgr._compress_count,
            }

        import uuid as _uuid2
        _trace_id = _uuid2.uuid4().hex[:8]
        old_sid = self._session_id

        try:
            new_sid = self._ctx_mgr.compress(
                self._messages, session_id=self._session_id
            )
            if new_sid:
                if self._memory_provider:
                    self._memory_provider.on_session_switch(
                        new_sid, self._session_id
                    )
                self._session_id = new_sid
            # 压缩审计日志（compact 是同步 CLI 调用）
            if self._log_collector:
                self._log_collector.log_compression(
                    trace_id=_trace_id,
                    compress_count=self._ctx_mgr._compress_count,
                    success=new_sid is not None,
                    old_session_id=old_sid,
                    new_session_id=new_sid or "",
                )
            if new_sid:
                return {
                    "status": "ok",
                    "message": f"压缩完成 (#{self._ctx_mgr._compress_count})",
                    "session_id": new_sid,
                    "compress_count": self._ctx_mgr._compress_count,
                }
            return {
                "status": "error",
                "message": "压缩失败（LLM 摘要异常）",
                "compress_count": self._ctx_mgr._compress_count,
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"压缩异常: {e}",
                "compress_count": self._ctx_mgr._compress_count,
            }

    def resume(self, session_id: str) -> bool:
        """恢复旧 session 的消息到当前会话。返回是否成功。"""
        if not self._session_store:
            return False
        messages = self._session_store.load(session_id)
        if not messages:
            return False
        self._messages = messages
        return True

    # ── 同步接口 ───────────────────────────────────────

    def chat(self, user_input: str) -> AgentResponse:
        """同步调用。阻塞直到整个 Pipeline 完成，返回 AgentResponse。

        内部委托给 chat_stream() 并聚合最终事件。
        任何异常都返回兜底回复，不会传出去。
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                final_text = ""
                emotion = ""
                gesture = None

                async def run():
                    nonlocal final_text, emotion, gesture
                    async for event in self.chat_stream(user_input):
                        if event.type == "done":
                            final_text = event.data.get("text", "")
                            emotion = event.data.get("emotion", "")
                            gesture = event.data.get("gesture")

                loop.run_until_complete(run())
            finally:
                # 先取消所有挂起的 task，避免 loop.close() 时协程残留
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.close()

            return AgentResponse(text=final_text, emotion=emotion, gesture=gesture)

        except Exception:
            logger.error("Agent.chat() 异常:\n%s", traceback.format_exc())
            return AgentResponse(
                text="抱歉，我刚才走神了，能再说一遍吗？",
                emotion="confused",
                gesture="tilt_head",
            )

    # ── 流式接口 ───────────────────────────────────────

    async def chat_stream(self, user_input: str) -> AsyncGenerator[AgentEvent, None]:
        """真流式调用。引擎在后台运行，emit 实时放入 asyncio.Queue，主循环逐条 yield。

        事件类型：
          - "phase.start"   → data={phase: "before|react|after|reflect"}
          - "rag.status"    → data={status, results}
          - "text_token"    → data={text: str}
          - "tool.start"    → data={name, arguments}
          - "tool.done"     → data={name, result}
          - "reflect.result"→ data={level, feedback}
          - "done"          → data={text, emotion, gesture}
        """
        ctx = RunContext(user_input=user_input)
        ctx.services.memory = None
        ctx.services.log_db = getattr(self, '_log_db', None)

        # 从短期记忆加载历史（复制，非引用）+ 注入本轮用户输入
        ctx.messages = list(self._messages) + [
            {"role": "user", "content": user_input}
        ]

        # DiffHistory 单例（跨 chat 复用）
        if self._diff_history is None:
            from anima.core.engine.diff_history import DiffHistory
            self._diff_history = DiffHistory()

        engine = self._graph.create_engine(
            max_steps=MAX_GRAPH_STEPS,
            diff_history=self._diff_history,
        )

        # ── asyncio.Queue 桥接 emit 回调和 yield ──
        queue: asyncio.Queue = asyncio.Queue()

        # ── 日志记录器（惰性初始化） ──
        if self._phase_logger is None:
            db = self._log_db if self._log_db is not None else ChatLogDB()
            self._phase_logger = PhaseEventLogger(db)

        pl = self._phase_logger
        pl.on_chat_start(ctx.trace_id, user_input)

        # ── Pre-turn: 上下文压缩 + Session Rotation（异步，不阻塞事件循环）──
        if self._ctx_mgr.need_compress():
            session_id_before = self._session_id
            try:
                new_sid = await self._ctx_mgr.compress_async(
                    self._messages, session_id=self._session_id
                )
                if new_sid and self._memory_provider:
                    # 压缩前用完整消息做深度提取
                    self._memory_provider.on_session_end(self._messages, llm=self._llm)
                    self._memory_provider.on_session_switch(new_sid, self._session_id)
                if new_sid:
                    self._session_id = new_sid
                # 重新同步：压缩后 self._messages 已被 snip/clear 修改，需重新组合
                ctx.messages = list(self._messages) + [
                    {"role": "user", "content": user_input}
                ]
                # 压缩审计日志
                if self._log_collector:
                    self._log_collector.log_compression(
                        trace_id=ctx.trace_id,
                        compress_count=self._ctx_mgr._compress_count,
                        success=True,
                        old_session_id=session_id_before,
                        new_session_id=self._session_id,
                    )
            except Exception as e:
                logger.warning("compress_async 失败: %s", e)
                if self._log_collector:
                    self._log_collector.log_compression(
                        trace_id=ctx.trace_id,
                        compress_count=self._ctx_mgr._compress_count,
                        success=False,
                        error_msg=str(e),
                    )

        # emit 函数：节点运行时实时将事件放入 asyncio.Queue
        # 同时分派到 PhaseEventLogger（阶段日志）和 LogCollector（审计日志）
        async def emit(type: str, **data):
            ev = AgentEvent(type=type, trace_id=ctx.trace_id, **data)
            await queue.put(ev)
            pl.handle_event(type, **data)
            if self._log_collector is not None:
                self._log_collector.handle(ev)

        # 延迟初始化 LogCollector
        if self._log_collector is None and self._log_db is not None:
            from anima.core.log.collector import LogCollector
            self._log_collector = LogCollector(self._log_db)

        async def _run_engine():
            """后台任务：运行引擎，完成后通过哨兵通知。"""
            try:
                await engine.run(ctx, emit=emit)
            except Exception:
                logger.error("GraphEngine.run() 异常:\n%s", traceback.format_exc())
                await queue.put(AgentEvent(type="phase.start", phase="reflect"))
                await queue.put(AgentEvent(type="reflect.result", level=4, feedback="引擎异常，兜底"))
                ctx.final_text = "抱歉，我刚才走神了，能再说一遍吗？"
                ctx.emotion = "confused"
                ctx.gesture = "tilt_head"
                # 引擎兜底是唯一允许绕过 diff 的通道，但必须 emit final 事件
                await emit("emotion.final", value="confused")
                await emit("gesture.final", value="tilt_head")
            finally:
                await queue.put(None)  # 哨兵

        task = asyncio.create_task(_run_engine())

        try:
            # 实时逐条 yield：引擎在后台运行，emit 往 queue 放，此循环取出 yield
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield ev

            # 确保异常传播（_run_engine 已内部处理异常，正常情况无 exception）
            try:
                await task
            except Exception:
                pass
        finally:
            # 清理：如果消费者提前终止（异常/中断/GC），确保 task 和 queue 不泄漏
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            # 排空 queue，释放所有挂起的 get() 协程引用
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        # ── Post-turn: 持久化 + 轻量提取 + done ──
        try:
            pl.on_chat_end(ctx)

            final_text = ctx.final_text or ctx.raw_text or ""
            # 无条件保存 user message，避免空回复时丢失用户输入
            self._messages.append({"role": "user", "content": user_input})
            if final_text.strip():
                self._messages.append({"role": "assistant", "content": final_text})

            # 轻量 regex 提取（零 API 成本）
            try:
                if self._memory_provider:
                    self._memory_provider.sync_turn(user_input, final_text)
            except Exception:
                pass

            # token 累计（压缩触发）
            if ctx.accumulated_usage > 0:
                self._ctx_mgr.update_from_response({"total_tokens": ctx.accumulated_usage})

            # Session 持久化
            if self._session_store:
                try:
                    self._session_store.save_messages(self._session_id, self._messages)
                except Exception:
                    pass

            yield AgentEvent(
                type="done",
                text=final_text,
                emotion=ctx.emotion or "confused",
                gesture=ctx.gesture,
            )
        except Exception:
            logger.error("chat_stream: 后处理异常:\\n%s", traceback.format_exc())
            yield AgentEvent(
                type="done",
                text=ctx.final_text or ctx.raw_text or "",
                emotion=ctx.emotion or "confused",
                gesture=None,
            )

    # ── 生命周期 ───────────────────────────────────────

    def reset(self) -> None:
        """清空对话消息，冻结当前 session，创建新 session。"""
        # 提取长期记忆（会话结束时做一次深度 LLM 提取）
        if self._memory_provider:
            try:
                self._memory_provider.on_session_end(self._messages, llm=self._llm)
            except Exception:
                pass

        # 冻结当前 session
        if self._session_store:
            self._session_store.finalize(self._session_id)
            import uuid as _uuid
            self._session_id = str(_uuid.uuid4())[:8]
            self._session_store.init_session(self._session_id, [])

        self._messages.clear()
        self._ctx_mgr.reset()
        logger.info("Agent reset, new session: %s", self._session_id)

    def shutdown(self) -> None:
        """释放所有资源。退出前提取长期记忆。"""
        if self._memory_provider and self._messages:
            try:
                self._memory_provider.on_session_end(self._messages, llm=self._llm)
            except Exception:
                pass
        for client in self._mcp_clients:
            try:
                client.stop()
            except Exception:
                pass
        self._mcp_clients.clear()
        if self._session_store:
            try:
                self._session_store.close()
            except Exception:
                pass
        if self._memory_provider:
            try:
                self._memory_provider.shutdown()
            except Exception:
                pass
        if self._phase_logger:
            try:
                self._phase_logger._db.close()
            except Exception:
                pass
        if self._log_collector:
            self._log_collector = None
        if self._diff_history:
            try:
                self._diff_history.close()
            except Exception:
                pass
