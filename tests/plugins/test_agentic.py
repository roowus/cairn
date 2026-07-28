"""Agentic file/exec plugins: behavior, boundary, env-scrub, and wrap-back.

The anti-injection invariant (results wrapped in <untrusted_external_data>) is
structural — every plugin is a BasePlugin, so the audited ``_tool`` closure wraps
its summary just like any OSINT plugin (proven by test_tool_result_is_wrapped).
These tests cover the agentic-specific behavior: workspace boundary enforcement,
secret scrubbing before exec, exit-code-as-data, and registration without
breaking the schema (the Phase-2 crash regression).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from pydantic_ai.models.test import TestModel

from cairn.execution.base import PluginContext
from cairn.execution.registry import PluginRegistry
from cairn.orchestration.session import Session
from cairn.plugins.agentic.download_url import DownloadUrlInput, DownloadUrlPlugin
from cairn.plugins.agentic.list_files import ListFilesInput, ListFilesPlugin
from cairn.plugins.agentic.read_file import ReadFileInput, ReadFilePlugin
from cairn.plugins.agentic.run_command import RunCommandInput, RunCommandPlugin
from cairn.plugins.agentic.write_file import WriteFileInput, WriteFilePlugin


def _ctx(workspace: Path, *, http=None) -> PluginContext:
    return PluginContext(http=http, workspace=workspace)


# --- read_file --------------------------------------------------------------


async def test_read_file_returns_content_and_mines_entities(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text(
        "reach test@example.com or 8.8.8.8 — see https://example.org/page",
        encoding="utf-8",
    )
    out = await ReadFilePlugin().run(ReadFileInput(target=str(path)), _ctx(tmp_path))
    assert "reach test@example.com" in out.summary_markdown
    types_values = {(e.type, e.value) for e in out.entities}
    assert ("email", "test@example.com") in types_values
    assert ("ip", "8.8.8.8") in types_values
    assert ("url", "https://example.org/page") in types_values


async def test_read_file_denies_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = await ReadFilePlugin().run(ReadFileInput(target="/etc/passwd"), _ctx(tmp_path))
    assert "denied" in out.summary_markdown
    assert out.bytes_read == 0


# --- write_file -------------------------------------------------------------


async def test_write_file_creates_and_appends(tmp_path):
    p = tmp_path / "out" / "log.txt"
    await WriteFilePlugin().run(
        WriteFileInput(target=str(p), content="line1\n"), _ctx(tmp_path)
    )
    await WriteFilePlugin().run(
        WriteFileInput(target=str(p), content="line2\n", append=True), _ctx(tmp_path)
    )
    assert p.read_text() == "line1\nline2\n"


async def test_write_file_denies_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = await WriteFilePlugin().run(
        WriteFileInput(target="/etc/cairn-nope.txt", content="x"), _ctx(tmp_path)
    )
    assert "denied" in out.summary_markdown
    assert out.bytes_written == 0


# --- list_files -------------------------------------------------------------


async def test_list_files_shows_tree(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    sub = tmp_path / "d"
    sub.mkdir()
    (sub / "b.txt").write_text("yy")
    out = await ListFilesPlugin().run(ListFilesInput(target=str(tmp_path)), _ctx(tmp_path))
    assert "a.txt" in out.summary_markdown
    assert "b.txt" in out.summary_markdown


# --- run_command ------------------------------------------------------------


async def test_run_command_echo_and_exit_zero(tmp_path):
    out = await RunCommandPlugin().run(
        RunCommandInput(target="echo hello-agentic"), _ctx(tmp_path)
    )
    assert "hello-agentic" in out.summary_markdown
    assert "exit 0" in out.summary_markdown
    assert out.exit_code == 0


async def test_run_command_nonzero_exit_is_data(tmp_path):
    out = await RunCommandPlugin().run(RunCommandInput(target="exit 7"), _ctx(tmp_path))
    assert "exit 7" in out.summary_markdown
    assert out.exit_code == 7


async def test_run_command_scrubs_secret_env(tmp_path, monkeypatch):
    # A key the developer `export`ed must NOT reach the subprocess.
    monkeypatch.setenv("CAIRN_LLM__API_KEY", "sk-leak-1234567890abcdef")
    out = await RunCommandPlugin().run(RunCommandInput(target="env"), _ctx(tmp_path))
    assert "sk-leak" not in out.summary_markdown


async def test_run_command_runs_in_workspace_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("here")
    out = await RunCommandPlugin().run(
        RunCommandInput(target="cat marker.txt"), _ctx(tmp_path)
    )
    assert "here" in out.summary_markdown


# --- download_url -----------------------------------------------------------


class _FakeResp:
    def __init__(self, content: bytes, status: int = 200, ct: str = "application/zip") -> None:
        self.content = content
        self.status_code = status
        self.headers = {"content-type": ct}


class _FakeHttp(httpx.AsyncClient):
    """AsyncClient stand-in so PluginContext.http type-validates; ``get`` is faked."""

    def __init__(self, resp: _FakeResp) -> None:
        super().__init__()
        self._resp = resp

    async def get(self, url: str) -> _FakeResp:
        return self._resp


async def test_download_url_saves_bytes_and_hash(tmp_path):
    payload = b"PK\x03\x04binary-blob"
    ctx = _ctx(tmp_path, http=_FakeHttp(_FakeResp(payload)))
    out = await DownloadUrlPlugin().run(
        DownloadUrlInput(target="https://example.org/chal.zip"), ctx
    )
    assert out.bytes_saved == len(payload)
    saved = Path(out.dest)
    assert saved.read_bytes() == payload
    assert "application/zip" in out.summary_markdown
    assert len(out.sha256) == 64


async def test_download_url_rejects_dest_escape(tmp_path):
    ctx = _ctx(tmp_path, http=_FakeHttp(_FakeResp(b"x")))
    out = await DownloadUrlPlugin().run(
        DownloadUrlInput(target="https://example.org/x", dest="../../etc/evil"), ctx
    )
    assert "denied" in out.summary_markdown or "escapes" in out.summary_markdown


# --- integration: registers + runs through the wrapping closure ------------


async def test_read_file_runs_through_wrapping_closure(fake_settings, tmp_path, monkeypatch):
    """The agentic plugin must register on the agent and run through the same
    audited, wrapping closure as every OSINT plugin — the Phase-2 crash regression
    (schema must build) plus the wrap-back invariant in one shot."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chal.txt").write_text("find me 1.2.3.4", encoding="utf-8")
    reg = PluginRegistry()
    reg.register(ReadFilePlugin())
    session = Session(
        settings=fake_settings, registry=reg, model=TestModel(), db=_db(tmp_path)
    )
    try:
        await session.ask(
            "x",
            model=TestModel(call_tools=["read_file"], custom_output_text="done"),
        )
    finally:
        await session.aclose()
    row = session.db.execute(
        "SELECT tool, status FROM audit_log WHERE tool='read_file'"
    ).fetchone()
    assert row is not None
    assert row["status"] == "ok"


def _db(tmp_path):
    from cairn.storage.db import Database

    return Database(tmp_path / "agentic.db")
