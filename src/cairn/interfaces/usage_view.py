"""Rich renderers for the usage/cost report.

Shared by the REPL (``/usage``, turn-end line), headless (``cairn search``
post-run summary), and the ``cairn usage`` command. Pure presentation over
:class:`~cairn.orchestration.usage.SourceUsage` — no execution logic here.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from cairn.orchestration.usage import SourceUsage


def _fmt_time(ms: float) -> str:
    s = ms / 1000.0
    if s >= 60:
        return f"{s / 60:.1f}m"
    if s >= 10:
        return f"{s:.0f}s"
    return f"{s:.1f}s"


def _remaining(su: SourceUsage) -> str:
    """Best remaining-quota/rate readout: dynamic from the response if known, else static."""
    if su.quota_remaining is not None:
        return f"{su.quota_remaining} left"
    if su.credits_remaining is not None:
        return f"{su.credits_remaining:g} credits"
    if su.rate_remaining is not None:
        return f"{su.rate_remaining} left"
    quota = su.quota_str()
    return "" if quota == "—" else quota


def _used(su: SourceUsage) -> str:
    if not su.ok:
        return "—"
    unit = su.unit
    # "calls" reads fine; other units are metered (credits, lookups/day, …)
    if su.consumed == int(su.consumed):
        return f"{int(su.consumed)} {unit}"
    return f"{su.consumed:g} {unit}"


def build_usage_table(
    sources: list[SourceUsage],
    *,
    title: str = "Usage",
    only_metered: bool = False,
) -> Table:
    """A Rich table of per-source usage. Set ``only_metered`` to show just paid/quota'd sources."""
    rows = [s for s in sources if (s.is_metered or not only_metered)]
    table = Table(title=title, show_header=True, header_style="bold", box=None)
    table.add_column("source", style="cyan", no_wrap=True)
    table.add_column("tier", style="yellow")
    table.add_column("calls", justify="right")
    table.add_column("time", justify="right", style="dim")
    table.add_column("used", justify="right")
    table.add_column("quota / remaining", style="magenta")
    table.add_column("paid?", justify="center")
    if not rows:
        table.add_row("[dim]no tool calls recorded yet[/dim]")
        return table
    for s in rows:
        table.add_row(
            s.name,
            s.tier,
            f"{s.ok}" + (f" (+{s.errors}✗)" if s.errors else ""),
            _fmt_time(s.elapsed_ms),
            _used(s),
            _remaining(s) or su_or_dash(s),
            "$" if s.paid else "",
        )
    return table


def su_or_dash(su: SourceUsage) -> str:
    return su.quota_str() if su.is_metered else "—"


def usage_line(sources: list[SourceUsage]) -> str:
    """Compact one-liner for the REPL turn-end / headless post-run summary."""
    calls = sum(s.calls for s in sources)
    ms = sum(s.elapsed_ms for s in sources)
    paid = sum(s.consumed for s in sources if s.paid)
    bits = [f"{calls} tool call(s)", _fmt_time(ms)]
    if paid:
        # show the paid unit of the first paid source for context
        unit = next((s.unit for s in sources if s.paid and s.consumed), "credits")
        bits.append(f"{int(paid) if paid == int(paid) else round(paid, 2)} {unit} used (paid)")
    limited = [s for s in sources if s.quota_remaining == 0]
    if limited:
        bits.append("quota hit: " + ", ".join(s.name for s in limited))
    return " · ".join(bits)


def render_usage(console: Console, sources: list[SourceUsage], *, title: str = "Usage") -> None:
    """Print the metered-sources table, then a totals line."""
    metered = [s for s in sources if s.is_metered]
    if metered:
        console.print(build_usage_table(metered, title=title + " — metered/paid sources"))
    console.print(f"[dim]{usage_line(sources)}[/dim]")
