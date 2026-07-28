"""Throttled streaming-Markdown accumulator for the per-turn ``Live`` region.

The brain's answer arrives as many small :class:`~cairn.orchestration.events.TextDelta`
chunks. Re-parsing and re-flowing :class:`rich.markdown.Markdown` on every token
flickers and burns CPU, so this module does what ``pi``'s renderer does:

* **throttle** — re-lex at most every ``min_interval`` seconds (≈32 ms ≈ 30 fps);
  tokens that arrive between renders coalesce into the next one.
* **anti-flicker** — drop a lone trailing ``\\`\\`\\``` fence so a half-typed code
  block does not visibly open and snap shut on every token.
* **dedupe** — skip the parse when the (trimmed) buffer is unchanged since last time.
* **cap** — while streaming, render only a tail window so a runaway answer can't
  wedge the re-lex; :meth:`MarkdownStream.seal` does one full render at turn end.

This module only ever consumes Cairn's stable ``TurnEvent`` (text); it never sees a
PydanticAI type and never touches the hard-stop (no tool execution, no payloads).
The expensive operation here is Markdown *parsing*; width-sensitive re-flow happens
later at console-render time inside Rich, so the cache is keyed on the trimmed text
alone (a width key would only cause needless re-parses on terminal jitter).
"""

from __future__ import annotations

import time

from rich.markdown import Markdown

__all__ = ["MarkdownStream", "trim_trailing_fence"]

#: Default re-lex interval ≈ 30 fps. Tuned for smooth streaming without re-parsing
#: every single token (the parse, not the re-flow, is the cost).
DEFAULT_MIN_INTERVAL = 0.032

#: While streaming, render at most this many trailing characters so a very long
#: answer can't make the per-frame re-lex pathologically slow. ``seal()`` drops it.
DEFAULT_MAX_STREAM_CHARS = 4096

_FENCE = "```"


def trim_trailing_fence(text: str) -> str:
    """Remove the last ``\\`\\`\\``` fence when code blocks are left unclosed.

    While the model types a code block, the buffer intermittently holds an *odd*
    number of fences (opener present, closer not yet emitted). Rich would render
    everything after the opener as a code block, then snap back to prose when the
    closer lands — that snap is the flicker. Dropping the trailing opener renders
    the in-progress code as plain prose until the block actually closes.
    """
    if text.count(_FENCE) % 2 == 1:
        idx = text.rfind(_FENCE)
        if idx != -1:
            return text[:idx] + text[idx + len(_FENCE) :]
    return text


class MarkdownStream:
    """Accumulate streaming text and hand back a throttled ``Markdown`` renderable."""

    def __init__(
        self,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        max_stream_chars: int | None = DEFAULT_MAX_STREAM_CHARS,
    ) -> None:
        self._text: str = ""
        self._renderable: Markdown | None = None
        self._rendered_view: str | None = None  # the trimmed/capped text last parsed
        self._last_render_at: float = 0.0
        self._min_interval = min_interval
        self._max_stream_chars = max_stream_chars
        self._sealed: bool = False

    def append(self, chunk: str) -> None:
        """Append one :class:`~cairn.orchestration.events.TextDelta`'s text."""
        if chunk:
            self._text += chunk

    @property
    def text(self) -> str:
        """The full accumulated text (untrimmed, uncapped)."""
        return self._text

    @property
    def empty(self) -> bool:
        return not self._text

    def _view(self) -> str:
        """The string to actually parse this frame: trimmed + capped while streaming."""
        text = self._text
        if not self._sealed:
            if (
                self._max_stream_chars is not None
                and len(text) > self._max_stream_chars
            ):
                text = "…\n" + text[-self._max_stream_chars :]
            text = trim_trailing_fence(text)
        return text

    def render(self, *, now: float | None = None) -> Markdown:
        """Return a ``Markdown`` renderable, re-lexing at most every ``min_interval``.

        ``now`` (``time.monotonic()`` seconds) may be injected for deterministic
        tests; it defaults to the current monotonic clock.
        """
        t = now if now is not None else time.monotonic()
        view = self._view()
        # Re-parse when: sealed (forces a clean full render), never rendered yet,
        # the throttle window has elapsed, or the visible view changed.
        due = (
            self._sealed
            or self._renderable is None
            or (t - self._last_render_at) >= self._min_interval
        )
        if due and (view != self._rendered_view or self._renderable is None):
            self._rendered_view = view
            self._renderable = Markdown(view)
            self._last_render_at = t
        # Within the throttle window, or view unchanged: hand back the cached parse.
        return self._renderable if self._renderable is not None else Markdown("")

    def seal(self) -> Markdown:
        """Finalize: drop the trim/cap and do one full render of everything."""
        self._sealed = True
        return self.render()
