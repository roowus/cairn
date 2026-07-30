"""Per-tool-call renderable cards for the live turn region.

A :class:`ToolCard` is keyed by ``tool_call_id`` and fed from **two independent
event sources** that both carry the same id — which is what makes correlation
robust under PydanticAI's default **parallel** tool execution (results land in
completion order, not emission order, and the same tool name can recur):

* the ``TurnEvent`` stream — ``ToolArgsStart`` (card appears), ``ToolExecStart``
  (running), ``ToolExecEnd`` (done fallback);
* the audited ``_tool`` closure's Progress hooks — ``on_tool_start`` (target),
  ``on_tool_end`` (status + excerpt).

A card morphs in place — pending ``▸`` → running spinner → done ``✓``/``✗`` with
excerpt — even while many tools run concurrently and complete out of order. The
closure stays the source of truth for target/excerpt (the same values the audit
log records); the card only renders them. Nothing here touches the hard-stop.

Transitions are idempotent and order-insensitive: whichever of the two sources
fires first advances the state; the second is a harmless no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.spinner import Spinner
from rich.text import Text

from cairn.interfaces.tui.theme import theme
from cairn.orchestration.progress import excerpt

__all__ = ["ToolCard"]

_PENDING = "pending"
_RUNNING = "running"
_DONE = "done"
_BODY_MAX_LINES = 6  # tail cap of streamed stdout shown in a card


@dataclass
class ToolCard:
    """One tool call's live status line, keyed by ``tool_call_id``."""

    tool_call_id: str
    tool_name: str
    target: str = ""
    excerpt: str = ""
    is_error: bool = False
    state: str = _PENDING
    body: list[str] = field(default_factory=list)
    _spinner: Spinner | None = field(default=None, repr=False)

    # --- stream-source transitions ---

    def mark_running(self) -> None:
        if self.state == _PENDING:
            self.state = _RUNNING

    # --- closure-source transitions (carry the real target/excerpt) ---

    def set_target(self, target: str) -> None:
        if target:
            self.target = target
        # the closure starting == the tool is running
        self.mark_running()

    def finish(self, status: str, summary: str, error: str | None) -> None:
        """Finalize from the closure's ``on_tool_end`` (authoritative excerpt)."""
        if self.state == _DONE:
            return
        self.state = _DONE
        self.is_error = status != "ok"
        self.excerpt = excerpt(error or summary)

    def finish_fallback(self, is_error: bool) -> None:
        """Safety net from the stream's ``ToolExecEnd`` if the closure hook missed."""
        if self.state == _DONE:
            return
        self.state = _DONE
        self.is_error = is_error

    def append_body(self, line: str) -> None:
        """Append a streamed stdout line (tail-capped) for live display."""
        if line.strip():
            self.body.append(line)
            if len(self.body) > _BODY_MAX_LINES:
                del self.body[: len(self.body) - _BODY_MAX_LINES]

    # --- rendering ---

    @property
    def done(self) -> bool:
        return self.state == _DONE

    @property
    def active(self) -> bool:
        """Pending (model composing the call) or running — i.e. still in flight."""
        return self.state in (_PENDING, _RUNNING)

    def render(self) -> RenderableType:
        if self.state == _RUNNING:
            if self._spinner is None:
                self._spinner = Spinner("dots")
            label = Text(f"  {self.tool_name}", style=theme.accent)
            if self.target:
                label.append(f" ({self.target})", style=theme.muted)
            self._spinner.text = label  # stable instance → smooth animation
            head: RenderableType = self._spinner
        else:
            line = Text()
            if self.state == _DONE:
                mark, mstyle = ("✓", theme.ok) if not self.is_error else ("✗", theme.err)
                line.append(f"  {mark} ", style=mstyle)
                line.append(self.tool_name, style=theme.accent)
                if self.target:
                    line.append(f" ({self.target})", style=theme.muted)
                if self.excerpt:
                    line.append(f" — {self.excerpt}", style=theme.muted)
            else:  # pending — model composing the call
                line.append("  ▸ ", style=theme.bold_accent)
                line.append(self.tool_name, style=theme.accent)
            head = line
        if self.body:
            # Streamed stdout tail, shown under the status line while/after the run.
            return Group(head, *(Text(f"    │ {ln}", style=theme.muted) for ln in self.body))
        return head
