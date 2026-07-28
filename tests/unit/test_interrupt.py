"""Esc / Ctrl-C turn cancellation helper."""

from __future__ import annotations

import asyncio

import pytest

from cairn.interfaces.interrupt import (
    TurnCancelled,
    cancel_async_task,
    cancel_tasks,
    run_cancellable,
)


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


def test_cancel_async_task_issues_cancel():
    """The programmatic path: cancel a running task by handle (the pool's primitive)."""
    loop = asyncio.new_event_loop()
    try:

        async def forever() -> str:
            await asyncio.sleep(3600)
            return "nope"

        task = loop.create_task(forever())
        loop.run_until_complete(asyncio.sleep(0))  # let it start
        assert not task.done()
        assert cancel_async_task(task) is True
        with pytest.raises(asyncio.CancelledError):
            loop.run_until_complete(task)
        # idempotent: an already-done task returns False
        assert cancel_async_task(task) is False
    finally:
        loop.close()


def test_cancel_tasks_counts():
    loop = asyncio.new_event_loop()
    try:

        async def snooze() -> str:
            await asyncio.sleep(3600)
            return "nope"

        tasks = [loop.create_task(snooze()) for _ in range(3)]
        loop.run_until_complete(asyncio.sleep(0))
        assert cancel_tasks(tasks) == 3
        # A task is only `.done()` once its cancellation has propagated, so drain
        # them before asserting the second (no-op) cancel counts nothing.
        for t in tasks:
            with pytest.raises(asyncio.CancelledError):
                loop.run_until_complete(t)
        assert cancel_tasks(tasks) == 0
    finally:
        loop.close()
