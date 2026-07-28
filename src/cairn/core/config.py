"""Provider-agnostic configuration.

There is **no default LLM provider**. The active provider/model/base_url/api_key
come entirely from configuration (env vars or TOML). Whatever the user sets is
used: Anthropic key → Claude, OpenAI key → GPT, base_url → local Ollama, etc.

Precedence (highest first): environment variables > ``~/.cairn/.env`` > ``./.env``
> ``~/.cairn/config.toml``. TOML is wired via a custom settings source so its
path can be overridden per-instance (for tests) without import-time resolution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from cairn.core import paths
from cairn.core.errors import ConfigError


class LLMSettings(BaseModel):
    """The LLM provider. All fields optional — but a usable path must be set."""

    provider: str | None = None  # "anthropic" | "openai" (covers Ollama via base_url)
    model: str | None = None
    base_url: str | None = None  # only for Ollama / OpenAI-compatible gateways
    api_key: SecretStr | None = None

    @field_validator("provider", "model", "base_url", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


# logical plugin key name -> Settings attribute that holds its SecretStr.
_KEY_FIELDS: dict[str, str] = {
    "shodan": "shodan_key",
    "virustotal": "virustotal_key",
    "censys": "censys_key",
    "abuseipdb": "abuseipdb_key",
    "hibp": "hibp_key",
    "brave": "brave_key",
    "exa": "exa_key",
    "github": "github_key",  # optional: lifts free 60/hr → 5,000/hr
    "urlscan": "urlscan_key",  # optional: higher community limit
}


class Settings(BaseSettings):
    """Top-level settings. Build via :func:`load_settings` (resolves file paths)."""

    # Per-instance TOML path (set by load_settings). Low priority among sources.
    _toml_path: ClassVar[Path | None] = None

    model_config = SettingsConfigDict(
        env_prefix="CAIRN_",
        env_nested_delimiter="__",
        env_file=(".env",),
        extra="ignore",
        case_sensitive=False,
    )

    llm: LLMSettings = LLMSettings()

    # Optional per-source API keys. A plugin activates once its key is set.
    shodan_key: SecretStr | None = None
    virustotal_key: SecretStr | None = None
    censys_key: SecretStr | None = None
    abuseipdb_key: SecretStr | None = None
    hibp_key: SecretStr | None = None
    brave_key: SecretStr | None = None
    exa_key: SecretStr | None = None
    github_key: SecretStr | None = None  # optional rate-limit boost (free w/o)
    urlscan_key: SecretStr | None = None  # optional rate-limit boost (free w/o)

    data_dir: Path = Path()  # filled by load_settings
    # Scratch workspace for agentic file ops (downloads, analyzer artifacts).
    # cwd is ALSO a workspace root (challenge files live in ./). Filled by load_settings.
    workspace_dir: Path = Path()
    # "investigate" (default): passive recon stance. "challenge": permits active
    # analysis of provided artifacts (files/pcap/images) but still forbids scanning
    # external hosts. Set via CAIRN_MODE.
    mode: Literal["investigate", "challenge"] = "investigate"
    log_level: str = "INFO"
    request_timeout: float = 30.0
    proxy: str | None = None
    # Browser-like default so first-party HTML (IG/etc.) matches incognito better.
    # Override with CAIRN_USER_AGENT if needed.
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # Off by default: plugins whose free tier has a hard per-DAY quota (e.g.
    # hackertarget ~50/day) are excluded from the brain's tools. Set
    # CAIRN_ALLOW_DAILY_LIMITED=1 to opt them in. Rate-limited-only sources stay on.
    allow_daily_limited: bool = False
    # --- Parallel-session knobs (see docs/architecture/parallel-sessions.md) ---
    # Ceiling on concurrently-running sessions in a SessionPool. Throughput/
    # orchestration only — never relaxes the hard-stop. The default is conservative
    # (most free OSINT sources rate-limit hard above a handful of parallel calls).
    max_concurrent_sessions: int = 4
    # Optional per-session ceilings enforced by the SessionPool (NOT by the
    # observer-only UsageTracker). None = unbounded; the pool halts a session's
    # turns once its tracker crosses the cap.
    session_max_spend: float | None = None
    session_max_calls: int | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml = (
            TomlConfigSettingsSource(settings_cls, toml_file=cls._toml_path)
            if cls._toml_path
            else TomlConfigSettingsSource(settings_cls)
        )
        # Priority (high -> low): init, env, dotenv, toml, secrets.
        return (init_settings, env_settings, dotenv_settings, toml, file_secret_settings)

    def plugin_keys(self) -> dict[str, SecretStr]:
        """Return logical-name -> SecretStr for every configured source key."""
        out: dict[str, SecretStr] = {}
        for logical, attr in _KEY_FIELDS.items():
            val = getattr(self, attr)
            if val is not None and val.get_secret_value():
                out[logical] = val
        return out

    def llm_is_configured(self) -> bool:
        """True if enough is set to construct a model (see reasoning.build_model)."""
        c = self.llm
        return bool(c.provider) or bool(c.base_url) or bool(c.model)


def load_settings(
    config_dir: Path | None = None,
    *,
    project_env_file: str | None = ".env",
) -> Settings:
    """Load settings, resolving config/.env files under ``config_dir``.

    Pass a temp dir in tests; leave default for production (``~/.cairn``). By
    default a ``./.env`` in the current directory is also read (developer
    convenience), but pass ``project_env_file=None`` to isolate from it — used by
    config tests that run from a project root containing a real ``.env``.
    """
    cfg = config_dir or paths.config_dir()
    Settings._toml_path = cfg / "config.toml"
    env_files: tuple[str, ...] = (str(cfg / ".env"),)
    if project_env_file:
        env_files = (*env_files, project_env_file)
    settings = Settings(_env_file=env_files)
    settings.data_dir = cfg
    # Default the scratch workspace under the config dir unless overridden
    # (CAIRN_WORKSPACE_DIR). cwd is also a workspace root, computed at call time.
    settings.workspace_dir = settings.workspace_dir or (cfg / "workspace")
    return settings


def require_llm(settings: Settings) -> None:
    """Raise ConfigError with exact guidance if no provider is configured."""
    if settings.llm_is_configured():
        return
    raise ConfigError(
        "No LLM provider configured. Set at least provider/model/api_key, e.g.:\n"
        "  # xAI Grok (reuses ~/.pi/agent/auth.json OAuth if no key set):\n"
        "  export CAIRN_LLM__PROVIDER=xai CAIRN_LLM__MODEL=grok-4.5\n"
        "  # Anthropic Claude:\n"
        "  export CAIRN_LLM__PROVIDER=anthropic\n"
        "  export CAIRN_LLM__MODEL=claude-sonnet-5\n"
        "  export CAIRN_LLM__API_KEY=sk-ant-...\n"
        "Or use local Ollama:\n"
        "  export CAIRN_LLM__PROVIDER=openai CAIRN_LLM__MODEL=llama3.1\n"
        "  export CAIRN_LLM__BASE_URL=http://localhost:11434/v1 CAIRN_LLM__API_KEY=ollama\n"
        "Or write ~/.cairn/config.toml (see .env.example). In the REPL, /model switches profiles."
    )


def settings_source_summary(settings: Settings) -> dict[str, Any]:
    """A safe, secret-free summary of the active settings (for logging)."""
    return {
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "base_url": settings.llm.base_url,
        "has_api_key": bool(settings.llm.api_key and settings.llm.api_key.get_secret_value()),
        "configured_keys": sorted(settings.plugin_keys().keys()),
        "data_dir": str(settings.data_dir),
    }
