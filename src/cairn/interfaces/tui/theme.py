"""Centralized Rich style tokens for the TUI (Phase 6 foundation).

The REPL/TUI scatter color literals (``[cyan]``, ``[dim]``, ``bold cyan`` …)
across many call sites. This module is the single source of truth, so a future
light/dark theme or accessibility tweak changes one place, not a dozen. Tokens
are :class:`rich.style.Style` objects on a frozen :class:`Theme`; the
module-level :data:`theme` singleton is what callers import.

Foundation only (Phase 6 Step 6.1). Adopting it at the existing literal sites is
Step 6.2 — a mechanical, render-identical swap sequenced separately so this
introduction stays reviewable on its own. Alternate themes (light/dark) are
deferred; v1 ships exactly this palette.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from rich.style import Style


@dataclass(frozen=True)
class Theme:
    """The TUI style palette; each field is a :class:`rich.style.Style`."""

    accent: Style = field(default_factory=lambda: Style(color="cyan"))
    bold_accent: Style = field(default_factory=lambda: Style(color="cyan", bold=True))
    muted: Style = field(default_factory=lambda: Style(dim=True))
    ok: Style = field(default_factory=lambda: Style(color="green"))
    err: Style = field(default_factory=lambda: Style(color="red"))
    warn: Style = field(default_factory=lambda: Style(color="yellow"))
    paid: Style = field(default_factory=lambda: Style(color="magenta"))
    border: Style = field(default_factory=lambda: Style(color="cyan"))
    prompt: Style = field(default_factory=lambda: Style(color="cyan", bold=True))
    thinking: Style = field(default_factory=lambda: Style(dim=True))
    tool_name: Style = field(default_factory=lambda: Style(color="cyan", bold=True))
    tool_target: Style = field(default_factory=lambda: Style(dim=True))

    def token_names(self) -> tuple[str, ...]:
        """Ordered field names — snapshot in tests to catch palette drift."""
        return tuple(f.name for f in fields(self))


# Module singleton — `from cairn.interfaces.tui.theme import theme`.
theme = Theme()
