"""Progress observation tap for the agentic loop.

A :class:`Progress` instance is notified as the agent executes tools, so
interfaces (REPL, headless) can show what is happening live — which tool is
running, its target, and a pass/fail result excerpt — instead of a silent
spinner. It is an **observer only** and never influences execution: it cannot
alter tool arguments, suppress calls, or change the answer.

Notifications originate from the tool closure in
:mod:`cairn.orchestration.tool_adapter`, which is the single source of truth for
per-call ``status``/``target``/``summary`` (the same values written to the audit
log). The default :class:`NullProgress` does nothing; interfaces subclass and
override the hooks they care about.

Every tool hook carries a ``tool_call_id`` — the per-call correlation key the
framework assigns. PydanticAI executes tool calls **concurrently** by default and
emits results in completion (not emission) order, and the same tool name can
appear twice in one response, so ``tool_call_id`` is the *only* robust way to
match a start to its end (and to the stream's ``ToolExecStart``/``ToolExecEnd``).
It is observer-only: never written to the audit log or usage tracker.

All hooks are **synchronous** — they run inside the agent's event loop on the
calling thread, so it is safe to render to a Rich console from them.
"""

from __future__ import annotations

from typing import Any


class Progress:
    """No-op observer. Subclass and override the hooks you need."""

    def on_turn_start(self, prompt: str) -> None:
        """A new user turn is beginning."""

    def on_tool_start(
        self, name: str, target: str, params: dict[str, Any], tool_call_id: str
    ) -> None:
        """A tool is about to run. ``tool_call_id`` correlates start→end→stream event."""

    def on_tool_end(
        self,
        name: str,
        target: str,
        status: str,
        summary: str,
        error: str | None,
        tool_call_id: str,
    ) -> None:
        """A tool finished. ``status`` is ``"ok"`` or ``"error"``."""

    def on_tool_progress(self, tool_call_id: str, line: str) -> None:
        """A streamed stdout line from a long-running tool (sherlock/holehe/run_command).

        High-volume (sherlock emits hundreds of lines) — receivers tail-cap what
        they show. Observer-only, like every hook here.
        """

    def on_turn_end(self, answer: str) -> None:
        """The turn finished with a final answer."""


class NullProgress(Progress):
    """Default observer — does nothing. Used when no UI is attached."""


def excerpt(text: str, limit: int = 120) -> str:
    """First meaningful line of a summary, trimmed for a one-line status."""
    if not text:
        return ""
    line = text.strip().split("\n", 1)[0].replace("**", "").strip()
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line
