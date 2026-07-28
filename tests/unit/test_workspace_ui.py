"""The /workspace REPL command and the RichPermissionUI v2 seam."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from rich.console import Console

from cairn.execution.base import PluginContext
from cairn.execution.workspace import PermissionRequest
from cairn.interfaces.repl import _cmd_workspace
from cairn.interfaces.tui.permission_panel import (
    RichPermissionUI,
    parse_confirm,
    render_permission_request,
)

# --- /workspace command -----------------------------------------------------


def test_cmd_workspace_renders_tree(tmp_path):
    (tmp_path / "challenge.zip").write_bytes(b"PK\x03\x04")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    session = SimpleNamespace(ctx=PluginContext(workspace=tmp_path))
    _cmd_workspace(console, session)
    out = buf.getvalue()
    assert "Workspace" in out
    assert "challenge.zip" in out  # the scratch root's file is listed


def test_cmd_workspace_shows_empty(tmp_path):
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    session = SimpleNamespace(ctx=PluginContext(workspace=tmp_path))
    _cmd_workspace(console, session)
    # tmp_path is empty; cwd root may have entries, but the call must not raise.
    assert "Workspace" in buf.getvalue()


# --- RichPermissionUI (v2 seam) --------------------------------------------


def test_parse_confirm():
    for yes in ("y", "Y", "yes", "YES", "  y  "):
        assert parse_confirm(yes) is True, yes
    for no in ("", "n", "no", "nope", "0"):
        assert parse_confirm(no) is False, no


def test_render_permission_request_panel():
    decl = PermissionRequest(op="write", target="/etc/x", reason="outside the workspace")
    buf = io.StringIO()
    Console(file=buf, force_terminal=False, width=120).print(render_permission_request(decl))
    out = buf.getvalue()
    assert "write" in out
    assert "/etc/x" in out
    assert "outside the workspace" in out


class _FakeConsole:
    """Duck-typed console: capture print, return a canned input()."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.printed: list[object] = []

    def print(self, *args, **kwargs) -> None:
        self.printed.append(args)

    def input(self, prompt: str = "") -> str:
        return self.answer


@pytest.mark.asyncio
async def test_rich_permission_ui_grants_on_yes():
    ui = RichPermissionUI(console=_FakeConsole("y"))
    granted = await ui.request(
        PermissionRequest(op="read", target="/etc/passwd", reason="outside")
    )
    assert granted is True
    assert ui.console.printed  # the panel was rendered


@pytest.mark.asyncio
async def test_rich_permission_ui_denies_on_default():
    ui = RichPermissionUI(console=_FakeConsole(""))
    granted = await ui.request(
        PermissionRequest(op="write", target="/etc/x", reason="outside")
    )
    assert granted is False


@pytest.mark.asyncio
async def test_authorize_consults_rich_permission_ui(tmp_path):
    from cairn.execution.workspace import Allow, Deny, authorize

    # Out-of-workspace target: a granting UI → Allow; a denying UI → Deny.
    granting = RichPermissionUI(console=_FakeConsole("y"))
    assert isinstance(await authorize("write", "/etc/outside", [tmp_path], granting), Allow)

    denying = RichPermissionUI(console=_FakeConsole("n"))
    assert isinstance(await authorize("write", "/etc/outside", [tmp_path], denying), Deny)
