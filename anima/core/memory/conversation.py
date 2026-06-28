"""会话工具函数 — 短期记忆辅助（不再持有消息列表本身）。"""

from typing import Any


def count_rounds(messages: list[dict]) -> int:
    """统计消息中有多少轮对话（user→assistant 对）。"""
    return sum(1 for m in messages if m["role"] == "assistant")


def estimate_tokens(messages: list[dict]) -> int:
    """粗略估算消息 token 数（使用 tiktoken cl100k_base）。"""
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str) and content:
            total += len(_enc.encode(content, disallowed_special=()))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if text:
                        total += len(_enc.encode(text, disallowed_special=()))
    return total


def find_message_boundaries(messages: list[dict], 
                            head_rounds: int = 5,
                            tail_rounds: int = 10) -> tuple[set[int], set[int]]:
    """找出 head 和 tail 的消息索引（供外部使用）。"""
    # head: system + 最早 head_rounds 轮
    head = {i for i, m in enumerate(messages) if m["role"] == "system"}
    round_count = 0
    for i, m in enumerate(messages):
        if m["role"] == "system":
            continue
        head.add(i)
        if m["role"] == "assistant":
            round_count += 1
            if round_count >= head_rounds:
                break

    # tail: 最近 tail_rounds 轮 + 最后一条
    tail = set()
    round_count = 0
    for i in range(len(messages) - 1, -1, -1):
        tail.add(i)
        if messages[i]["role"] == "user":
            round_count += 1
            if round_count >= tail_rounds:
                break

    return head, tail
