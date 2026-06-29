"""Anima Agent CLI — 命令系统 + 调试模式 + 模型切换（图引擎版）"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from pathlib import Path

from anima.core.agent import Agent, AgentResponse
from anima.core.llm import OpenAICompatibleClient, find_provider_by_model
from anima.core.config import LLM_CATALOG
from anima.core.log.logger import set_log_level
from anima.core.log.log_db import ChatLogDB
from anima.core.agent import PermissionManager
from anima.io.Console import ConsoleInput, ConsoleOutput

emotion_icons = {
    "calm": "😶", "pleased": "🌸", "cold": "❄️",
    "happy": "😊", "sad": "😢", "angry": "😠",
    "surprised": "😲", "confused": "🤔", "excited": "🎉",
}


def format_debug(response: AgentResponse) -> str:
    """格式化调试输出。"""
    lines = []
    lines.append("── 调试信息 ──")
    emotion = response.emotion or "?"
    lines.append(f"情绪: {emotion}")
    if response.gesture:
        lines.append(f"姿势: {response.gesture}")
    lines.append("──────────────")
    return "\n".join(lines)


def handle_model_command(parts: list[str], llm: OpenAICompatibleClient,
                          agent=None) -> bool:
    """处理 /model 命令。返回 True 表示命令已处理。"""
    if len(parts) > 1 and parts[1] == "list":
        current_provider = find_provider_by_model(llm._model)
        for key, info in LLM_CATALOG.items():
            models_str = ", ".join(info["models"])
            marker = " ← 当前" if key == current_provider else ""
            print(f"  {info['name']}: {models_str}{marker}")
        return True

    if len(parts) > 1:
        target = parts[1]
        result = llm.switch_provider(target)
        if result:
            print(f"✅ 已切换到 {result}")
            # 同步更新压缩阈值以适应新模型的上下文窗口
            if agent is not None and hasattr(llm, "_provider_config") and llm._provider_config:
                agent._ctx_mgr.reconfigure(model_limit=llm._provider_config.default_context_length)
        else:
            provider = find_provider_by_model(target)
            if not provider:
                provider = target if target in LLM_CATALOG else None
            if provider and provider in LLM_CATALOG:
                env = LLM_CATALOG[provider]["api_key_env"]
                name = LLM_CATALOG[provider]["name"]
                print(f"⚠ {env} 未配置，无法切换到 {name}。请在 .env 中设置后重启。")
            else:
                print(f"⚠ 未知模型或厂商: {target}")
        return True

    # /model 无参数 — 交互式选择
    print(f"当前模型: {llm._model}")

    providers = list(LLM_CATALOG.items())
    current_provider = find_provider_by_model(llm._model)

    print("选择厂商：")
    for i, (key, info) in enumerate(providers, 1):
        marker = " ← 当前" if key == current_provider else ""
        print(f"  {i}) {info['name']}{marker}")
    print(f"  0) 返回")

    while True:
        try:
            choice = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return True
        if choice == "0" or choice == "":
            return True
        if choice.isdigit() and 1 <= int(choice) <= len(providers):
            break
        print(f"无效输入，请输入 0-{len(providers)}")

    selected_key, selected_info = providers[int(choice) - 1]

    models = selected_info["models"]
    is_current_provider = (current_provider == selected_key)

    print(f"\n{selected_info['name']} — 选择模型：")
    for i, model in enumerate(models, 1):
        marker = " ← 当前" if is_current_provider and model == llm._model else ""
        print(f"  {i}) {model}{marker}")
    print(f"  0) 返回")

    while True:
        try:
            choice = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return True
        if choice == "0" or choice == "":
            return True
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            break
        print(f"无效输入，请输入 0-{len(models)}")

    target_model = models[int(choice) - 1]
    result = llm.switch_provider(target_model)
    if result:
        print(f"✅ 已切换到 {result}")
    else:
        env = selected_info["api_key_env"]
        print(f"⚠ {env} 未配置，无法切换到 {selected_info['name']}。请在 .env 中设置后重启。")

    return True


def handle_log_command(parts: list[str], log_db: ChatLogDB) -> bool:
    """处理 /log 子命令。返回 True 表示命令已处理。"""
    sub = parts[0].lower() if parts else ""

    if sub == "chat":
        limit = 10
        if len(parts) > 1 and parts[1].isdigit():
            limit = int(parts[1])
        rows = log_db.query(limit=limit)
        if not rows:
            print("📭 暂无聊天记录。")
            return True
        print(f"📋 最近 {min(limit, len(rows))} 条聊天记录：")
        print(f"  {'ID':>3} │ {'时间':<19} │ {'情绪':<6} │ {'耗时':>6} │ {'LLM调用':>7} │ {'输入'}")
        print("  " + "─" * 80)
        for r in reversed(rows):
            ts = r["created_at"][:19] if r["created_at"] else ""
            dur = f"{r['total_duration_ms'] / 1000:.1f}s" if r["total_duration_ms"] else "-"
            inp = r["user_input"][:40] + "…" if len(r["user_input"]) > 40 else r["user_input"]
            print(f"  {r['id']:>3} │ {ts:<19} │ {r['emotion'] or '-':<6} │ {dur:>6} │ {r['llm_call_count']:>7} │ {inp}")
        return True

    if sub == "phase":
        if len(parts) < 2:
            print("用法: /log phase <trace_id>")
            return True
        trace_id = parts[1]
        rows = log_db.query_phases(trace_id=trace_id)
        if not rows:
            print(f"📭 未找到 trace 为「{trace_id}」的阶段记录。")
            return True
        print(f"📋 trace「{trace_id}」的阶段事件：")
        print(f"  {'阶段':<8} │ {'耗时(ms)':>8} │ {'状态':<8} │ {'输入摘要'}")
        print("  " + "─" * 60)
        for r in rows:
            inp = r["input_summary"][:30] + "…" if len(r["input_summary"]) > 30 else r["input_summary"]
            print(f"  {r['phase_name']:<8} │ {r['duration_ms']:>8} │ {r['status']:<8} │ {inp}")
        return True

    if sub == "facts":
        limit = 20
        if len(parts) > 1 and parts[1].isdigit():
            limit = int(parts[1])
        rows = log_db.query_facts(limit=limit)
        if not rows:
            print("📭 暂无长期记忆。")
            return True
        print(f"🧠 长期记忆（共 {log_db.count_facts()} 条）：")
        for r in rows:
            print(f"  [{r['id']}] {r['fact_text']}")
            print(f"      来源: {r['source_trace'][:30]} | {r['created_at'][:19]}")
        return True

    if sub == "session":
        # /log session 或 /log session <id>
        if len(parts) > 1 and parts[1]:
            sid = parts[1]
            # 查看指定 session 详情
            rows = log_db.query(trace_id=sid, limit=5)
            if not rows:
                print(f"📭 未找到 trace 为「{sid}」的记录。")
                return True
            print(f"📋 trace「{sid}」的聊天记录：")
            for r in rows:
                print(f"  [{r['id']}] {r['created_at'][:19]} | {r['emotion'] or '-'} | {r['response_text'][:60]}…")
        else:
            # 列出所有 session
            try:
                sessions = agent._session_store.list_sessions()
            except Exception:
                print("⚠ 无法加载 session 数据库。")
                return True
            if not sessions:
                print("📭 无可用 session。")
                return True
            print(f"📋 所有会话（共 {len(sessions)} 个）：")
            print(f"  {'Session ID':<16} │ {'状态':<6} │ {'消息数':>6} │ {'创建时间':<19}")
            print("  " + "─" * 55)
            for s in sessions:
                sid = s["session_id"]
                status = "活跃" if s["active"] else "已冻结"
                msg_count = len(json.loads(s["messages"])) if s["messages"] else 0
                ts = s["created_at"][:19] if s["created_at"] else ""
                print(f"  {sid:<16} │ {status:<6} │ {msg_count:>6} │ {ts:<19}")
        return True

    if sub == "tool":
        limit = 10
        if len(parts) > 1 and parts[1].isdigit():
            limit = int(parts[1])
        rows = log_db.query_tool_audit(limit=limit)
        if not rows:
            print("📭 暂无工具调用记录。")
            return True
        print(f"🔧 最近 {min(limit, len(rows))} 条工具调用：")
        print(f"  {'ID':>3} │ {'工具名':<20} │ {'耗时':>6} │ {'HITL':<6} │ {'状态':<6}")
        print("  " + "─" * 60)
        for r in reversed(rows):
            dur = f"{r['duration_ms']}ms" if r["duration_ms"] else "-"
            print(f"  {r['id']:>3} │ {r['tool_name']:<20} │ {dur:>6} │ {r['hitl_status']:<6} │ {r['status']:<6}")
        return True

    if sub == "compression":
        limit = 10
        if len(parts) > 1 and parts[1].isdigit():
            limit = int(parts[1])
        rows = log_db.query_compression(limit=limit)
        if not rows:
            print("📭 暂无压缩记录。")
            return True
        print(f"🗜️ 最近 {min(limit, len(rows))} 条压缩记录：")
        print(f"  {'ID':>3} │ {'成功':<4} │ {'前tokens':>8} │ {'后tokens':>8} │ {'Session':<16}")
        print("  " + "─" * 55)
        for r in reversed(rows):
            ok = "✅" if r["success"] else "❌"
            print(f"  {r['id']:>3} │ {ok:<4} │ {r['before_tokens']:>8} │ {r['after_tokens']:>8} │ {r['new_session_id']:<16}")
        return True

    if sub == "clear":
        log_db.clear()
        log_db.clear_phases()
        log_db.clear_facts()
        print("✅ 所有日志数据已清空。")
        return True

    print(f"❓ 未知子命令: /log {sub}。可用: chat, phase <trace_id>, facts, clear")
    return True


def handle_command(line: str, agent: Agent, llm: OpenAICompatibleClient,
                   debug: list[bool], log_db: ChatLogDB | None = None) -> bool:
    """处理 CLI 命令。返回 False 表示退出。"""
    try:
        parts = shlex.split(line)
    except ValueError:
        return True
    cmd = parts[0].lower()

    if cmd == "/reset":
        agent.reset()
        print("（对话记忆已清空）")
        return True

    if cmd == "/debug":
        if len(parts) > 1 and parts[1] == "verbose":
            debug[1] = True
            debug[0] = True
            set_log_level(logging.DEBUG)
            print("详细调试模式：开启（完整输出 + 调试日志）")
        elif debug[0]:
            debug[0] = False
            debug[1] = False
            set_log_level(logging.WARNING)
            print("调试模式：关闭")
        else:
            debug[0] = True
            set_log_level(logging.INFO)
            print("调试模式：开启（阶段事件日志）")
        return True

    if cmd == "/model":
        return handle_model_command(parts, llm, agent=agent)

    if cmd == "/log":
        if log_db is None:
            print("⚠ 日志系统未启用。")
            return True
        return handle_log_command(parts[1:], log_db)

    if cmd == "/compact":
        result = agent.compact()
        status = result["status"]
        if status == "ok":
            print(f"🗜️ {result['message']}")
        elif status == "skip":
            print(f"⏭ {result['message']}")
        else:
            print(f"⚠ {result['message']}")
        return True

    if cmd == "/resume":
        if not agent._session_store:
            print("⚠ Session 管理未启用。")
            return True
        if len(parts) > 1:
            sid = parts[1]
            ok = agent.resume(sid)
            print(f"✅ 已恢复 session {sid}" if ok else f"⚠ 未找到 session {sid}")
        else:
            sessions = agent._session_store.list_sessions()
            if not sessions:
                print("📭 无可用 session。")
                return True
            print(f"📋 可恢复的会话（共 {len(sessions)} 个）：")
            print(f"  {'#':>3} │ {'Session ID':<16} │ {'状态':<6} │ {'消息数':>6} │ {'创建时间':<19}")
            print("  " + "─" * 60)
            for i, s in enumerate(sessions, 1):
                sid = s["session_id"]
                status = "活跃" if s["active"] else "已冻结"
                msg_count = len(json.loads(s["messages"])) if s["messages"] else 0
                ts = s["created_at"][:19] if s["created_at"] else ""
                print(f"  {i:>3} │ {sid:<16} │ {status:<6} │ {msg_count:>6} │ {ts:<19}")
            print("\n选择 (输入编号，或 0 返回):")
            try:
                choice = input("> ").strip()
                if choice == "0" or choice == "":
                    return True
                idx = int(choice) - 1
                if 0 <= idx < len(sessions):
                    ok = agent.resume(sessions[idx]["session_id"])
                    print(f"✅ 已恢复 session {sessions[idx]['session_id']}" if ok else "⚠ 恢复失败")
                else:
                    print("⚠ 无效编号")
            except (ValueError, EOFError):
                print("⚠ 无效输入")
        return True

    if cmd == "/help":
        print("可用命令:")
        print("  /compact          手动触发压缩")
        print("  /resume           恢复旧会话（交互选择）")
        print("  /resume <id>      直接恢复指定会话")
        print("  /reset            清空对话记忆")
        print("  /debug            切换调试模式")
        print("  /debug verbose    详细调试模式（完整输出）")
        print("  /model            交互式切换模型")
        print("  /model list       列出所有可用模型")
        print("  /model <name>     直接切换到指定模型")
        print("  /log chat         查询最近聊天记录")
        print("  /log phase <id>   查询指定 trace 的阶段事件")
        print("  /log facts        查询长期记忆")
        print("  /log session      列出所有会话")
        print("  /log session <id> 查看指定会话详情")
        print("  /log tool         查询最近工具调用")
        print("  /log compression  查询压缩记录")
        print("  /log clear        清空所有日志")
        print("  /help             显示帮助")
        print("  exit/quit         退出")
        return True

    if cmd in ("exit", "quit"):
        return False

    return None  # 继续对话


async def stream_chat(agent: Agent, user_input: str,
                      output_adapter: ConsoleOutput) -> AgentResponse:
    """流式 chat：逐 token 输出，返回最终 AgentResponse。"""
    output_adapter.stream_start()
    final_text = ""
    emotion = ""
    gesture = None

    async for event in agent.chat_stream(user_input):
        if event.type == "text_token":
            token = event.data.get("text", "")
            if token:
                output_adapter.stream_token(token)
                final_text += token
        elif event.type == "emotion.update":
            emotion = event.data.get("emotion", emotion)
            gesture = event.data.get("gesture")
            if debug_mode[1]:  # verbose 模式输出 emotion switch
                print(f"\n  🎭 emotion: {emotion} gesture: {gesture or '-'}", end="", flush=True)
        elif event.type in ("tool.start", "tool.done"):
            if debug_mode[1]:  # verbose 模式
                name = event.data.get("name", "")
                if event.type == "tool.start":
                    args = event.data.get("arguments", {})
                    print(f"\n  ⚙ 调用工具: {name}({args})", end="", flush=True)
                else:
                    result = event.data.get("result", "")
                    preview = str(result)[:40]
                    print(f" → {preview}", flush=True)
        elif event.type == "node.start":
            name = event.data.get("name", "")
            if debug_mode[1]:
                print(f"\n  📍 {name}", end="", flush=True)
        elif event.type == "node.done":
            if debug_mode[1]:
                name = event.data.get("name", "")
                # 显示简要摘要
                extra = {k: v for k, v in event.data.items() if k != "name"}
                summary = ", ".join(f"{k}={v}" for k, v in extra.items() if v not in (None, "", 0, False))
                if summary:
                    print(f" → {summary}", flush=True)
        elif event.type == "done":
            final_text = event.data.get("text", final_text)
            emotion = event.data.get("emotion", "")
            gesture = event.data.get("gesture")

    output_adapter.stream_end()
    return AgentResponse(text=final_text, emotion=emotion, gesture=gesture)


# 全局调试状态（被 stream_chat 引用）
debug_mode = [False, False]


def main():
    import os
    from dotenv import load_dotenv
    load_dotenv()

    # ── 加载 RAG 知识库 ──
    vectorLibrary = VectorStore.load(Path("anima/data/vectorlibrary/Saki.pkl"))
    keywordLibrary = KeywordStore.load(Path("anima/data/keywordlibrary/Saki.pkl"))

    # ── 加载人设 ──
    persona = Path("anima/data/prompts/saki_persona.txt").read_text(encoding="utf-8")

    # ── 创建 LLM ──
    llm = OpenAICompatibleClient()
    # ── 创建 Agent（图引擎版） ──
    async def _permission_callback(tool_name: str, args: dict) -> bool:
        """CLI 权限回调：同步询问用户。"""
        print(f"\n  ⚠ 工具「{tool_name}」需要你的确认")
        preview = str(args)[:80]
        if preview:
            print(f"    参数: {preview}")
        try:
            reply = input("  允许执行？(Y/n): ").strip().lower()
            return reply in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    perm_mgr = PermissionManager(callback=_permission_callback)

    # ── 日志 + 记忆 + Session 系统 ──
    from anima.core.config import get_log_config
    log_cfg = get_log_config()
    log_db = ChatLogDB(
        max_db_size_mb=log_cfg["max_db_size_mb"],
        max_age_days=log_cfg["max_age_days"],
    )

    from anima.core.session.store import SessionStore
    from anima.core.memory.default_provider import DefaultMemoryProvider
    from anima.core.memory.store import MemoryStore
    from anima.core.paths import sessions_dir, memory_dir

    session_store = SessionStore(db_path=str(sessions_dir() / "sessions.db"))
    memory_store = MemoryStore(db_path=str(memory_dir() / "memory.db"))
    memory_provider = DefaultMemoryProvider(memory_store, log_db=log_db, persona_name="saki")

    agent = Agent.create_default(
        llm=llm,
        persona=persona,
        vector_store=vectorLibrary,
        keyword_store=keywordLibrary,
        permission_manager=perm_mgr,
        log_db=log_db,
        memory_provider=memory_provider,
        session_store=session_store,
    )

    # ── I/O ──
    input_adapter = ConsoleInput("> ")
    output_adapter = ConsoleOutput("Saki", emotion_icons)

    # ── 调试状态（引用模块级 debug_mode，供 stream_chat 读取） ──
    global debug_mode

    output_adapter.send(AgentResponse(
        text=f"Saki 已就绪（{llm._model}）。输入 /help 查看命令。"
    ))

    # ── 循环复用 ──
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while True:
            try:
                line = input_adapter.receive()
            except EOFError:
                break

            if not line.strip():
                continue

            result = handle_command(line, agent, llm, debug_mode, log_db=log_db)
            if result is False:
                break
            if result is not None:
                continue

            # ── 正常对话（流式） ──
            try:
                response = loop.run_until_complete(
                    stream_chat(agent, line, output_adapter)
                )
            except Exception:
                import traceback
                traceback.print_exc()
                response = AgentResponse(
                    text="抱歉，我刚才走神了，能再说一遍吗？",
                    emotion="confused",
                )
                output_adapter.send(response)

            if debug_mode[0]:
                print(format_debug(response))

    except KeyboardInterrupt:
        pass
    finally:
        # 先取消所有挂起的 task，避免 loop.close() 时协程残留报错
        pending = asyncio.all_tasks(loop)
        for t in pending:
            t.cancel()
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        agent.shutdown()
        loop.close()
        output_adapter.send(AgentResponse(text="再见！"))


if __name__ == "__main__":
    # 延迟导入避免循环
    from anima.core.rag.VectorStore import VectorStore
    from anima.core.rag.KeywordStore import KeywordStore
    main()
