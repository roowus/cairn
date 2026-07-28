"""Esc / Ctrl-C turn cancellation helper."""

from __future__ import annotations

import asyncio

import pytest

from cairn.interfaces.interrupt import TurnCancelled, run_cancellable


def test_run_cancellable_success():
    loop = asyncio.new_event_loop()
    try:

        async def ok() -> str:
            await asyncio.sleep(0.01)
            return "done"

        assert run_cancellable(loop, ok()) == "done"
    finally:
        loop.close()


def test_run_cancellable_on_task_cancel():
    loop = asyncio.new_event_loop()
    try:

        async def forever() -> str:
            await asyncio.sleep(3600)
            return "nope"

        task_box: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]

        async def starter() -> str:
            # Schedule cancel of the outer task mid-flight via the running loop.
            current = asyncio.current_task()
            assert current is not None
            task_box["t"] = current
            loop.call_soon(current.cancel)
            return await forever()

        with pytest.raises(TurnCancelled):
            run_cancellable(loop, starter())
    finally:
        loop.close()
