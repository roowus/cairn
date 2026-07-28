"""Safe subprocess execution.

Every CLI-wrapper plugin MUST go through :func:`run_subprocess`, and the agentic
shell through :func:`run_shell`. Both use ``asyncio.create_subprocess_exec`` with
**list arguments** — never ``shell=True`` — so a parameter containing shell
metacharacters is passed as a single argv element and never evaluated at the
Python level. (:func:`run_shell` invokes ``bash -c <command>`` as the array
``["bash", "-c", command]`` to give the agentic shell pipes/redirects/globs while
preserving this invariant — the anti-command-injection property.)

The shared core :func:`_exec` owns the timeout + kill discipline so it is
impossible to forget.
"""

from __future__ import annotations

import asyncio
import contextlib
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class SubprocessError(Exception):
    """Raised when a wrapped subprocess fails or times out."""


@dataclass(frozen=True)
class CommandResult:
    """Result of :func:`run_shell`: stdout/stderr bytes + the exit code.

    The exit code is returned as DATA (never raised on non-zero) so the agent can
    observe command failures as wrapped observation rather than as tool errors.
    """

    stdout: bytes
    stderr: bytes
    returncode: int


async def _exec(
    args: Sequence[str],
    *,
    timeout: float,
    env: dict[str, str] | None,
    cwd: Path | None,
) -> tuple[bytes, bytes, int | None]:
    """Shared core: run ``args`` (array), return ``(stdout, stderr, returncode)``.

    Raises :class:`SubprocessError` on timeout or a missing binary (FileNotFoundError).
    ``args`` is never concatenated into a shell.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        raise SubprocessError(f"binary not found: {args[0]!r}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        raise SubprocessError(
            f"timed out after {timeout:g}s running: {shlex.join(args)}"
        ) from None

    return stdout, stderr, proc.returncode


async def run_subprocess(
    args: Sequence[str],
    *,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> tuple[bytes, bytes]:
    """Run a command with array args and return ``(stdout, stderr)`` bytes.

    Raises :class:`SubprocessError` on timeout, non-zero exit (when
    ``check=True``), or a missing binary (FileNotFoundError). ``args`` is never
    concatenated into a shell. ``cwd`` runs the child in that directory;
    ``None`` inherits the parent cwd.
    """
    stdout, stderr, rc = await _exec(args, timeout=timeout, env=env, cwd=cwd)
    if check and rc not in (0, None):
        raise SubprocessError(
            f"{shlex.join(args)} exited {rc}: {stderr.decode(errors='replace').strip()}"
        )
    return stdout, stderr


async def run_shell(
    command: str,
    *,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> CommandResult:
    """Run ``command`` under ``bash -c`` and return stdout/stderr/exit code.

    Invoked as the array ``["bash", "-c", command]`` via
    :func:`asyncio.create_subprocess_exec` — **never** ``shell=True`` — so the
    no-shell-at-Python-level invariant holds while still giving the agentic shell
    pipes, redirects, globs, and ``&&``. A non-zero exit is returned as data
    (never raised); only a timeout or a missing ``bash`` raise
    :class:`SubprocessError`.
    """
    stdout, stderr, rc = await _exec(
        ["bash", "-c", command], timeout=timeout, env=env, cwd=cwd
    )
    return CommandResult(stdout, stderr, rc if rc is not None else 0)
