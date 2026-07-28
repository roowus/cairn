"""Allowlisted CLI tool install / resolve."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cairn.execution.cli_tools import (
    _augment_path_env,
    ensure_cli_tool,
    find_cli_tool,
    list_cli_tools,
    run_cli_tool,
    which_binary,
)
from cairn.execution.subprocess_util import SubprocessError


def test_allowlist_contains_sherlock_and_holehe():
    names = {t.name for t in list_cli_tools()}
    assert {"sherlock", "holehe"} <= names
    assert find_cli_tool("sherlock-project") is not None
    assert find_cli_tool("SHERLOCK") is not None
    assert find_cli_tool("rm -rf /") is None


@pytest.mark.asyncio
async def test_unknown_tool_rejected():
    ok, msg = await ensure_cli_tool("totally-fake-cli")
    assert ok is False
    assert "Unknown" in msg or "Allowlisted" in msg


def test_two_tier_analyzer_allowlist_present():
    by_name = {t.name: t for t in list_cli_tools()}
    # Tier A — uv-installable analyzers (on demand, NOT bootstrapped at startup).
    for name in ("binwalk", "oletools", "html2text", "pdfminer.six"):
        assert by_name[name].manager == "uv", name
        assert by_name[name].bootstrap is False, name
    # Tier B — system packages, hint-only.
    for name in ("exiftool", "tshark", "nmap", "steghide"):
        assert by_name[name].manager == "system", name
        assert by_name[name].bootstrap is False, name
        assert by_name[name].install_hint, name
    # Core identity tools still auto-bootstrap.
    assert by_name["sherlock"].bootstrap is True
    assert by_name["holehe"].manager == "uv"


@pytest.mark.asyncio
async def test_system_tool_returns_hint_without_installing(tmp_path, monkeypatch):
    # exiftool absent; run_subprocess must NOT be called (no uv install attempt).
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr("cairn.execution.cli_tools._EXTRA_PATH_DIRS", (tmp_path,))

    called: list[tuple] = []

    async def fake_run(*a, **k):
        called.append(a)
        return b"", b""

    with patch("cairn.execution.cli_tools.run_subprocess", new=AsyncMock(side_effect=fake_run)):
        ok, msg = await ensure_cli_tool("exiftool", install=True)
    assert ok is False
    assert "system" in msg.lower() or "install" in msg.lower()
    assert "brew install exiftool" in msg  # the hint is relayed verbatim
    assert called == []  # a system tool never triggers `uv tool install`


def test_augment_path_env_scrubs_exported_secrets(monkeypatch):
    """The CLI-tool subprocess env must scrub a user-exported secret.

    Regression for the review-found gap: ``_augment_path_env`` used to pass
    ``os.environ.copy()`` raw, so sherlock/holehe/binwalk (networked) inherited
    exported tokens. Now it routes through ``scrub_env`` like ``run_command``.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 36)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "x" * 20)
    monkeypatch.setenv("MY_COOKIE", "session=secret")
    env = _augment_path_env()
    assert "GITHUB_TOKEN" not in env
    assert "OPENAI_API_KEY" not in env
    assert "MY_COOKIE" not in env
    assert "PATH" in env  # PATH augmentation still works post-scrub


def test_bootstrap_filter_is_core_tools_only():
    # The repl bootstraps only uv tools flagged bootstrap=True (sherlock/holehe).
    boot = [t.name for t in list_cli_tools() if t.bootstrap and t.manager == "uv"]
    assert set(boot) == {"sherlock", "holehe"}


@pytest.mark.asyncio
async def test_ensure_already_installed(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "sherlock"
    fake.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    ok, msg = await ensure_cli_tool("sherlock", install=False)
    assert ok is True
    assert "already installed" in msg
    assert which_binary("sherlock") == str(fake)


@pytest.mark.asyncio
async def test_ensure_installs_via_uv(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # uv present, sherlock absent initially
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(
        "cairn.execution.cli_tools._EXTRA_PATH_DIRS",
        (bin_dir,),
    )

    async def fake_run(args, timeout=30.0, env=None):
        assert args[:3] == ["uv", "tool", "install"]
        assert args[3] == "sherlock-project"
        # Simulate install dropping the binary
        sh = bin_dir / "sherlock"
        sh.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        sh.chmod(0o755)
        return b"Installed", b""

    with patch("cairn.execution.cli_tools.run_subprocess", new=AsyncMock(side_effect=fake_run)):
        ok, msg = await ensure_cli_tool("sherlock", install=True)
    assert ok is True
    assert "Installed" in msg
    assert which_binary("sherlock") is not None


@pytest.mark.asyncio
async def test_ensure_refuses_without_uv(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # empty of uv and sherlock
    monkeypatch.setattr("cairn.execution.cli_tools._EXTRA_PATH_DIRS", (tmp_path,))
    ok, msg = await ensure_cli_tool("holehe", install=True)
    assert ok is False
    assert "uv" in msg.lower()


@pytest.mark.asyncio
async def test_run_cli_tool_auto_install(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr("cairn.execution.cli_tools._EXTRA_PATH_DIRS", (bin_dir,))

    calls: list[list[str]] = []

    async def fake_run(args, timeout=30.0, env=None, check=True):
        calls.append(list(args))
        if args[:3] == ["uv", "tool", "install"]:
            sh = bin_dir / "holehe"
            sh.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
            sh.chmod(0o755)
            return b"", b""
        # actual holehe invocation
        return b"[+] github\n", b""

    with patch("cairn.execution.cli_tools.run_subprocess", new=AsyncMock(side_effect=fake_run)):
        out, _ = await run_cli_tool(
            "holehe", ["--only-used", "--no-color", "a@b.c"], auto_install=True
        )
    assert b"github" in out
    assert any(c[:3] == ["uv", "tool", "install"] for c in calls)


@pytest.mark.asyncio
async def test_run_cli_unknown_raises():
    with pytest.raises(SubprocessError, match="unknown"):
        await run_cli_tool("totally-fake-tool", ["x"])


@pytest.mark.asyncio
async def test_install_cli_plugin_list():
    from cairn.execution.base import PluginContext
    from cairn.plugins.identity.install_cli import InstallCliInput, InstallCliPlugin

    out = await InstallCliPlugin().run(InstallCliInput(target="list"), PluginContext())
    assert "sherlock" in out.summary_markdown
    assert "holehe" in out.summary_markdown


@pytest.mark.asyncio
async def test_ensure_missing_installs_only_absent(tmp_path, monkeypatch):
    from cairn.execution.cli_tools import ensure_missing_cli_tools

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # holehe present, sherlock absent
    holehe = bin_dir / "holehe"
    holehe.write_text("#!/bin/sh\n", encoding="utf-8")
    holehe.chmod(0o755)
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr("cairn.execution.cli_tools._EXTRA_PATH_DIRS", (bin_dir,))

    installed: list[str] = []

    async def fake_run(args, timeout=30.0, env=None):
        if args[:3] == ["uv", "tool", "install"]:
            installed.append(args[3])
            sh = bin_dir / "sherlock"
            sh.write_text("#!/bin/sh\n", encoding="utf-8")
            sh.chmod(0o755)
            return b"ok", b""
        return b"", b""

    with patch("cairn.execution.cli_tools.run_subprocess", new=AsyncMock(side_effect=fake_run)):
        rows = await ensure_missing_cli_tools(install=True)
    by_name = {n: (ok, msg) for n, ok, msg in rows}
    assert by_name["holehe"][1] == "already installed"
    assert by_name["sherlock"][0] is True
    assert installed == ["sherlock-project"]


@pytest.mark.asyncio
async def test_install_cli_plugin_installs(monkeypatch):
    from cairn.execution.base import PluginContext
    from cairn.plugins.identity.install_cli import InstallCliInput, InstallCliPlugin

    async def fake_ensure(name, install=True, timeout=300.0, progress=None):
        assert name == "sherlock"
        return True, "Installed sherlock → /tmp/sherlock"

    monkeypatch.setattr(
        "cairn.plugins.identity.install_cli.ensure_cli_tool",
        fake_ensure,
    )
    out = await InstallCliPlugin().run(InstallCliInput(target="sherlock"), PluginContext())
    assert out.installed is True
    assert "Installed" in out.summary_markdown
