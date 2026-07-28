"""Per-turn Rich ``Live`` region: streams the answer and shows tool cards inline.

Owns the structural invariant documented in :mod:`cairn.interfaces.tui`: a
``Live(transient=False)`` region is open **only** while the turn runs and input is
idle. ``transient=False`` means Rich seals the final frame into scrollback on
exit — so the streamed answer persists in history exactly like ``pi`` / Claude
Code, instead of vanishing when the region closes.

Tool calls render as in-place :class:`~cairn.interfaces.tui.cards.ToolCard`s keyed
by ``tool_call_id`` (the only robust key under PydanticAI's default parallel tool
execution — completion order ≠ emission order, and a tool name can recur). Each
card morphs ``▸ pending → spinner running → ✓/✗ done`` and is fed from BOTH the
``TurnEvent`` stream and the audited closure's Progress hooks, which share the same
``tool_call_id``. The closure stays the source of truth for target/excerpt (the
same values the audit log records); the stream only adds the lifecycle. The
hard-stop is untouched.

On a non-TTY pipe Rich writes a clean final frame instead of a differential
repaint, so ``cairn search`` output stays pipe-friendly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.text import Text

from cairn.interfaces.tui.cards import ToolCard
from cairn.interfaces.tui.markdown_stream import MarkdownStream
from cairn.interfaces.tui.statusline import render_statusline
from cairn.orchestration.events import TextDelta, ToolArgsStart, ToolExecEnd, ToolExecStart
from cairn.orchestration.progress import Progress

if TYPE_CHECKING:
    from cairn.orchestration.events import TurnEvent
    from cairn.orchestration.session import Session

__all__ = ["run_turn"]

_REFRESH_PER_SECOND = 30  # smooth re-flow + spinner animation; MarkdownStream throttles the parse


class _Composer:
    """Holds insertion-ordered tool cards + streaming Markdown; composes the Live frame."""

    def __init__(
        self, session: Session, *, status_hints: bool = False, show_status: bool = True
    ) -> None:
        self._session = session
        self._status_hints = status_hints
        self._show_status = show_status
        self.cards: dict[str, ToolCard] = {}
        self.md = MarkdownStream()

    def _statusline(self) -> RenderableType | None:
        if not self._show_status:
            return None
        return render_statusline(self._session, hints=self._status_hints)

    def _card(self, tool_call_id: str, tool_name: str = "") -> ToolCard:
        card = self.cards.get(tool_call_id)
        if card is None:
            card = ToolCard(tool_call_id=tool_call_id, tool_name=tool_name)
            self.cards[tool_call_id] = card
        elif tool_name and not card.tool_name:
            card.tool_name = tool_name
        return card

    # --- stream-source transitions (lifecycle only) ---

    def args_started(self, tool_call_id: str, tool_name: str) -> None:
        # Creating the card (default PENDING state) is the whole effect — it appears
        # as soon as the model starts composing the call, before it runs.
        self._card(tool_call_id, tool_name)

    def exec_started(self, tool_call_id: str, tool_name: str) -> None:
        self._card(tool_call_id, tool_name).mark_running()

    def exec_ended(self, tool_call_id: str, is_error: bool) -> None:
        card = self.cards.get(tool_call_id)
        if card is not None:
            card.finish_fallback(is_error)

    # --- closure-source transitions (carry the real target/excerpt) ---

    def tool_started(self, tool_call_id: str, name: str, target: str) -> None:
        self._card(tool_call_id, name).set_target(target)

    def tool_finished(
        self,
        tool_call_id: str,
        name: str,
        target: str,
        status: str,
        summary: str,
        error: str | None,
    ) -> None:
        card = self.cards.get(tool_call_id)
        if card is None:
            # Closure fired without a prior stream event (shouldn't normally happen) —
            # synthesize the card from the hook's own name/target so the call is visible.
            card = self._card(tool_call_id, name)
            card.set_target(target)
        card.finish(status, summary, error)

    # --- frame composition ---

    def _frame(self, body: RenderableType) -> RenderableType:
        parts: list[RenderableType] = [*(c.render() for c in self.cards.values()), body]
        status = self._statusline()
        if status is not None:
            parts.append(status)
        return Group(*parts)

    def render(self) -> RenderableType:
        if not self.md.empty:
            body: RenderableType = self.md.render()
        elif not self.cards:
            body = Text("⠋ thinking…", style="dim")
        else:
            body = Text("")  # tool cards (some running) provide the activity
        return self._frame(body)

    def sealed(self) -> RenderableType:
        """Final frame for ``Live(transient=False)``: cards + sealed Markdown +
        the statusline, which persists in scrollback like ``pi``'s bottom bar
        (REPL only — headless suppresses it via ``show_status=False`` and keeps
        its own usage section, avoiding a non-TTY run-together)."""
        return self._frame(self.md.seal())


class _ToolRecorder(Progress):
    """Bridges the closure's Progress hooks into the Live composer (by tool_call_id)."""

    def __init__(self, composer: _Composer, live: Live) -> None:
        self._composer = composer
        self._live = live

    def on_tool_start(
        self, name: str, target: str, params: dict[str, Any], tool_call_id: str
    ) -> None:
        self._composer.tool_started(tool_call_id, name, target)
        self._live.update(self._composer.render())

    def on_tool_end(
        self,
        name: str,
        target: str,
        status: str,
        summary: str,
        error: str | None,
        tool_call_id: str,
    ) -> None:
        self._composer.tool_finished(tool_call_id, name, target, status, summary, error)
        self._live.update(self._composer.render())


async def run_turn(
    session: Session,
    prompt: str,
    *,
    console: Console,
    model: Any | None = None,
    show_status: bool = True,
    status_hints: bool = False,
) -> str:
    """Run one turn under a streaming ``Live`` region; return the final output.

    Drives :meth:`session.iter_turn <cairn.orchestration.session.Session.iter_turn>`,
    appending ``TextDelta``s to the streaming-Markdown accumulator and advancing
    ``ToolCard``s as calls compose, run, and finish. The statusline
    (:func:`~cairn.interfaces.tui.statusline.render_statusline`) rides as the last
    row and is sealed with the frame (``show_status=False`` suppresses it entirely
    — headless keeps its own usage section; ``status_hints=True`` adds the REPL's
    ``/help · Esc stop`` tail). On success returns
    :attr:`session.last_output <cairn.orchestration.session.Session.last_output>`;
    on cancel/exception the ``Live`` region closes (frame sealed/cleared) and the
    error propagates for the caller (REPL/headless) to report.
    """
    composer = _Composer(session, status_hints=status_hints, show_status=show_status)
    with Live(
        composer.render(),
        console=console,
        transient=False,
        refresh_per_second=_REFRESH_PER_SECOND,
    ) as live:
        recorder = _ToolRecorder(composer, live)
        async for ev in session.iter_turn(prompt, progress=recorder, model=model):
            _apply_event(composer, ev)
            live.update(composer.render())
        # Turn done: seal the full answer (trim/cap dropped) with the statusline,
        # which persists in scrollback until the next turn.
        live.update(composer.sealed())
    return session.last_output


def _apply_event(composer: _Composer, ev: TurnEvent) -> None:
    """Fold one stream TurnEvent into the composer.

    Tool-arg deltas (``ToolArgsDelta``) and thinking (``Thinking*``) are deferred
    to later phases; tool target/excerpt come from the closure's Progress hooks.
    """
    if isinstance(ev, TextDelta):
        composer.md.append(ev.text)
    elif isinstance(ev, ToolArgsStart):
        composer.args_started(ev.tool_call_id, ev.tool_name)
    elif isinstance(ev, ToolExecStart):
        composer.exec_started(ev.tool_call_id, ev.tool_name)
    elif isinstance(ev, ToolExecEnd):
        composer.exec_ended(ev.tool_call_id, ev.is_error)
