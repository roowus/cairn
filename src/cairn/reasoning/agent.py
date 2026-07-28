"""Construct the LLM model from provider-agnostic settings.

The model object is built here so a custom ``base_url`` (local Ollama or any
OpenAI-compatible gateway) is unambiguous. There is **no default provider**;
:func:`build_model` raises if the configuration is insufficient.

Supported providers:
  - ``anthropic`` — Claude
  - ``openai`` / ``ollama`` — OpenAI or any OpenAI-compatible gateway (Z.AI, Ollama)
  - ``xai`` / ``grok`` — xAI Grok (``https://api.x.ai/v1``), key from settings or
    ``~/.pi/agent/auth.json`` OAuth / ``XAI_API_KEY``
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from cairn.core.config import Settings
from cairn.core.errors import ProviderError
from cairn.core.pi_auth import get_xai_api_key, get_zai_api_key
from cairn.reasoning.catalog import XAI_BASE_URL, ZAI_BASE_URL

# Friendly fallbacks when a provider is chosen but no model name is given.
_DEFAULT_ANTHROPIC = "claude-sonnet-5"
_DEFAULT_OPENAI = "gpt-4o-mini"
_DEFAULT_LOCAL = "llama3.1"
_DEFAULT_XAI = "grok-4.5"
_DEFAULT_ZAI = "glm-5.2"


def _looks_anthropic(provider: str | None, model: str | None) -> bool:
    return (provider or "").lower() == "anthropic" or (
        not provider and bool(model) and "claude" in (model or "").lower()
    )


def _looks_xai(provider: str | None, model: str | None, base_url: str | None) -> bool:
    p = (provider or "").lower()
    if p in {"xai", "grok"}:
        return True
    if base_url and "api.x.ai" in base_url:
        return True
    m = (model or "").lower()
    return m.startswith("grok")


def _looks_zai(base_url: str | None, model: str | None) -> bool:
    if base_url and "api.z.ai" in base_url:
        return True
    m = (model or "").lower()
    return m.startswith("glm")


def _resolve_api_key(settings: Settings) -> str | None:
    """Return an API key, falling back to pi-auth for xAI / Z.AI when unset."""
    c = settings.llm
    if c.api_key:
        val = c.api_key.get_secret_value()
        if val:
            return val

    if _looks_xai(c.provider, c.model, c.base_url):
        key = get_xai_api_key()
        if key:
            # Cache onto settings so subsequent calls and audit see it without
            # re-reading the file every turn (refresh still happens inside
            # get_xai_api_key when the token is near expiry).
            settings.llm.api_key = SecretStr(key)
            return key

    if _looks_zai(c.base_url, c.model):
        key = get_zai_api_key()
        if key:
            settings.llm.api_key = SecretStr(key)
            return key

    return None


def build_model(settings: Settings):
    """Return a PydanticAI Model instance for the configured provider."""
    c = settings.llm
    provider = (c.provider or "").lower()
    api_key = _resolve_api_key(settings)
    model = c.model
    base_url = c.base_url

    if _looks_anthropic(provider, model):
        return AnthropicModel(
            model or _DEFAULT_ANTHROPIC,
            provider=AnthropicProvider(api_key=api_key, base_url=base_url),
        )

    if _looks_xai(provider, model, base_url):
        if not api_key:
            raise ProviderError(
                "xAI/Grok is selected but no credential was found. "
                "Run `pi` and `/login xai`, or set XAI_API_KEY / CAIRN_LLM__API_KEY."
            )
        return OpenAIChatModel(
            model or _DEFAULT_XAI,
            provider=OpenAIProvider(
                base_url=(base_url or XAI_BASE_URL),
                api_key=api_key,
            ),
        )

    if provider in ("", "openai", "ollama") or base_url:
        if not model:
            if _looks_zai(base_url, model):
                model = _DEFAULT_ZAI
            else:
                model = _DEFAULT_LOCAL if base_url else _DEFAULT_OPENAI
        # If this is the Z.AI gateway and we still have no key, try pi-auth once more.
        if not api_key and _looks_zai(base_url, model):
            api_key = get_zai_api_key()
            if api_key:
                settings.llm.api_key = SecretStr(api_key)
        # Ollama and other OpenAI-compatible gateways take a placeholder key.
        key = api_key or ("ollama" if base_url else None)
        # Default Z.AI base_url when model is clearly a GLM and none was set.
        if not base_url and _looks_zai(None, model):
            base_url = ZAI_BASE_URL
        return OpenAIChatModel(
            model,
            provider=OpenAIProvider(base_url=base_url, api_key=key),
        )

    raise ProviderError(
        f"Unknown LLM provider {provider!r}. Use 'anthropic', 'openai', 'xai'/'grok', "
        "or 'ollama' (with a base_url). See .env.example."
    )
