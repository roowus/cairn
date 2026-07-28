"""Named LLM profiles that the REPL ``/model`` command can switch between.

Profiles are built-in presets (Grok via xAI, GLM via Z.AI, local Ollama, …)
plus the currently configured ``settings.llm`` entry. Availability is based on
whether a credential can be resolved — either from ``CAIRN_LLM__API_KEY`` /
provider env vars, or from ``~/.pi/agent/auth.json``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from cairn.core.config import LLMSettings, Settings
from cairn.core.errors import ConfigError
from cairn.core.pi_auth import get_xai_api_key, get_zai_api_key

# OpenAI-compatible gateways.
XAI_BASE_URL = "https://api.x.ai/v1"
ZAI_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
OLLAMA_BASE_URL = "http://localhost:11434/v1"


@dataclass(frozen=True)
class ModelProfile:
    """A selectable model endpoint."""

    name: str  # short switch id, e.g. "grok"
    provider: str  # anthropic | openai | xai | ollama
    model: str  # provider model id
    base_url: str | None = None
    description: str = ""
    # Where to pull a key if settings.llm.api_key is empty.
    # "xai" → pi auth / XAI_API_KEY; "zai" → pi auth / ZAI_API_KEY; None → settings only.
    auth: str | None = None
    aliases: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model})"


# Built-in presets. First matching alias wins on lookup.
_BUILTIN: tuple[ModelProfile, ...] = (
    ModelProfile(
        name="grok",
        provider="xai",
        model="grok-4.5",
        base_url=XAI_BASE_URL,
        description="xAI Grok 4.5 (subscription OAuth or XAI_API_KEY)",
        auth="xai",
        aliases=("grok-4.5", "xai", "grok4.5"),
    ),
    ModelProfile(
        name="grok-4.3",
        provider="xai",
        model="grok-4.3",
        base_url=XAI_BASE_URL,
        description="xAI Grok 4.3",
        auth="xai",
        aliases=("grok4.3",),
    ),
    ModelProfile(
        name="glm",
        provider="openai",
        model="glm-5.2",
        base_url=ZAI_BASE_URL,
        description="Z.AI GLM-5.2 (free coding plan)",
        auth="zai",
        aliases=("glm-5.2", "zai", "glm5.2"),
    ),
    ModelProfile(
        name="glm-5.1",
        provider="openai",
        model="glm-5.1",
        base_url=ZAI_BASE_URL,
        description="Z.AI GLM-5.1",
        auth="zai",
        aliases=("glm5.1",),
    ),
    ModelProfile(
        name="ollama",
        provider="openai",
        model="llama3.1",
        base_url=OLLAMA_BASE_URL,
        description="Local Ollama (OpenAI-compatible)",
        auth=None,
        aliases=("local", "llama3.1"),
    ),
)


def builtin_profiles() -> list[ModelProfile]:
    return list(_BUILTIN)


def _index() -> dict[str, ModelProfile]:
    out: dict[str, ModelProfile] = {}
    for p in _BUILTIN:
        out[p.name.lower()] = p
        for a in p.aliases:
            out[a.lower()] = p
    return out


def find_profile(name: str) -> ModelProfile | None:
    """Look up a built-in profile by name or alias (case-insensitive)."""
    key = (name or "").strip().lower()
    if not key:
        return None
    return _index().get(key)


def resolve_api_key(profile: ModelProfile, settings: Settings | None = None) -> str | None:
    """Best-effort credential for a profile.

    Order: settings.llm.api_key (when it matches this profile's endpoint) →
    provider-specific env / pi-auth helpers → placeholder for local Ollama.
    """
    # Only reuse the configured key when the active settings already point at
    # this profile (avoids sending a Z.AI key to xAI after a switch).
    if settings and settings.llm.api_key and _settings_match_profile(settings.llm, profile):
        val = settings.llm.api_key.get_secret_value()
        if val:
            return val

    if profile.auth == "xai":
        import os

        env = os.environ.get("XAI_API_KEY") or os.environ.get("CAIRN_XAI_KEY")
        if env:
            return env
        return get_xai_api_key()

    if profile.auth == "zai":
        import os

        env = os.environ.get("ZAI_API_KEY") or os.environ.get("CAIRN_ZAI_KEY")
        if env:
            return env
        return get_zai_api_key()

    # Ollama accepts any non-empty key.
    if profile.base_url and "11434" in (profile.base_url or ""):
        return "ollama"
    return None


def _settings_match_profile(llm: LLMSettings, profile: ModelProfile) -> bool:
    if llm.model and llm.model == profile.model:
        return True
    if (llm.provider or "").lower() in {profile.provider, profile.name} and (
        not llm.model or llm.model == profile.model
    ):
        return True
    return bool(
        llm.base_url
        and profile.base_url
        and llm.base_url.rstrip("/") == profile.base_url.rstrip("/")
        and (not llm.model or llm.model == profile.model)
    )


def profile_available(profile: ModelProfile, settings: Settings | None = None) -> bool:
    """True if we can construct a model for this profile right now."""
    if profile.auth is None and profile.base_url and "11434" in profile.base_url:
        return True  # local Ollama — availability is runtime, not credential
    return bool(resolve_api_key(profile, settings))


def current_profile_name(settings: Settings) -> str:
    """Best-effort short name for the active settings.llm configuration."""
    llm = settings.llm
    # Prefer a built-in match.
    for p in _BUILTIN:
        if llm.model and llm.model == p.model:
            return p.name
        if (
            (llm.provider or "").lower() == "xai"
            and (llm.model or p.model) == p.model
            and p.auth == "xai"
        ):
            return p.name
    if llm.model:
        return llm.model
    if llm.provider:
        return llm.provider
    return "unknown"


def apply_profile(settings: Settings, profile: ModelProfile) -> Settings:
    """Mutate ``settings.llm`` to the given profile (resolves api key).

    Returns the same settings object for convenience.
    """
    key = resolve_api_key(profile, settings)
    if profile.auth is not None and not key:
        raise ConfigError(
            f"No credentials for model {profile.name!r}.\n"
            + (
                "  Log in with `pi` (/login xai) or set XAI_API_KEY / CAIRN_LLM__API_KEY."
                if profile.auth == "xai"
                else "  Log in with `pi` (zai key) or set ZAI_API_KEY / CAIRN_LLM__API_KEY."
            )
        )
    settings.llm.provider = profile.provider
    settings.llm.model = profile.model
    settings.llm.base_url = profile.base_url
    settings.llm.api_key = SecretStr(key) if key else None
    return settings


def list_profiles(settings: Settings | None = None) -> list[tuple[ModelProfile, bool]]:
    """Return ``(profile, available)`` for every built-in profile."""
    return [(p, profile_available(p, settings)) for p in _BUILTIN]
