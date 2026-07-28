"""Config: env round-trip, empty handling, TOML, require_llm."""

from __future__ import annotations

import pytest

from cairn.core.config import load_settings, require_llm
from cairn.core.errors import ConfigError


def test_env_round_trip(monkeypatch):
    monkeypatch.setenv("CAIRN_LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("CAIRN_LLM__MODEL", "claude-sonnet-5")
    monkeypatch.setenv("CAIRN_LLM__API_KEY", "sk-test-123")
    monkeypatch.setenv("CAIRN_SHODAN_KEY", "SH-abc")
    s = load_settings()
    assert s.llm.provider == "anthropic"
    assert s.llm.model == "claude-sonnet-5"
    assert s.llm.api_key.get_secret_value() == "sk-test-123"
    assert "shodan" in s.plugin_keys()


def test_empty_provider_is_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setenv("CAIRN_LLM__PROVIDER", "")
    monkeypatch.delenv("CAIRN_LLM__MODEL", raising=False)
    monkeypatch.delenv("CAIRN_LLM__API_KEY", raising=False)
    s = load_settings(config_dir=tmp_path, project_env_file=None)
    assert not s.llm_is_configured()
    with pytest.raises(ConfigError):
        require_llm(s)


def test_toml_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CAIRN_CONFIG_DIR", str(tmp_path))
    for k in ("CAIRN_LLM__PROVIDER", "CAIRN_LLM__MODEL", "CAIRN_LLM__API_KEY"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "config.toml").write_text(
        '[llm]\nprovider = "openai"\nmodel = "gpt-4o"\napi_key = "sk-toml"\n', encoding="utf-8"
    )
    s = load_settings(config_dir=tmp_path, project_env_file=None)
    assert s.llm.provider == "openai"
    assert s.llm.model == "gpt-4o"
    assert s.llm.api_key.get_secret_value() == "sk-toml"


def test_provider_key_mapping(monkeypatch):
    monkeypatch.setenv("CAIRN_LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("CAIRN_HIBP_KEY", "hibp-secret")
    monkeypatch.setenv("CAIRN_ABUSEIPDB_KEY", "aibdb-secret")
    s = load_settings()
    keys = s.plugin_keys()
    assert set(keys) == {"hibp", "abuseipdb"}
    assert keys["hibp"].get_secret_value() == "hibp-secret"
