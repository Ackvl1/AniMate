"""OpenAICompatibleClient — LLM 调用封装（流式 + 同步 + 自动重试）"""

from __future__ import annotations
import json
import threading
import time
from typing import AsyncGenerator, Generator

from anima.core.config import get_llm_config, LLM_CATALOG
from anima.core.errors import LLMError
from anima.core.llm.models import LLMResult, ToolCall, find_provider_by_model
from anima.core.log import setup_logger

logger = setup_logger(__name__)


class OpenAICompatibleClient:
    """兼容 OpenAI API 的 LLM 客户端（DeepSeek / OpenAI / Qwen / MiniMax 等）。

    延迟加载：`import openai` 和 `OpenAI()` 构造推迟到第一次 chat 调用时。
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        try:
            cfg = get_llm_config(provider)
        except KeyError as e:
            raise LLMError(str(e)) from e

        self._model = model or cfg.default_model
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = 1.0
        self._temperature = temperature if temperature is not None else cfg.default_temperature
        self._max_tokens = max_tokens if max_tokens is not None else cfg.default_max_tokens

        # 延迟加载：只存配置，不 import openai
        self._provider_config = cfg
        self._client = None
        self._async_client = None

        # 后台预加载：用户打字时静默 import openai
        self._openai_ready = False
        self._preloader = threading.Thread(target=self._bg_import, daemon=True)
        self._preloader.start()

        logger.info(
            "LLM client configured: model=%s (lazy init + bg preload)",
            self._model,
        )

    def _bg_import(self):
        """后台线程：预先 import openai。"""
        try:
            __import__("openai")
            self._openai_ready = True
            logger.debug("openai preloaded in background")
        except Exception:
            logger.debug("openai bg preload failed, will retry on demand")

    def _ensure_client(self):
        """延迟创建 OpenAI 客户端（首次调用时 import openai）。"""
        if self._client is not None:
            return

        # 后台预加载还没完成？等它
        if not self._openai_ready and self._preloader.is_alive():
            self._preloader.join(timeout=10)

        import openai

        cfg = self._provider_config
        self._client = openai.OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            **( {"default_headers": cfg.extra_headers} if cfg.extra_headers else {}),
        )
        logger.info("LLM client initialized: base_url=%s", cfg.base_url)

    def _ensure_async_client(self):
        """延迟创建 AsyncOpenAI 客户端。"""
        if self._async_client is not None:
            return
        import openai

        cfg = self._provider_config
        self._async_client = openai.AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            **( {"default_headers": cfg.extra_headers} if cfg.extra_headers else {}),
        )

    def switch_provider(self, provider_or_model: str) -> str | None:
        """运行时切换 LLM provider/模型。不丢失对话记忆。

        Returns:
            切换后的模型名，失败返回 None。
        """
        import os

        # 1. 确定 provider 和 model
        provider = find_provider_by_model(provider_or_model)
        model = None

        if provider:
            # 传的是具体模型名 → 锁定模型
            model = provider_or_model
        else:
            # 传的是 provider 名
            provider = provider_or_model
            info = LLM_CATALOG.get(provider)
            if info:
                model = info["default"]
            else:
                available = ", ".join(LLM_CATALOG.keys())
                logger.warning("未知 provider/model: %s（可用: %s）", provider_or_model, available)
                return None

        info = LLM_CATALOG.get(provider)
        if not info:
            logger.warning("未知 provider: %s", provider)
            return None

        # 2. 检查 API Key
        api_key = os.getenv(info["api_key_env"], "")
        if not api_key:
            logger.warning("环境变量 %s 未设置，无法切换到 %s", info["api_key_env"], info["name"])
            return None

        # 3. 重建客户端（延迟加载：只更新配置，重建留给首次 chat）
        self._model = model or info["default"]
        self._temperature = 0.7
        self._max_tokens = 4096

        # 重建 config + 重置 client
        from anima.core.config import ProviderConfig
        base_url = info.get("base_url", "")
        if "base_url_env" in info:
            base_url = os.getenv(info["base_url_env"], info.get("base_url_default", base_url))
        self._provider_config = ProviderConfig(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            default_model=self._model,
        )
        self._client = None  # 下次 chat 时重建
        self._async_client = None  # 下次 async chat 时重建

        logger.info("switched to provider=%s model=%s base_url=%s",
                     provider, self._model, base_url)
        return self._model

    def chat(self, messages: list[dict], tools: list | None = None) -> LLMResult:
        """同步调用，返回 LLMResult（含 content + tool_calls）。"""
        self._ensure_client()
        kwargs = self._build_kwargs(messages, tools, stream=False)
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                msg = resp.choices[0].message
                usage_tokens = getattr(resp, "usage", None)
                total_tokens = usage_tokens.total_tokens if usage_tokens else 0
                return LLMResult(
                    content=msg.content or "",
                    tool_calls=ToolCall.from_openai(msg.tool_calls),
                    total_tokens=total_tokens,
                )
            except self._retryable_errors() as e:
                if attempt == self._max_retries:
                    raise LLMError(f"LLM 调用失败（已重试 {self._max_retries} 次）: {e}") from e
                self._wait_and_log(attempt, e)
                continue
            except Exception as e:
                raise LLMError(f"LLM 调用失败: {e}") from e
        raise LLMError("LLM 调用失败：所有重试已耗尽")

    async def chat_async(self, messages: list[dict], tools: list | None = None) -> LLMResult:
        """异步调用（不阻塞事件循环），用于 ContextManager 摘要等异步路径。"""
        self._ensure_async_client()
        kwargs = self._build_kwargs(messages, tools, stream=False)
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self._async_client.chat.completions.create(**kwargs)
                msg = resp.choices[0].message
                usage_tokens = getattr(resp, "usage", None)
                total_tokens = usage_tokens.total_tokens if usage_tokens else 0
                return LLMResult(
                    content=msg.content or "",
                    tool_calls=ToolCall.from_openai(msg.tool_calls),
                    total_tokens=total_tokens,
                )
            except self._retryable_errors() as e:
                if attempt == self._max_retries:
                    raise LLMError(f"LLM 异步调用失败（已重试 {self._max_retries} 次）: {e}") from e
                await self._wait_and_log_async(attempt, e)
                continue
            except Exception as e:
                raise LLMError(f"LLM 异步调用失败: {e}") from e
        raise LLMError("LLM 异步调用失败：所有重试已耗尽")

    def chat_stream(self, messages: list[dict], tools: list | None = None) -> Generator[dict, None, None]:
        """流式调用，yield 统一事件字典。"""
        self._ensure_client()
        kwargs = self._build_kwargs(messages, tools, stream=True)
        yielded_something = False
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)
                for chunk in response:
                    yielded_something = True
                    # usage-only chunk (choices 为空)
                    if chunk.usage and not chunk.choices:
                        usage = chunk.usage
                        if hasattr(usage, "model_dump"):
                            usage = usage.model_dump()
                        yield {"type": "usage", "total_tokens": usage.get("total_tokens", 0)}
                        continue
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue
                    if delta.content:
                        yield {"type": "delta", "content": delta.content}
                    if isinstance(getattr(delta, 'reasoning_content', None), str):
                        yield {"type": "delta", "reasoning_content": delta.reasoning_content}
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            yield {
                                "type": "tool_call",
                                "index": tc.index,
                                "id": tc.id or "",
                                "name": tc.function.name if tc.function else "",
                                "arguments": tc.function.arguments if tc.function else "",
                            }
                    if chunk.choices and chunk.choices[0].finish_reason:
                        yield {"type": "done"}
                return
            except self._retryable_errors() as e:
                if yielded_something:
                    raise LLMError(f"LLM 流式调用中断: {e}") from e
                if attempt == self._max_retries:
                    raise LLMError(f"LLM 流式调用失败（已重试 {self._max_retries} 次）: {e}") from e
                self._wait_and_log(attempt, e)
                continue
            except Exception as e:
                raise LLMError(f"LLM 流式调用失败: {e}") from e

    async def chat_stream_async(self, messages: list[dict], tools: list | None = None) -> AsyncGenerator[dict, None]:
        """异步流式调用，用 async for 迭代（不阻塞事件循环）。"""
        self._ensure_async_client()
        kwargs = self._build_kwargs(messages, tools, stream=True)
        yielded_something = False
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._async_client.chat.completions.create(**kwargs)
                async for chunk in response:
                    yielded_something = True
                    # usage-only chunk (choices 为空)
                    if chunk.usage and not chunk.choices:
                        usage = chunk.usage
                        if hasattr(usage, "model_dump"):
                            usage = usage.model_dump()
                        yield {"type": "usage", "total_tokens": usage.get("total_tokens", 0)}
                        continue
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue
                    if delta.content:
                        yield {"type": "delta", "content": delta.content}
                    if isinstance(getattr(delta, 'reasoning_content', None), str):
                        yield {"type": "delta", "reasoning_content": delta.reasoning_content}
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            yield {
                                "type": "tool_call",
                                "index": tc.index,
                                "id": tc.id or "",
                                "name": tc.function.name if tc.function else "",
                                "arguments": tc.function.arguments if tc.function else "",
                            }
                    if chunk.choices and chunk.choices[0].finish_reason:
                        yield {"type": "done"}
                return
            except self._retryable_errors() as e:
                if yielded_something:
                    raise LLMError(f"LLM 流式调用中断: {e}") from e
                if attempt == self._max_retries:
                    raise LLMError(f"LLM 异步流式调用失败（已重试 {self._max_retries} 次）: {e}") from e
                await self._wait_and_log_async(attempt, e)
                continue
            except Exception as e:
                raise LLMError(f"LLM 异步流式调用失败: {e}") from e

    def _build_kwargs(self, messages, tools, stream):
        # DeepSeek thinking 模式：历史 assistant 消息必须带 reasoning_content
        # 如果 messages 里缺这个字段，API 会报 400
        # 解决：给没有 reasoning_content 的 assistant 消息加一个空的
        safe_messages = []
        for m in messages:
            msg = dict(m)
            if msg.get("role") == "assistant" and "reasoning_content" not in msg:
                msg["reasoning_content"] = ""
            safe_messages.append(msg)

        kwargs = {
            "model": self._model,
            "messages": safe_messages,
            "stream": stream,
            "timeout": self._timeout,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def _retryable_errors(self) -> tuple:
        import openai
        return (
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        )

    def _wait_and_log(self, attempt: int, error: Exception) -> None:
        wait = self._backoff_base * (2 ** (attempt - 1))
        logger.warning("LLM call failed (attempt %d/%d), retrying in %.1fs: %s", attempt, self._max_retries, wait, error)
        time.sleep(wait)
