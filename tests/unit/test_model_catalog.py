"""Model catalog + Session.switch_model."""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr
from pydantic_ai.models.test import TestModel

from cairn.core.config import LLMSettings, Settings
from cairn.core.errors import ConfigError
from cairn.orchestration.session import Session
from cairn.reasoning.catalog import (
    apply_profile,
    find_profile,
    list_profiles,
    profile_available,
    resolve_api_key,
)


def test_find_profile_aliases():
    g = find_profile("grok-4.5")
    assert g is not None
    assert g.name == "grok"
    assert g.model == "grok-4.5"
    assert find_profile("GLM") is not None
    assert find_profile("nope") is None


def test_resolve_xai_from_pi_auth(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps({"xai": {"type": "api_key", "key": "xai-from-pi"}}), encoding="utf-8"
    )
    monkeypatch.setenv("PI_AUTH_PATH", str(auth))
    profile = find_profile("grok")
    assert profile is not None
    assert resolve_api_key(profile) == "xai-from-pi"
    assert profile_available(profile) is True


def test_resolve_zai_from_pi_auth(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps({"zai": {"type": "api_key", "key": "zai-from-pi"}}), encoding="utf-8"
    )
    monkeypatch.setenv("PI_AUTH_PATH", str(auth))
    profile = find_profile("glm")
    assert profile is not None
    assert resolve_api_key(profile) == "zai-from-pi"


def test_apply_profile_missing_creds(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_AUTH_PATH", str(tmp_path / "missing.json"))
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("CAIRN_XAI_KEY", raising=False)
    s = Settings(llm=LLMSettings(provider="openai", model="gpt-4o"), data_dir=tmp_path)
    profile = find_profile("grok")
    assert profile is not None
    with pytest.raises(ConfigError, match="No credentials"):
        apply_profile(s, profile)


def test_list_profiles_marks_availability(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "xai": {"type": "api_key", "key": "x"},
                "zai": {"type": "api_key", "key": "z"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_AUTH_PATH", str(auth))
    rows = {p.name: ok for p, ok in list_profiles()}
    assert rows["grok"] is True
    assert rows["glm"] is True


def test_session_switch_model(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "xai": {"type": "api_key", "key": "xai-k"},
                "zai": {"type": "api_key", "key": "zai-k"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_AUTH_PATH", str(auth))

    settings = Settings(
        llm=LLMSettings(
            provider="xai",
            model="grok-4.5",
            api_key=SecretStr("xai-k"),
            base_url="https://api.x.ai/v1",
        ),
        data_dir=tmp_path,
    )
    # Start with a TestModel so no network is needed; switch_model rebuilds a real one.
    session = Session(settings=settings, model=TestModel(), registry=__import__(
        "cairn.execution.registry", fromlist=["PluginRegistry"]
    ).PluginRegistry())
    assert session.model_name  # smoke

    # Avoid constructing a real OpenAI client against the network: stub build_model.
    from cairn.orchestration import session as session_mod

    calls: list[str] = []

    def fake_build(s: Settings):
        calls.append(s.llm.model or "")
        return TestModel(custom_output_text=s.llm.model or "x")

    monkeypatch.setattr(session_mod, "build_model", fake_build)

    name = session.switch_model("glm")
    assert name  # TestModel may not expose model_name; settings do
    assert session.settings.llm.model == "glm-5.2"
    assert session.settings.llm.api_key is not None
    assert session.settings.llm.api_key.get_secret_value() == "zai-k"
    assert calls == ["glm-5.2"]

    session.switch_model("grok")
    assert session.settings.llm.model == "grok-4.5"
    assert session.settings.llm.provider == "xai"
    assert session.audit.model_name == session.model_name

    with pytest.raises(ConfigError, match="Unknown model"):
        session.switch_model("no-such-model")

    session.close()
