"""TokenCounter — 增量 token 计数器，使用 tiktoken cl100k_base。

每轮只 encode 新增消息，避免全量 O(n) 扫描。
"""

import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")

# 多模态 content 中图片的 token 估算
_IMAGE_TOKEN_ESTIMATE = 1600


def _count_content(content) -> int:
    """估算一条消息的 content 的 token 数。"""
    if content is None:
        return 0
    if isinstance(content, str):
        if not content:
            return 0
        return len(_enc.encode(content, disallowed_special=()))
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += len(_enc.encode(part, disallowed_special=()))
            elif isinstance(part, dict):
                ptype = part.get("type", "")
                if ptype in ("image_url", "input_image", "image"):
                    total += _IMAGE_TOKEN_ESTIMATE
                else:
                    text = part.get("text", "")
                    if text:
                        total += len(_enc.encode(text, disallowed_special=()))
        return total
    return len(_enc.encode(str(content or ""), disallowed_special=()))


class TokenCounter:
    """增量 token 计数器。

    Usage:
        counter = TokenCounter()
        counter.add_message({"role": "user", "content": "你好"})
        print(counter.total)  # > 0
        counter.remove_messages(3)
        counter.rebuild(new_messages)
    """

    def __init__(self):
        self._counts: list[int] = []
        self._total: int = 0

    @property
    def total(self) -> int:
        return self._total

    def add_message(self, message: dict) -> None:
        """添加一条消息并累加 token 数。"""
        count = _count_content(message.get("content"))
        self._counts.append(count)
        self._total += count

    def remove_messages(self, count: int) -> None:
        """移除最早 N 条消息的 token 计数。"""
        if count <= 0:
            return
        actual = min(count, len(self._counts))
        for _ in range(actual):
            removed = self._counts.pop(0)
            self._total -= removed

    def rebuild(self, messages: list[dict]) -> None:
        """全量重建（用于压缩后）。"""
        self._counts = [_count_content(m.get("content")) for m in messages]
        self._total = sum(self._counts)
