"""Tests for the streaming subprocess path (UI overhaul U3).

Covers: ``on_line`` streams stdout line-by-line AND the full bytes are still
returned; ``on_line=None`` keeps the original buffered ``communicate()`` path
(behavior-identical for every existing caller); the streaming timeout still
raises ``SubprocessError``.
"""

from __future__ import annotations

import pytest

from cairn.execution.subprocess_util import SubprocessError, run_shell, run_subprocess


async def test_run_shell_streams_lines_and_returns_full_output():
    lines: list[str] = []
    res = await run_shell("echo a; echo b; echo c", on_line=lambda ln: lines.append(ln))
    assert lines == ["a", "b", "c"]
    assert res.stdout.strip() == b"a\nb\nc"  # full output preserved
    assert res.returncode == 0


async def test_on_line_none_keeps_buffered_path():
    res = await run_shell("echo hi")
    assert res.stdout.strip() == b"hi"


async def test_run_subprocess_streams_and_returns_full():
    lines: list[str] = []
    out, _err = await run_subprocess(
        ["printf", "x\ny\n"], on_line=lambda ln: lines.append(ln)
    )
    assert lines == ["x", "y"]
    assert out.strip() == b"x\ny"


async def test_exec_stream_timeout_raises():
    with pytest.raises(SubprocessError):
        await run_shell("sleep 5", timeout=0.5, on_line=lambda ln: None)
