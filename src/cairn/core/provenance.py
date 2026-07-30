"""Evidence-grade data models: provenance, confidence, severity, findings.

These are the OSINT-native upgrades that turn Cairn's flat "entity + summary"
outputs into an **evidence locker**. In OSINT, *where a fact came from and when*
matters as much as the fact (credibility, admissibility, reproducibility), and a
flat assertion is worthless next to one tagged with source, timestamp, hash, and a
calibrated confidence. A coding agent treats tool output as ephemeral context; an
investigator treats it as evidence.

Models (mirrored from the Claude-OSINT tradecraft — methodology §2/§3/§4 — which
is the concrete spec for Cairn's moat Pillars 2 and 4, see docs/strategy.md):

- :class:`Confidence` — tentative / firm / confirmed (+ the rule-of-three
  aggregation that promotes an entity as more sources corroborate it).
- :class:`Severity` — info / low / medium / high / critical (the findings rubric).
- :class:`Provenance` — the chain-of-custody record on an :class:`Entity`
  (source URL, UTC capture time, raw-bytes SHA-256, producing tool, archive ref).
- :class:`Evidence` / :class:`Finding` — the portable, asset-management-tool-shaped
  finding a technique emits (typed asset_key, category, severity, confidence,
  evidence block, references, remediation).

Pure stdlib + Pydantic. This is the ``core`` layer — **no** imports from
``orchestration`` / ``execution`` / ``subprocess`` / ``socket`` (the layering
test AST-walks ``core`` too).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Raw-evidence bodies are capped so a captured HTTP response / file snippet can't
# balloon a finding (and can't dump a whole secret into a report). Mirrors the
# "raw truncated to 2 KiB" rule from Claude-OSINT methodology §4.
_MAX_RAW_BYTES = 2048


def utc_now() -> datetime:
    """Timezone-aware UTC ``now``. Centralized so capture timestamps are always
    real UTC (local time creates correlation bugs — methodology §14 anti-pattern)."""
    return datetime.now(UTC)


def _truncate_raw(raw: str) -> str:
    return raw if len(raw.encode("utf-8", "replace")) <= _MAX_RAW_BYTES else raw[:_MAX_RAW_BYTES]


class Confidence(StrEnum):
    """How well-corroborated a fact is (methodology §2).

    - ``tentative`` — plausible from indirect/single-source evidence; unverified.
    - ``firm`` — directly observed, OR corroborated by >=2 independent sources.
    - ``confirmed`` — multiple independent corroborations or directly verified
      (e.g. a read-only credential validator returned success). Never claimed on
      single-source evidence; downgrade when in doubt.
    """

    TENTATIVE = "tentative"
    FIRM = "firm"
    CONFIRMED = "confirmed"

    @classmethod
    def from_sources(cls, n: int) -> Confidence:
        """Promote confidence by independent-source count (the rule-of-three seed).

        0-1 sources -> tentative; >=2 -> firm. ``confirmed`` is *not* earned by count
        alone — it requires direct verification, so callers set it explicitly.
        """
        return cls.FIRM if n >= 2 else cls.TENTATIVE

    @classmethod
    def aggregate(cls, confidences: list[Confidence]) -> Confidence:
        """Combine per-source confidences into one. The max wins, but ``confirmed``
        still needs a genuinely confirming signal (max of the inputs) — aggregation
        never *manufactures* confirmed from tentatives alone."""
        if not confidences:
            return cls.TENTATIVE
        order = {cls.TENTATIVE: 0, cls.FIRM: 1, cls.CONFIRMED: 2}
        best = max(confidences, key=lambda c: order[c])
        return best


class Severity(StrEnum):
    """Operational severity (methodology §9). Ordered low->critical; ``>=`` works."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def _rank(cls) -> dict[Severity, int]:
        return {cls.INFO: 0, cls.LOW: 1, cls.MEDIUM: 2, cls.HIGH: 3, cls.CRITICAL: 4}

    def __ge__(self, other: object) -> bool:
        return isinstance(other, Severity) and self._rank()[self] >= self._rank()[other]

    def __gt__(self, other: object) -> bool:
        return isinstance(other, Severity) and self._rank()[self] > self._rank()[other]

    def __le__(self, other: object) -> bool:
        return isinstance(other, Severity) and self._rank()[self] <= self._rank()[other]

    def __lt__(self, other: object) -> bool:
        return isinstance(other, Severity) and self._rank()[self] < self._rank()[other]

    @classmethod
    def escalate(cls, base: Severity, to: Severity) -> Severity:
        """One-way escalation only (e.g. HSTS-missing on /login: MED→HIGH). Never
        downgrades — a higher ``to`` wins, a lower one is ignored."""
        return base if base >= to else to


class Provenance(BaseModel):
    """Chain-of-custody for an :class:`~cairn.execution.base.Entity`.

    Immutable intent: when an entity is mined from a URL it records where, when,
    and the hash of the raw bytes that produced it, so a since-deleted tweet or a
    tampered page is still citable. ``tool`` is always known; the rest is best-
    effort (a regex-mined phone has no source URL).
    """

    tool: str
    source_url: str | None = None
    captured_at: datetime | None = None
    raw_sha256: str | None = None
    archive_ref: str | None = None  # Wayback / archive.today snapshot, when saved


class Evidence(BaseModel):
    """The evidence block of a :class:`Finding` (methodology §3/§4)."""

    url: str | None = None
    timestamp: datetime | None = None
    sha256: str | None = None
    raw: str = ""

    @field_validator("raw", mode="before")
    @classmethod
    def _cap_raw(cls, v: object) -> str:
        # raw bodies are capped (2 KiB) so a captured response can't balloon a
        # finding or dump a whole secret into a report (methodology §4).
        return _truncate_raw(v) if isinstance(v, str) else ""


class Finding(BaseModel):
    """A single technique's output, shaped to drop into any findings store.

    Mirrors Claude-OSINT's output schema (methodology §3 / architecture.md) — the
    portable unit an ASM platform, ticket, or ``to_provenance_report()`` consumes.
    """

    module: str  # the plugin/technique that discovered it
    asset_key: str  # typed key, e.g. "sub:api.example.com" (see core/assets.py)
    category: str  # e.g. SECRET_LEAK, OPEN_GRAPHQL_API, SSO_EXPOSURE
    severity: Severity = Severity.INFO
    confidence: Confidence = Confidence.TENTATIVE
    title: str
    description: str = ""
    evidence: Evidence = Field(default_factory=Evidence)
    references: list[str] = Field(default_factory=list)
    remediation: str = ""
    id: str = ""  # stable hash if unset (see make_id)

    def model_post_init(self, __context: Any) -> None:
        # Backfill a stable id from the identifying fields so the same finding is
        # dedup-able across runs. Explicit ids (passed in) are preserved.
        if not self.id:
            object.__setattr__(
                self,
                "id",
                make_id(self.module, self.asset_key, self.category, self.title),
            )

    def to_markdown(self) -> str:
        """One-finding card for reports / wrapped summaries."""
        sev = self.severity.value.upper()
        conf = self.confidence.value
        lines = [
            f"### [{sev}] {self.title}",
            (
                f"`{self.asset_key}` · category `{self.category}` · "
                f"confidence **{conf}** · via `{self.module}`"
            ),
        ]
        if self.description:
            lines.append(self.description)
        ev = self.evidence
        ev_bits: list[str] = []
        if ev.url:
            ev_bits.append(f"url: {ev.url}")
        if ev.timestamp:
            ev_bits.append(f"captured: {ev.timestamp.isoformat()}")
        if ev.sha256:
            ev_bits.append(f"sha256: `{ev.sha256}`")
        if ev_bits:
            lines.append("- " + " · ".join(ev_bits))
        if self.remediation:
            lines.append(f"- **remediation**: {self.remediation}")
        return "\n".join(lines)


def make_id(*parts: str) -> str:
    """Deterministic 12-char id from the identifying parts (module/asset/category/
    title). Same inputs → same id → findings dedup across runs/sessions."""
    h = hashlib.sha256("|".join(p.strip() for p in parts if p).encode("utf-8")).hexdigest()
    return h[:12]
