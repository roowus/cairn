"""Tests for the per-call tool_call_id bridge + on_tool_progress hook (UI overhaul U3).

The load-bearing one is :func:`test_contextvar_isolates_per_concurrent_task` — it
proves concurrent tool calls (each its own asyncio Task) read their OWN
tool_call_id, which is the whole reason live stdout lands on the right ToolCard
under PydanticAI's parallel tool execution.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from cairn.execution.tool_progress import (
    bind_tool_call_id,
    current_tool_call_id,
    progress_for,
)
from cairn.orchestration.progress import NullProgress, Progress


async def test_contextvar_isolates_per_concurrent_task():
    """asyncio copies ContextVar per Task; concurrent calls don't clobber each other."""
    seen: dict[str, str | None] = {}

    async def worker(tid: str) -> None:
        with bind_tool_call_id(tid):
            await asyncio.sleep(0.01)  # interleave with the sibling task
            seen[tid] = current_tool_call_id()

    await asyncio.gather(worker("AAA"), worker("BBB"))
    assert seen == {"AAA": "AAA", "BBB": "BBB"}


def test_bind_resets_after_exit():
    with bind_tool_call_id("X"):
        assert current_tool_call_id() == "X"
    assert current_tool_call_id() is None


def test_progress_for_none_without_observer():
    assert progress_for(SimpleNamespace(progress=None)) is None


def test_progress_for_forwards_on_tool_progress():
    captured: list[tuple[str, str]] = []

    class _Rec(Progress):
        def on_tool_progress(self, tool_call_id: str, line: str) -> None:  # type: ignore[override]
            captured.append((tool_call_id, line))

    on_line = progress_for(SimpleNamespace(progress=_Rec()))
    assert on_line is not None
    with bind_tool_call_id("call-7"):
        on_line("hello")
        on_line("world")
    assert captured == [("call-7", "hello"), ("call-7", "world")]


def test_null_progress_on_tool_progress_is_noop():
    NullProgress().on_tool_progress("id", "line")  # must not raise
