"""build_model provider routing (no live network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from cairn.core.config import LLMSettings, Settings
from cairn.core.errors import ProviderError
from cairn.reasoning.agent import build_model


def _settings(**kwargs) -> Settings:
    return Settings(llm=LLMSettings(**kwargs), data_dir="/tmp")


def test_build_xai_uses_openai_compatible(tmp_path):
    s = Settings(
        llm=LLMSettings(
            provider="xai",
            model="grok-4.5",
            api_key=SecretStr("tok"),
            base_url="https://api.x.ai/v1",
        ),
        data_dir=tmp_path,
    )
    with patch("cairn.reasoning.agent.OpenAIChatModel") as mock_cls:
        mock_cls.return_value = MagicMock(name="model")
        m = build_model(s)
        assert m is mock_cls.return_value
        args, kwargs = mock_cls.call_args
        assert args[0] == "grok-4.5"
        provider = kwargs["provider"]
        # OpenAIProvider stores base_url/api_key on the instance.
        assert "api.x.ai" in (getattr(provider, "base_url", "") or "")


def test_build_xai_missing_key_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_AUTH_PATH", str(tmp_path / "none.json"))
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    s = Settings(
        llm=LLMSettings(provider="xai", model="grok-4.5"),
        data_dir=tmp_path,
    )
    with pytest.raises(ProviderError, match="no credential"):
        build_model(s)


def test_build_xai_from_pi_auth(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(
        __import__("json").dumps({"xai": {"type": "api_key", "key": "from-pi"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_AUTH_PATH", str(auth))
    s = Settings(
        llm=LLMSettings(provider="xai", model="grok-4.5"),
        data_dir=tmp_path,
    )
    with patch("cairn.reasoning.agent.OpenAIChatModel") as mock_cls:
        mock_cls.return_value = MagicMock()
        build_model(s)
        assert s.llm.api_key is not None
        assert s.llm.api_key.get_secret_value() == "from-pi"


def test_build_anthropic():
    s = _settings(provider="anthropic", model="claude-sonnet-5", api_key=SecretStr("sk"))
    with patch("cairn.reasoning.agent.AnthropicModel") as mock_cls:
        mock_cls.return_value = MagicMock()
        build_model(s)
        mock_cls.assert_called_once()
        assert mock_cls.call_args[0][0] == "claude-sonnet-5"


def test_build_unknown_provider():
    s = _settings(provider="nope", model="x", api_key=SecretStr("k"))
    with pytest.raises(ProviderError, match="Unknown LLM provider"):
        build_model(s)
