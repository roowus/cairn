"""Persistent statusline for the live turn region.

A compact one-line readout rendered as the last row of the ``Live`` frame and
sealed with it (so it persists in scrollback like ``pi`` / Claude Code's bottom
bar). It shows the live model, cumulative LLM tokens (merged per turn from
PydanticAI's :class:`~pydantic_ai.usage.RunUsage`), cumulative OSINT tool calls
and paid-source spend (from :class:`~cairn.orchestration.usage.UsageTracker`),
and — in the REPL only — the two hints users reach for most.

Pure presentation: it reads the session's accumulators but never mutates them,
touches no audit path, and carries no untrusted payload, so it is safe to render
at any point mid-turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from cairn.interfaces.tui.theme import theme

if TYPE_CHECKING:
    from cairn.orchestration.session import Session

__all__ = ["render_statusline"]


def _compact(n: float) -> str:
    """``1234`` → ``1.2k``, ``1_500_000`` → ``1.5M``; small numbers stay plain.

    The ``k`` band is promoted to ``1.0M`` once it would round up to ``1000.0k``
    (e.g. ``999_999``), avoiding the awkward ``1000.0k`` label.
    """
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        k = n / 1_000
        if k >= 999.95:  # :.1f would round up to 1000.0k — promote to 1.0M
            return "1.0M"
        return f"{k:.1f}k"
    return f"{int(n)}"


def render_statusline(session: Session, *, hints: bool = False) -> Text:
    """Render the statusline as a Rich :class:`~rich.text.Text`.

    ``hints`` appends the REPL-only ``/help · Esc stop`` tail (omitted for
    headless output, where it would only noise up a piped answer). Reads
    :attr:`Session.llm_usage` and :attr:`Session.usage` but never writes them.
    """
    line = Text()
    line.append(session.model_name or "cairn", style=theme.bold_accent)

    llm = getattr(session, "llm_usage", None)
    if llm is not None and (llm.input_tokens or llm.output_tokens):
        line.append(" · ", style=theme.muted)
        tokens = f"↑{_compact(llm.input_tokens)} ↓{_compact(llm.output_tokens)} tok"
        line.append(tokens, style=theme.muted)

    usage = getattr(session, "usage", None)
    if usage is not None:
        calls = usage.total_calls()
        if calls:
            line.append(" · ", style=theme.muted)
            line.append(f"{_compact(calls)} tool{'s' if calls != 1 else ''}", style=theme.muted)
        paid = usage.total_paid_consumed()
        if paid > 0:
            unit = next((s.unit for s in usage.sources() if s.paid), "credits")
            line.append(" · ", style=theme.muted)
            line.append(f"{_compact(paid)} {unit}", style=theme.paid)

    if hints:
        line.append(" · ", style=theme.muted)
        line.append("/help", style=theme.accent)
        line.append(" · ", style=theme.muted)
        line.append("Esc stop", style=theme.muted)
    return line
