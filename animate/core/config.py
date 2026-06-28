"""Animate 核心配置 — 从 config.yaml 加载 Provider 目录"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ── 配置数据类 ──────────────────────────────────────────


@dataclass
class ProviderConfig:
    """一个 Provider 的配置。"""
    api_key: str
    base_url: str
    default_model: str = ""
    default_max_tokens: int = 4096
    default_temperature: float = 0.7
    default_context_length: int = 1000000
    extra_headers: dict[str, str] = field(default_factory=dict)


# ── 加载 YAML ──────────────────────────────────────────

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


def _load_yaml() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# 惰性加载（首次 import 时不执行 IO，避免 config.yaml 缺失导致模块加载失败）
_data: dict | None = None


def _get_data() -> dict:
    global _data
    if _data is None:
        try:
            _data = _load_yaml()
        except Exception:
            _data = {}
    return _data


# LLM Provider 目录（惰性加载）
def _get_llm_catalog() -> dict[str, dict]:
    return _get_data().get("llm", {})


# Embedding Provider 目录（惰性加载）
def _get_embedding_catalog() -> dict[str, dict]:
    return _get_data().get("embedding", {})


# ── 当前活跃 Provider ──────────────────────────────────

_DEFAULT_LLM_PROVIDER: str = os.getenv("ANIMATE_LLM_PROVIDER", "deepseek").lower()
_DEFAULT_EMBEDDING_PROVIDER: str = os.getenv("ANIMATE_EMBEDDING_PROVIDER", "dashscope").lower()


# ── 工厂函数 ────────────────────────────────────────────

def _build_provider_config(info: dict) -> ProviderConfig:
    """从 catalog 条目构建 ProviderConfig（API Key 从环境变量读取）。"""
    api_key = os.getenv(info["api_key_env"], "")
    base_url = info.get("base_url", "")
    # 支持从环境变量读取 base_url（有则覆盖 yaml 内默认值）
    if "base_url_env" in info:
        base_url = os.getenv(info["base_url_env"], info.get("base_url_default", base_url))
    return ProviderConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        default_model=info["default"],
        default_context_length=info.get("context_length", 1000000),
    )


def get_llm_config(provider: str | None = None) -> ProviderConfig:
    """获取 LLM Provider 配置。"""
    p = (provider or _DEFAULT_LLM_PROVIDER).lower()
    info = _get_llm_catalog().get(p)
    if info is None:
        raise KeyError(
            f"未注册的 LLM provider '{p}'，可用: {list(_get_llm_catalog().keys())}"
        )
    return _build_provider_config(info)


def get_embedding_config(provider: str | None = None) -> ProviderConfig:
    """获取 Embedding Provider 配置。"""
    p = (provider or _DEFAULT_EMBEDDING_PROVIDER).lower()
    info = _get_embedding_catalog().get(p)
    if info is None:
        raise KeyError(
            f"未注册的 Embedding provider '{p}'，可用: {list(_get_embedding_catalog().keys())}"
        )
    return _build_provider_config(info)


def llm_model_name(provider: str | None = None) -> str:
    """获取 LLM 模型名。"""
    return get_llm_config(provider).default_model


def embedding_model_name(provider: str | None = None) -> str:
    """获取 Embedding 模型名。"""
    return get_embedding_config(provider).default_model


def get_llm_client():
    """创建 openai.OpenAI 实例（LLM）。"""
    import openai
    cfg = get_llm_config()
    return openai.OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


def get_embedding_client():
    """创建 openai.OpenAI 实例（Embedding）。"""
    import openai
    cfg = get_embedding_config()
    return openai.OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


def set_default_provider(provider: str) -> None:
    """运行时切换默认 LLM provider。"""
    global _DEFAULT_LLM_PROVIDER
    provider = provider.lower()
    if provider not in _get_llm_catalog():
        raise KeyError(f"未注册的 provider '{provider}'")
    _DEFAULT_LLM_PROVIDER = provider


def set_default_embedding_provider(provider: str) -> None:
    """运行时切换默认 Embedding provider。"""
    global _DEFAULT_EMBEDDING_PROVIDER
    provider = provider.lower()
    if provider not in _get_embedding_catalog():
        raise KeyError(f"未注册的 embedding provider '{provider}'")
    _DEFAULT_EMBEDDING_PROVIDER = provider


# ── 压缩配置 ──────────────────────────────────────────

def _get_compress_config() -> dict:
    return _get_data().get("compress", {})

def get_compress_config() -> dict:
    """获取压缩参数配置。"""
    cfg = _get_compress_config()
    return {
        "threshold": cfg.get("threshold", 0.70),
        "head_rounds": cfg.get("head_rounds", 5),
        "tail_rounds": cfg.get("tail_rounds", 10),
        "compact_reserve": cfg.get("compact_reserve", 30000),
        "max_failures": cfg.get("max_failures", 3),
        "model_limit": cfg.get("model_limit", 1000000),
    }


def get_agent_config() -> dict:
    """获取 Agent 参数配置。"""
    cfg = _get_data().get("agent", {})
    return {
        "max_graph_steps": cfg.get("max_graph_steps", 50),
        "max_react_rounds": cfg.get("max_react_rounds", 10),
    }


def get_log_config() -> dict:
    """获取日志轮转参数配置。"""
    cfg = _get_data().get("log", {})
    return {
        "max_db_size_mb": cfg.get("max_db_size_mb", 50),
        "max_age_days": cfg.get("max_age_days", 30),
    }


def get_memory_config() -> dict:
    """获取记忆系统参数配置。"""
    cfg = _get_data().get("memory", {})
    se = cfg.get("session_end", {})
    pf = cfg.get("prefetch", {})
    return {
        "session_end": {
            "min_user_messages": se.get("min_user_messages", 4),
            "content_limit": se.get("content_limit", 2000),
            "trust_score": se.get("trust_score", 0.7),
        },
        "prefetch": {
            "limit": pf.get("limit", 5),
        },
    }


# ── 向后兼容：from animate.core.config import LLM_CATALOG 仍可用 ──

def __getattr__(name: str):
    """惰性加载 LLM_CATALOG 和 EMBEDDING_CATALOG，保持旧 import 语法兼容。"""
    if name == "LLM_CATALOG":
        return _get_llm_catalog()
    if name == "EMBEDDING_CATALOG":
        return _get_embedding_catalog()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
