"""Collapsed thinking accumulator for the live turn (UI overhaul U3).

The brain's reasoning (PydanticAI ``ThinkingPart``) arrives as ``ThinkingDelta``
events. v1 renders it **collapsed** — a one-line ``thinking ▸ (N lines)``
indicator — because the streaming ``Live`` region doesn't own stdin (no expand
key without widening the Esc/Ctrl-C watcher); a future fullscreen/alt-screen UI
can add the toggle. Mirrors :class:`~cairn.interfaces.tui.markdown_stream.MarkdownStream`'s
append/render/seal shape for symmetry, minus the markdown parsing.
"""

from __future__ import annotations

from rich.text import Text

__all__ = ["ThinkingStream"]

_DEFAULT_MAX_LINES = 200  # tail cap; thinking can be verbose


class ThinkingStream:
    """Accumulate thinking text; render a collapsed one-line count indicator."""

    def __init__(self, *, max_lines: int = _DEFAULT_MAX_LINES) -> None:
        self._lines: list[str] = []
        self._max_lines = max_lines

    def append(self, chunk: str) -> None:
        """Append one :class:`~cairn.orchestration.events.ThinkingDelta`'s text."""
        if not chunk:
            return
        for ln in chunk.splitlines():
            if ln.strip():
                self._lines.append(ln.strip())
        if len(self._lines) > self._max_lines:
            self._lines = self._lines[-self._max_lines :]

    @property
    def empty(self) -> bool:
        return not self._lines

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def render(self) -> Text:
        if self.empty:
            return Text("")
        return Text(f"thinking ▸ ({self.line_count} lines)", style="dim")

    def seal(self) -> Text:
        # Collapsed in v1 — sealed view is the same indicator.
        return self.render()
