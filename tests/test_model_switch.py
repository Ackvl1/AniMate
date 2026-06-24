"""Tests for 模型目录 + 模型热切换"""

from unittest.mock import MagicMock, patch
import pytest

from animate.core.config import LLM_CATALOG


class TestModelCatalog:
    """模型目录结构验证"""

    def test_catalog_has_required_providers(self):
        """至少包含 deepseek、zhipu、qwen 三家"""
        for name in ("deepseek", "zhipu", "qwen"):
            assert name in LLM_CATALOG, f"缺少 {name}"

    def test_each_provider_has_required_fields(self):
        """每个 provider 有 name/base_url/api_key_env/models/default"""
        for name, info in LLM_CATALOG.items():
            assert "name" in info, f"{name} 缺少 name"
            assert "base_url" in info, f"{name} 缺少 base_url"
            assert "api_key_env" in info, f"{name} 缺少 api_key_env"
            assert "models" in info, f"{name} 缺少 models"
            assert "default" in info, f"{name} 缺少 default"
            assert info["default"] in info["models"], f"{name} default 不在 models 列表中"
            assert len(info["models"]) >= 1, f"{name} 至少有一个 model"

    def test_all_models_have_unique_names(self):
        """所有模型名唯一（不跨 provider 重名）"""
        all_names = []
        for info in LLM_CATALOG.values():
            all_names.extend(info["models"])
        assert len(all_names) == len(set(all_names)), "存在重名的模型"

    def test_find_model_in_catalog(self):
        """通过模型名找到对应的 provider"""
        from animate.core.llm.models import find_provider_by_model
        assert find_provider_by_model("deepseek-v4-flash") == "deepseek"
        assert find_provider_by_model("glm-4.7") == "zhipu"
        assert find_provider_by_model("qwen-3") == "qwen"
        assert find_provider_by_model("nonexistent") is None


class TestLLMSwitchProvider:
    """LLM 客户端热切换"""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch):
        """注入测试用的 API Key 和 mock OpenAI"""
        monkeypatch.setenv("OPENAI_CHAT_API_KEY", "***")
        monkeypatch.setenv("ZAI_API_KEY", "***")

    def _patch_openai(self):
        """Mock OpenAI 避免真实 HTTP 调用"""
        return patch("openai.OpenAI")

    def test_switch_provider_changes_model(self):
        """switch_provider 后 _model 切换为目标模型的默认值"""
        from animate.core.llm.client import OpenAICompatibleClient
        from animate.core.config import set_default_provider

        # 先把默认 provider 设为 deepseek
        set_default_provider("deepseek")

        with self._patch_openai() as mock_openai:
            client = OpenAICompatibleClient(provider="deepseek", model="deepseek-v4-flash")
            original_model = client._model

            # 切换到 zhipu
            client.switch_provider("zhipu")
            assert client._model != original_model
            assert client._model == LLM_CATALOG["zhipu"]["default"]

    def test_switch_provider_creates_new_client(self):
        """switch_provider 后模型已变更（通过 model 名验证）"""
        from animate.core.llm.client import OpenAICompatibleClient
        from animate.core.config import set_default_provider

        set_default_provider("deepseek")

        with self._patch_openai(), \
             patch.dict("os.environ", {"QWEN_API_KEY": "test-key"}):
            client = OpenAICompatibleClient(provider="deepseek", model="deepseek-v4-flash")
            client.switch_provider("qwen")
            # model 变了说明已切换成功
            assert client._model == "qwen-3"

    def test_switch_to_specific_model(self):
        """switch_provider 支持指定具体模型名"""
        from animate.core.llm.client import OpenAICompatibleClient
        from animate.core.config import set_default_provider

        set_default_provider("deepseek")

        with self._patch_openai() as mock_openai:
            client = OpenAICompatibleClient(provider="deepseek", model="deepseek-v4-flash")
            client.switch_provider("glm-4.5")
            assert client._model == "glm-4.5"

    def test_switch_unknown_provider_doesnt_crash(self):
        """切到不存在的 provider 时保持当前配置"""
        from animate.core.llm.client import OpenAICompatibleClient
        from animate.core.config import set_default_provider

        set_default_provider("deepseek")

        with self._patch_openai() as mock_openai:
            instance = MagicMock()
            mock_openai.return_value = instance

            client = OpenAICompatibleClient(provider="deepseek", model="deepseek-v4-flash")
            original = client._model
            result = client.switch_provider("nonexistent")
            assert client._model == original
            assert result is None

    def test_switch_provider_returns_model_name(self):
        """switch_provider 成功时返回模型名"""
        from animate.core.llm.client import OpenAICompatibleClient
        from animate.core.config import set_default_provider

        set_default_provider("deepseek")

        with self._patch_openai():
            client = OpenAICompatibleClient(provider="deepseek", model="deepseek-v4-flash")
            result = client.switch_provider("zhipu")
            assert result == "glm-4.7"

    def test_switch_provider_missing_api_key_returns_none(self, monkeypatch):
        """API Key 缺失时返回 None"""
        from animate.core.llm.client import OpenAICompatibleClient
        from animate.core.config import set_default_provider

        set_default_provider("deepseek")
        monkeypatch.delenv("QWEN_API_KEY", raising=False)

        with self._patch_openai():
            client = OpenAICompatibleClient(provider="deepseek", model="deepseek-v4-flash")
            result = client.switch_provider("qwen")
            assert result is None


class TestHandleModelCommand:
    """handle_model_command 交互逻辑"""

    def test_model_list_shows_current(self, capsys):
        """/model list 显示当前厂商"""
        from unittest.mock import MagicMock
        from cli import handle_model_command

        llm = MagicMock()
        llm._model = "deepseek-v4-flash"

        handle_model_command(["/model", "list"], llm)
        output = capsys.readouterr().out
        assert "DeepSeek" in output
        assert "← 当前" in output

    def test_direct_switch_success(self, capsys):
        """/model <name> 直接切换成功"""
        from unittest.mock import MagicMock
        from cli import handle_model_command

        llm = MagicMock()
        llm.switch_provider.return_value = "glm-4.7"

        handle_model_command(["/model", "glm-4.7"], llm)
        output = capsys.readouterr().out
        assert "✅ 已切换到 glm-4.7" in output
        llm.switch_provider.assert_called_once_with("glm-4.7")

    def test_direct_switch_failure_shows_env_hint(self, capsys):
        """/model <name> 切换失败显示环境变量提示"""
        from unittest.mock import MagicMock
        from cli import handle_model_command

        llm = MagicMock()
        llm._model = "deepseek-v4-flash"
        llm.switch_provider.return_value = None

        handle_model_command(["/model", "glm-4.7"], llm)
        output = capsys.readouterr().out
        assert "ZAI_API_KEY" in output
        assert "未配置" in output

    def test_direct_switch_unknown_model(self, capsys):
        """/model <unknown> 显示未知提示"""
        from unittest.mock import MagicMock
        from cli import handle_model_command

        llm = MagicMock()
        llm._model = "deepseek-v4-flash"
        llm.switch_provider.return_value = None

        handle_model_command(["/model", "fake-model"], llm)
        output = capsys.readouterr().out
        assert "未知" in output

    def test_no_args_shows_current_model(self, capsys):
        """/model 无参数显示当前模型"""
        from unittest.mock import MagicMock
        from cli import handle_model_command

        llm = MagicMock()
        llm._model = "deepseek-v4-flash"

        # 模拟用户输入 0（返回）
        with patch("builtins.input", return_value="0"):
            handle_model_command(["/model"], llm)
        output = capsys.readouterr().out
        assert "当前模型: deepseek-v4-flash" in output
        assert "选择厂商" in output
