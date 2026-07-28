"""Cancel an in-flight agent turn on Esc or Ctrl-C.

The REPL runs the async agent loop with ``run_until_complete``. While that is
blocking, we watch stdin (cbreak mode on a TTY) for Esc (``\\x1b``) or Ctrl-C
(``\\x03``) and cancel the asyncio task. Non-TTY environments fall back to
Ctrl-C / ``KeyboardInterrupt`` only.
"""

from __future__ import annotations

import asyncio
import contextlib
import select
import sys
import threading
from collections.abc import Awaitable, Callable


class TurnCancelled(Exception):
    """Raised when the user aborts the current agent turn (Esc / Ctrl-C)."""


def run_cancellable[T](
    loop: asyncio.AbstractEventLoop,
    coro: Awaitable[T],
    *,
    on_cancel: Callable[[], None] | None = None,
) -> T:
    """Run ``coro`` until done, cancelling it if the user hits Esc or Ctrl-C.

    Returns the coroutine result. Raises :class:`TurnCancelled` on user abort.
    """
    task: asyncio.Task[T] = loop.create_task(coro)  # type: ignore[arg-type]
    stop = threading.Event()
    watcher: _KeyWatcher | None = None

    if sys.stdin.isatty():
        watcher = _KeyWatcher(
            on_escape=lambda: loop.call_soon_threadsafe(_cancel_task, task),
            stop=stop,
        )
        watcher.start()

    try:
        try:
            return loop.run_until_complete(task)
        except KeyboardInterrupt:
            _cancel_task(task)
            # Drain the cancellation so the loop stays usable.
            with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
                loop.run_until_complete(task)
            if on_cancel:
                on_cancel()
            raise TurnCancelled("interrupted (Ctrl-C)") from None
        except asyncio.CancelledError:
            if on_cancel:
                on_cancel()
            raise TurnCancelled("interrupted (Esc)") from None
    finally:
        stop.set()
        if watcher is not None:
            watcher.join(timeout=0.5)
        if not task.done():
            _cancel_task(task)
            with contextlib.suppress(Exception):
                loop.run_until_complete(task)


def _cancel_task(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    if not task.done():
        task.cancel()


class _KeyWatcher(threading.Thread):
    """Daemon thread: cbreak stdin → cancel callback on Esc / Ctrl-C."""

    def __init__(self, *, on_escape: Callable[[], None], stop: threading.Event) -> None:
        super().__init__(name="cairn-esc-watcher", daemon=True)
        self._on_escape = on_escape
        self._stop = stop

    def run(self) -> None:
        fd = None
        old = None
        try:
            import termios
            import tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            while not self._stop.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not r:
                    continue
                ch = sys.stdin.read(1)
                if ch in ("\x1b", "\x03"):  # Esc or Ctrl-C
                    self._on_escape()
                    return
        except Exception:
            # No termios (Windows) or stdin closed — Ctrl-C path still works.
            return
        finally:
            if fd is not None and old is not None:
                try:
                    import termios

                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except Exception:
                    pass
