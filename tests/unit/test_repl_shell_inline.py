"""Tests for U4: ``!``/``!!`` shell passthrough + ``@file`` inline.

Both are user-trusted affordances: their output/contents enter the prompt or
terminal directly — never wrapped, never audited. Covered here: the ``@file``
expansion (in-workspace inline, out-of-workspace literal + warn, emails ignored)
and that the ``!`` shell path still scrubs secrets from the child env.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

from rich.console import Console

from cairn.interfaces.repl import _expand_atfiles


def _console_buf() -> tuple[io.StringIO, Console]:
    buf = io.StringIO()
    return buf, Console(file=buf, force_terminal=False, width=80, color_system=None)


def test_expand_atfiles_inlines_workspace_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # cwd is a workspace root; @note.txt resolves here
    note = tmp_path / "note.txt"
    note.write_text("hello world", encoding="utf-8")
    session = SimpleNamespace(ctx=SimpleNamespace(workspace=tmp_path))
    buf, console = _console_buf()
    out = _expand_atfiles(console, session, f"summarize @{note.name}")
    assert "hello world" in out
    assert "contents of @note.txt" in out
    assert "outside workspace" not in buf.getvalue()


def test_expand_atfiles_leaves_out_of_workspace_literal(tmp_path):
    session = SimpleNamespace(ctx=SimpleNamespace(workspace=tmp_path))
    buf, console = _console_buf()
    out = _expand_atfiles(console, session, "@/etc/passwd")
    assert out == "@/etc/passwd"  # left literal
    assert "outside workspace" in buf.getvalue()  # warned


def test_expand_atfiles_ignores_email_at(tmp_path):
    session = SimpleNamespace(ctx=SimpleNamespace(workspace=tmp_path))
    buf, console = _console_buf()
    line = "contact a@b.com please"
    assert _expand_atfiles(console, session, line) == line  # emails not expanded
    assert buf.getvalue() == ""


async def test_run_user_shell_scrubs_env(monkeypatch):
    """`!env` must not dump an exported LLM key / token to the terminal."""
    from cairn.interfaces.repl import _run_user_shell

    monkeypatch.setenv("CAIRN_LLM__API_KEY", "sk-leak-1234567890")
    monkeypatch.setenv("MY_TOKEN", "sekret-value")
    result = await _run_user_shell("env")
    out = result.stdout.decode(errors="replace")
    assert "sk-leak" not in out
    assert "sekret-value" not in out
