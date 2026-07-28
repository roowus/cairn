"""Top/bottom chrome lines for the zoned live-turn frame (UI overhaul U1).

The zoned layout renders each turn as a structured block sealed into scrollback:
a HEADER line (``cairn · model · mode · cumulative LLM tokens · tool calls · paid
spend``), a boxed TOOLS panel, a boxed ANSWER panel, and a FOOTER line
(``/help · Esc stop``). This module owns the header + footer; the panels are
composed in :mod:`cairn.interfaces.tui.live_turn`.

Pure presentation — it mirrors
:func:`cairn.interfaces.tui.statusline.render_statusline` (reads the session's
accumulators, never mutates them) but reshapes the same data into a top-of-turn
header. No untrusted payload, no audit path, safe to render at any point mid-turn.

v1 deliberately omits an ``in/context-window`` ratio: ``session.llm_usage`` is
*cumulative* across turns, so a ratio from it would mislead. The slot is reserved;
adding it later is a one-line change once a per-request input-token source exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from cairn import __version__
from cairn.interfaces.tui.statusline import _compact
from cairn.interfaces.tui.theme import theme

if TYPE_CHECKING:
    from cairn.orchestration.session import Session

__all__ = ["render_footer", "render_header"]


def render_header(session: Session) -> Text:
    """Top-of-turn header: ``cairn vX.Y.Z · model · mode · ↑in ↓out tok · N tools · paid``.

    Reads ``session.model_name``, ``session.llm_usage``, ``session.usage`` and
    ``session.settings.mode`` but never writes them. Mode ``challenge`` (active
    artifact analysis) is highlighted; ``investigate`` stays muted.
    """
    mode = getattr(getattr(session, "settings", None), "mode", "investigate")

    line = Text()
    line.append("cairn", style=theme.bold_accent)
    line.append(f" v{__version__}", style=theme.muted)
    line.append(" · ", style=theme.muted)
    line.append(session.model_name or "unknown", style=theme.accent)
    line.append(" · ", style=theme.muted)
    line.append(mode, style=theme.warn if mode == "challenge" else theme.muted)

    llm = getattr(session, "llm_usage", None)
    if llm is not None and (llm.input_tokens or llm.output_tokens):
        line.append(" · ", style=theme.muted)
        line.append(
            f"↑{_compact(llm.input_tokens)} ↓{_compact(llm.output_tokens)} tok",
            style=theme.muted,
        )

    usage = getattr(session, "usage", None)
    if usage is not None:
        calls = usage.total_calls()
        if calls:
            line.append(" · ", style=theme.muted)
            line.append(
                f"{_compact(calls)} tool{'s' if calls != 1 else ''}", style=theme.muted
            )
        paid = usage.total_paid_consumed()
        if paid > 0:
            unit = next((s.unit for s in usage.sources() if s.paid), "credits")
            line.append(" · ", style=theme.muted)
            line.append(f"{_compact(paid)} {unit}", style=theme.paid)
    return line


def render_footer() -> Text:
    """Bottom-of-turn footer: the two hints users reach for most."""
    line = Text()
    line.append("/help", style=theme.accent)
    line.append(" · ", style=theme.muted)
    line.append("Esc stop", style=theme.muted)
    return line
