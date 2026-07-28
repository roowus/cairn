"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

# Default to a throwaway config dir so tests never touch ~/.cairn.
os.environ.setdefault("CAIRN_CONFIG_DIR", "/tmp/cairn-test-config")


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path, monkeypatch):
    """Each test gets its own config/data dir under tmp_path."""
    monkeypatch.setenv("CAIRN_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    """Strip CAIRN_LLM__* from the host shell so unit tests are deterministic.

    The developer's real provider (e.g. GLM via Z.AI) is exported in the shell;
    without this, those vars leak into every test via the env-settings source.
    Tests that need a provider set it explicitly themselves.
    """
    for k in list(os.environ):
        if k.startswith("CAIRN_LLM__"):
            monkeypatch.delenv(k, raising=False)


@pytest.fixture
def fake_settings(tmp_path):
    from pydantic import SecretStr

    from cairn.core.config import LLMSettings, Settings

    return Settings(
        llm=LLMSettings(
            provider="anthropic", model="claude-sonnet-5", api_key=SecretStr("sk-test")
        ),
        data_dir=tmp_path,
    )


@pytest.fixture
def empty_ctx():
    from cairn.execution.base import PluginContext

    return PluginContext(http=None)
