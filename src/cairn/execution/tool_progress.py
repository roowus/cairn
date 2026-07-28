"""Per-call ``tool_call_id`` bridge: tool closure → live stdout (UI overhaul U3).

The audited tool closure (:mod:`cairn.orchestration.tool_adapter`) knows each
call's ``tool_call_id``; the deep execution path (a plugin's ``run()`` →
``run_shell`` / ``run_subprocess``) does not. This module bridges them with a
:class:`contextvars.ContextVar`: the closure binds it around ``plugin.run()``,
and :func:`progress_for` builds the ``on_line`` callback that tags each streamed
stdout line with the *current* call's id so it lands on the right ToolCard.

asyncio copies the context per Task, and PydanticAI runs each tool call as its
own Task, so concurrent calls don't clobber each other's id — the property the
parallel-correlation test guards. Layering: this lives in ``execution`` so both
``orchestration.tool_adapter`` (downward import, sets the var) and the plugins
(same layer, read it via :func:`progress_for`) can reach it without an upward
import.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cairn.execution.base import PluginContext

_current_tool_call_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cairn_current_tool_call_id", default=None
)


@contextlib.contextmanager
def bind_tool_call_id(tool_call_id: str):
    """Bind ``tool_call_id`` as the current call for the duration of the block.

    Used as ``with bind_tool_call_id(tid): out = await plugin.run(...)`` in the
    tool closure. Reset on exit so a reused worker never inherits a stale id.
    """
    token = _current_tool_call_id.set(tool_call_id)
    try:
        yield
    finally:
        _current_tool_call_id.reset(token)


def current_tool_call_id() -> str | None:
    """The tool_call_id of the call currently running on this task (or ``None``)."""
    return _current_tool_call_id.get()


def progress_for(ctx: PluginContext) -> Callable[[str], None] | None:
    """Build a sync ``on_line(line)`` callback that tags stdout to the current call.

    Returns ``None`` when no progress observer is attached (then the caller uses
    the buffered ``communicate()`` path). The callback only forwards to the
    observer's ``on_tool_progress`` — it never influences execution.
    """
    progress = getattr(ctx, "progress", None)
    if progress is None:
        return None

    def on_line(line: str) -> None:
        progress.on_tool_progress(_current_tool_call_id.get() or "", line)

    return on_line
