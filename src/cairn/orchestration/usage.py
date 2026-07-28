"""Usage & cost accounting.

Tracks per-source consumption — call counts, wall-clock time, and units
consumed — plus any dynamic metering signals a plugin reads from a response
(rate-limit headers, remaining quota / credit balance). The tool closure in
:mod:`cairn.orchestration.tool_adapter` is the single source of truth: it times
each call and feeds the tracker.

This is an **accountant only** — it never influences execution. It cannot alter
tool arguments, suppress calls, or change the answer. It is the cost/quota
analogue of :class:`~cairn.orchestration.progress.Progress`.

Two scopes:

- **Live (session)**: a :class:`UsageTracker` accumulates across a session —
  REPL lifetime, or one ``cairn search`` run. Surfaced by ``/usage`` in the REPL
  and the post-run summary in headless mode.
- **Historical (persisted)**: each call's ``elapsed_ms`` and a usage snapshot
  are written to the append-only ``audit_log`` (by
  :class:`~cairn.orchestration.audit.AuditWriter`). :func:`aggregate_history`
  reconstructs per-source totals from that log — this powers ``cairn usage``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cairn.execution.base import BasePlugin, CostSpec, PluginOutput, plugin_tier

if TYPE_CHECKING:
    from cairn.storage.db import Database


@dataclass
class SourceUsage:
    """Accumulated usage for one plugin/source."""

    name: str
    category: str = ""
    tier: str = "free"  # free | limited/day | keyed
    calls: int = 0
    ok: int = 0
    errors: int = 0
    elapsed_ms: float = 0.0
    consumed: float = 0.0  # total units consumed (successful calls * per_call)
    unit: str = "calls"
    paid: bool = False
    daily_quota: int | None = None
    monthly_quota: int | None = None
    note: str = ""
    # Last-known dynamic values — overlaid from each response that reports them.
    rate_remaining: int | None = None
    rate_reset: int | None = None  # epoch seconds
    quota_remaining: int | None = None
    credits_remaining: float | None = None

    @property
    def is_metered(self) -> bool:
        """A quota'd or paid source — the ones the cost report cares about most."""
        return self.paid or self.daily_quota is not None or self.monthly_quota is not None

    def quota_str(self) -> str:
        """Human readout of the static quota, e.g. ``50/day · 2000/mo``."""
        parts: list[str] = []
        if self.daily_quota is not None:
            parts.append(f"{self.daily_quota}/day")
        if self.monthly_quota is not None:
            parts.append(f"{self.monthly_quota}/mo")
        return " · ".join(parts) or "—"


@dataclass
class UsageTracker:
    """Accumulates per-source usage across a session (observer only)."""

    _sources: dict[str, SourceUsage] = field(default_factory=dict)

    def record(
        self,
        plugin: BasePlugin[Any, Any],
        *,
        elapsed_ms: float,
        status: str = "ok",
        output: PluginOutput | None = None,
    ) -> SourceUsage:
        """Account one tool call. Returns the updated :class:`SourceUsage`."""
        cost: CostSpec = getattr(plugin, "cost", None) or CostSpec()
        name = getattr(plugin, "name", "?")
        su = self._sources.get(name)
        if su is None:
            su = SourceUsage(
                name=name,
                category=getattr(plugin, "category", ""),
                tier=plugin_tier(plugin),
                unit=cost.unit,
                paid=cost.paid,
                daily_quota=cost.daily_quota,
                monthly_quota=cost.monthly_quota,
                note=cost.note,
            )
            self._sources[name] = su
        su.calls += 1
        if status == "ok":
            su.ok += 1
            su.consumed += cost.per_call
        else:
            su.errors += 1
        su.elapsed_ms += elapsed_ms
        if output is not None:
            if output.rate_limit_remaining is not None:
                su.rate_remaining = output.rate_limit_remaining
            if output.rate_limit_reset is not None:
                su.rate_reset = output.rate_limit_reset
            if output.quota_remaining is not None:
                su.quota_remaining = output.quota_remaining
            if output.credits_remaining is not None:
                su.credits_remaining = output.credits_remaining
        return su

    def sources(self) -> list[SourceUsage]:
        """All sources seen, busiest first (ties broken by name)."""
        return sorted(self._sources.values(), key=lambda s: (-s.calls, s.name))

    def checkpoint(self) -> dict[str, tuple[int, float, float]]:
        """Snapshot ``(calls, elapsed_ms, consumed)`` per source — pass to :meth:`delta`."""
        return {n: (s.calls, s.elapsed_ms, s.consumed) for n, s in self._sources.items()}

    def delta(self, since: dict[str, tuple[int, float, float]]) -> list[SourceUsage]:
        """Sources that advanced since a :meth:`checkpoint`, with incremental values.

        Used for the REPL turn-end line (what *this* turn cost) without mutating
        the live accumulators. Dynamic values (rate/quota remaining) are carried
        through since they're point-in-time, not cumulative.
        """
        out: list[SourceUsage] = []
        for name, su in self._sources.items():
            prev = since.get(name, (0, 0.0, 0.0))
            d_calls = su.calls - prev[0]
            if d_calls <= 0:
                continue
            d = SourceUsage(
                name=name,
                category=su.category,
                tier=su.tier,
                calls=d_calls,
                # ok/errors deltas aren't tracked in the checkpoint; the line
                # uses calls/time/consumed only, so these stay coarse here.
                ok=d_calls,
                elapsed_ms=su.elapsed_ms - prev[1],
                consumed=su.consumed - prev[2],
                unit=su.unit,
                paid=su.paid,
                daily_quota=su.daily_quota,
                monthly_quota=su.monthly_quota,
                note=su.note,
                rate_remaining=su.rate_remaining,
                rate_reset=su.rate_reset,
                quota_remaining=su.quota_remaining,
                credits_remaining=su.credits_remaining,
            )
            out.append(d)
        return sorted(out, key=lambda s: (-s.calls, s.name))

    def total_calls(self) -> int:
        return sum(s.calls for s in self._sources.values())

    def total_elapsed_ms(self) -> float:
        return sum(s.elapsed_ms for s in self._sources.values())

    def total_paid_consumed(self) -> float:
        """Units consumed on paid sources this session (credits, etc.)."""
        return sum(s.consumed for s in self._sources.values() if s.paid)

    def paid_sources(self) -> list[SourceUsage]:
        return [s for s in self._sources.values() if s.paid]


def snapshot(su: SourceUsage, *, per_call_consumed: float | None = None) -> dict[str, Any]:
    """A JSON-serializable, secret-free per-call snapshot for the audit log.

    ``consumed`` here must be the **per-call** delta (what *this* call cost), not
    the cumulative ``su.consumed`` — otherwise :func:`aggregate_history` sums
    running totals across rows and over-counts. Cumulative point-in-time fields
    (rate/quota/credits remaining) are stored as-is; aggregation carries the
    last-known value forward.
    """
    return {
        "unit": su.unit,
        "consumed": round(per_call_consumed if per_call_consumed is not None else su.consumed, 4),
        "tier": su.tier,
        "paid": su.paid,
        "daily_quota": su.daily_quota,
        "monthly_quota": su.monthly_quota,
        "rate_remaining": su.rate_remaining,
        "rate_reset": su.rate_reset,
        "quota_remaining": su.quota_remaining,
        "credits_remaining": su.credits_remaining,
    }


def aggregate_history(db: Database) -> list[SourceUsage]:
    """Reconstruct per-source usage totals from the append-only ``audit_log``.

    Sums call counts and elapsed time, and decodes the per-call ``usage_json``
    snapshots (accumulating ``consumed``; carrying forward the last-known
    dynamic values). Sources never seen live (e.g. prior runs) still appear.
    """
    rows = db.execute(
        "SELECT tool, status, elapsed_ms, usage_json FROM audit_log"
    ).fetchall()
    agg: dict[str, SourceUsage] = {}
    for r in rows:
        name = r["tool"]
        su = agg.get(name)
        if su is None:
            su = SourceUsage(name=name)
            agg[name] = su
        su.calls += 1
        if r["status"] == "ok":
            su.ok += 1
        else:
            su.errors += 1
        su.elapsed_ms += r["elapsed_ms"] or 0
        raw = r["usage_json"]
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if d.get("unit"):
            su.unit = d["unit"]
        if d.get("tier"):
            su.tier = d["tier"]
        su.paid = su.paid or bool(d.get("paid"))
        if d.get("daily_quota") is not None:
            su.daily_quota = d["daily_quota"]
        if d.get("monthly_quota") is not None:
            su.monthly_quota = d["monthly_quota"]
        su.consumed += float(d.get("consumed") or 0)
        for k in ("rate_remaining", "quota_remaining", "credits_remaining"):
            v = d.get(k)
            if v is not None:
                setattr(su, k, v)  # last known wins
    return sorted(agg.values(), key=lambda s: (-s.calls, s.name))
