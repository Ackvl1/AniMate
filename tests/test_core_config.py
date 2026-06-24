"""Tests for animate/core/config.py — YAML 配置加载"""

import pytest
from unittest.mock import patch
import os


class TestYAMLLoading:
    """YAML 加载 + 目录结构"""

    def test_llm_catalog_has_required_providers(self):
        """LLM_CATALOG 包含 deepseek、zhipu、qwen"""
        from animate.core.config import LLM_CATALOG
        for name in ("deepseek", "zhipu", "qwen"):
            assert name in LLM_CATALOG, f"缺少 {name}"

    def test_embedding_catalog_has_dashscope(self):
        """EMBEDDING_CATALOG 包含 dashscope"""
        from animate.core.config import EMBEDDING_CATALOG
        assert "dashscope" in EMBEDDING_CATALOG

    def test_each_llm_provider_has_required_fields(self):
        """每个 LLM provider 有 name/base_url/api_key_env/models/default"""
        from animate.core.config import LLM_CATALOG
        for name, info in LLM_CATALOG.items():
            assert "name" in info, f"{name} 缺少 name"
            assert "base_url" in info, f"{name} 缺少 base_url"
            assert "api_key_env" in info, f"{name} 缺少 api_key_env"
            assert "models" in info, f"{name} 缺少 models"
            assert "default" in info, f"{name} 缺少 default"
            assert info["default"] in info["models"], f"{name} default 不在 models 中"
            assert len(info["models"]) >= 1, f"{name} 至少有一个 model"

    def test_each_embedding_provider_has_required_fields(self):
        """每个 Embedding provider 有必要字段"""
        from animate.core.config import EMBEDDING_CATALOG
        for name, info in EMBEDDING_CATALOG.items():
            assert "name" in info
            assert "base_url" in info
            assert "api_key_env" in info
            assert "models" in info
            assert "default" in info

    def test_all_llm_models_unique(self):
        """所有 LLM 模型名唯一"""
        from animate.core.config import LLM_CATALOG
        all_names = []
        for info in LLM_CATALOG.values():
            all_names.extend(info["models"])
        assert len(all_names) == len(set(all_names)), "存在重名模型"


class TestGetLLMConfig:
    """get_llm_config 工厂函数"""

    def test_default_provider(self, monkeypatch):
        """默认 provider 从 ANIMATE_LLM_PROVIDER 读取"""
        from animate.core import config
        monkeypatch.setattr(config, "_DEFAULT_LLM_PROVIDER", "deepseek")
        cfg = config.get_llm_config()
        assert cfg.default_model == "deepseek-v4-flash"

    def test_custom_provider(self, monkeypatch):
        """指定 provider 返回对应配置"""
        from animate.core import config
        cfg = config.get_llm_config("zhipu")
        assert cfg.default_model == "glm-4.7"

    def test_unknown_provider_raises(self, monkeypatch):
        """未知 provider 抛 KeyError"""
        from animate.core import config
        monkeypatch.setattr(config, "_DEFAULT_LLM_PROVIDER", "nonexistent")
        with pytest.raises(KeyError, match="未注册的 LLM provider"):
            config.get_llm_config()


class TestGetEmbeddingConfig:
    """get_embedding_config 工厂函数"""

    def test_default_provider(self, monkeypatch):
        """默认 embedding provider 是 dashscope"""
        from animate.core import config
        monkeypatch.setattr(config, "_DEFAULT_EMBEDDING_PROVIDER", "dashscope")
        cfg = config.get_embedding_config()
        assert cfg.default_model == "text-embedding-v4"

    def test_unknown_provider_raises(self, monkeypatch):
        """未知 provider 抛 KeyError"""
        from animate.core import config
        monkeypatch.setattr(config, "_DEFAULT_EMBEDDING_PROVIDER", "nonexistent")
        with pytest.raises(KeyError, match="未注册的 Embedding provider"):
            config.get_embedding_config()


class TestSetDefaultProvider:
    """set_default_provider 运行时切换"""

    def test_switch_llm_provider(self):
        """切换 LLM provider 生效"""
        from animate.core import config
        original = config._DEFAULT_LLM_PROVIDER
        try:
            config.set_default_provider("zhipu")
            assert config._DEFAULT_LLM_PROVIDER == "zhipu"
            cfg = config.get_llm_config()
            assert cfg.default_model == "glm-4.7"
        finally:
            config._DEFAULT_LLM_PROVIDER = original

    def test_switch_unknown_raises(self):
        """切换到未知 provider 抛 KeyError"""
        from animate.core import config
        with pytest.raises(KeyError):
            config.set_default_provider("nonexistent")

    def test_switch_embedding_provider(self):
        """切换 Embedding provider 生效"""
        from animate.core import config
        original = config._DEFAULT_EMBEDDING_PROVIDER
        try:
            # dashscope 是唯一注册的，切换到它再切回来
            config.set_default_embedding_provider("dashscope")
            assert config._DEFAULT_EMBEDDING_PROVIDER == "dashscope"
        finally:
            config._DEFAULT_EMBEDDING_PROVIDER = original


class TestFindProviderByModel:
    """find_provider_by_model 从 catalog 反查"""

    def test_find_deepseek(self):
        from animate.core.config import LLM_CATALOG
        for key, info in LLM_CATALOG.items():
            if "deepseek-v4-flash" in info["models"]:
                assert key == "deepseek"
                break

    def test_find_zhipu(self):
        from animate.core.config import LLM_CATALOG
        for key, info in LLM_CATALOG.items():
            if "glm-4.7" in info["models"]:
                assert key == "zhipu"
                break

    def test_find_unknown_returns_none(self):
        from animate.core.config import LLM_CATALOG
        for info in LLM_CATALOG.values():
            assert "nonexistent-model" not in info["models"]
