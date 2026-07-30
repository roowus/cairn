"""The plugin contract.

Every OSINT capability is a concrete :class:`BasePlugin` subclass. Plugins are
auto-discovered (see :mod:`cairn.execution.registry`) — you never register them.
A plugin takes a typed :class:`PluginInput`, executes a deterministic lookup, and
returns a :class:`PluginOutput` carrying a condensed ``summary_markdown`` and any
:class:`Entity` graph nodes it observed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from cairn.core.provenance import Confidence, Provenance
from cairn.execution.browser_http import DEFAULT_BROWSER_UA


@dataclass(frozen=True)
class CostSpec:
    """Static metering facts for a plugin — drives the usage/cost report.

    Free plugins inherit the default (one call costs one call, no quota, not
    paid) and need not declare anything. Override on plugins whose service
    meters usage: a hard per-day/per-month quota, a non-trivial rate limit, or
    paid credits. This metadata only *describes* a source so the CLI can report
    it; it never gates execution (that's ``requires_key``/``daily_limited``).
    """

    unit: str = "calls"  # "lookups/day" | "queries/mo" | "credits" | "calls/hr" | …
    per_call: float = 1.0  # units consumed per *successful* call
    daily_quota: int | None = None
    monthly_quota: int | None = None
    paid: bool = False  # service charges money / requires a paid plan
    note: str = ""  # free-text metering note (rate limit, tier, upgrade path)


class PluginContext(BaseModel):
    """Per-call runtime context injected by the runner. Never logged wholesale."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    timeout: float = 30.0
    proxy: str | None = None
    # Match production runner defaults; bare ``PluginContext()`` must not advertise
    # a bot-only UA when plugins fall back to a temporary client.
    user_agent: str = DEFAULT_BROWSER_UA
    # logical key name -> secret; populated from Settings. Never sent to the LLM.
    keys: dict[str, SecretStr] = Field(default_factory=dict)
    http: httpx.AsyncClient | None = None  # injected so tests can use respx
    # Optional observer tap, set per-turn by the Session. Opaque here so the
    # execution layer never imports orchestration; the tool closure (orchestration)
    # is what calls it. Plugins may also report sub-progress through it.
    progress: Any = None
    # When False (default), daily-quota'd free plugins are excluded from the
    # brain's tool list. Set True (CAIRN_ALLOW_DAILY_LIMITED=1) to opt in.
    allow_daily_limited: bool = False
    # When False (default), agentic tools are excluded from the brain's tool list
    # in investigate mode (set True in challenge mode, or CAIRN_ALLOW_AGENTIC=1).
    allow_agentic: bool = False
    # Agentic file/exec: the scratch workspace root (cwd is ALSO a root, computed
    # at call time). None when agentic mode is off / workspace unset.
    workspace: Path | None = None
    # v2 permission UI tap (PermissionUI protocol in cairn.execution.workspace),
    # set per-turn by the Session. v1 ships NullPermissionUI (denies out-of-
    # workspace without prompting). Opaque here so execution never imports
    # orchestration.
    permission: Any = None

    def key(self, logical: str) -> str | None:
        s = self.keys.get(logical)
        return s.get_secret_value() if s else None


class Entity(BaseModel):
    """A graph node captured from a tool result (ip, domain, email, asn, …).

    Carries optional evidence metadata (moat Pillar 2): ``confidence`` (how
    corroborated), ``provenance`` (chain-of-custody — source/time/hash/tool), and
    ``first_seen``. All default to ``None`` so the existing plugin construction
    sites (``Entity(type=…, value=…)`` / ``Entity(type=…, value=…, attrs=…)``) are
    unchanged; the text-mining converters populate them (see scrape_url /
    web_search / read_file). The graph store upgrades ``confidence`` as more
    independent sources corroborate the same node.
    """

    type: str
    value: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    confidence: Confidence | None = None
    provenance: Provenance | None = None
    first_seen: datetime | None = None


class PluginInput(BaseModel):
    """Base for plugin inputs. Subclass and add typed fields."""

    target: str


class PluginOutput(BaseModel):
    """Base for plugin outputs. Each plugin adds its own typed result fields."""

    source: str
    # Defaults to empty so a plugin can populate its structured fields first and
    # then synthesize the human/markdown summary from them (see the github/
    # hackertarget plugins). It must be set before returning upward.
    summary_markdown: str = ""
    entities: list[Entity] = Field(default_factory=list)
    # Optional dynamic metering signals read from the service's response (rate-
    # limit headers, remaining quota/credit balance) when the API exposes them.
    # None = unknown; the usage report then falls back to per-call accounting
    # from the plugin's :class:`CostSpec`. Never redacted (these are counts).
    rate_limit_remaining: int | None = None
    rate_limit_reset: int | None = None  # epoch seconds, when the rate window resets
    quota_remaining: int | None = None  # remaining within a daily/monthly quota
    credits_remaining: float | None = None  # credit balance (credit-metered services)


class BasePlugin[TIn: "PluginInput", TOut: "PluginOutput"](ABC):
    """Abstract base for all OSINT plugins."""

    name: ClassVar[str] = ""
    category: ClassVar[str] = ""  # "identity" | "infrastructure" | "web"
    requires_key: ClassVar[str | None] = None  # None = free; else logical key name
    # OPSEC: the trail this tool leaves on the target (moat Pillar 3, ported from
    # Claude-OSINT methodology §6.2). "low" = passive — the target never sees you
    # (CT logs, archives, third-party indexes, DNS via resolver, local file ops);
    # "medium" = a targeted probe the target's infra observes (HTTP GET to the
    # target, holehe/username presence checks); "high" = active scanning (port
    # scans, brute-force, fuzzing). Default "low" = passive-by-default. Override
    # on plugins that touch a target; the brain must justify medium/high touches.
    detectability: ClassVar[str] = "low"
    # True if the free tier has a hard per-DAY quota (not just rate-limiting).
    # Such plugins are excluded from the brain's tool list unless the user opts
    # in via CAIRN_ALLOW_DAILY_LIMITED=1. Rate-limited-only sources stay on.
    daily_limited: ClassVar[bool] = False
    # How this source's service meters usage — descriptive only, for the
    # ``cairn usage`` / ``/usage`` reports. Free plugins inherit the default.
    cost: ClassVar[CostSpec] = CostSpec()
    input_model: ClassVar[type[PluginInput]]
    output_model: ClassVar[type[PluginOutput]]

    @abstractmethod
    async def run(self, inp: TIn, ctx: PluginContext) -> TOut:
        """Execute the deterministic lookup and return a structured result."""
        raise NotImplementedError

    def available(self, ctx: PluginContext) -> bool:
        """Key gate only. The daily-limit preference is enforced by the registry."""
        return self.requires_key is None or ctx.key(self.requires_key) is not None

    def describe(self) -> str:
        return self.__doc__ or f"{self.name}: {self.category} OSINT lookup"


def plugin_tier(plugin: BasePlugin[Any, Any]) -> str:
    """Human label: ``free`` (no key, no daily quota), ``limited/day``, or ``keyed``."""
    if plugin.requires_key:
        return "keyed"
    return "limited/day" if plugin.daily_limited else "free"


def plugin_status(plugin: BasePlugin[Any, Any], ctx: PluginContext) -> str:
    """Why a plugin is or isn't in the brain's tool list right now."""
    if plugin.requires_key and ctx.key(plugin.requires_key) is None:
        return "hidden (set key)"
    if plugin.daily_limited and not ctx.allow_daily_limited:
        return "hidden (CAIRN_ALLOW_DAILY_LIMITED=0)"
    if plugin.category == "agentic" and not ctx.allow_agentic:
        return "hidden (investigate mode; use CAIRN_MODE=challenge)"
    return "active"


def cost_label(plugin: BasePlugin[Any, Any]) -> str:
    """Compact one-line readout of a plugin's :class:`CostSpec` for listings.

    Shows the metering that matters: quotas first (``50/day``), then a non-trivial
    unit (``credits`` / ``calls/hr``), and a ``paid`` flag. Free plugins with the
    default spec collapse to ``free``.
    """
    c: CostSpec = getattr(plugin, "cost", None) or CostSpec()
    parts: list[str] = []
    if c.daily_quota is not None:
        parts.append(f"{c.daily_quota}/day")
    if c.monthly_quota is not None:
        parts.append(f"{c.monthly_quota}/mo")
    if not parts and c.unit and c.unit != "calls":
        parts.append(c.unit)
    if c.paid:
        parts.append("paid")
    return " · ".join(parts) or "free"
