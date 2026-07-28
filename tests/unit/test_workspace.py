"""Agentic workspace primitives: boundary check, env scrub, permission gate.

Guards the two-layer model's *execution-permission* layer (anti-injection is
exercised separately via the wrap-back tests in ``test_agentic.py``).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cairn.execution.workspace import (
    Allow,
    Deny,
    NullPermissionUI,
    PermissionRequest,
    authorize,
    decide,
    is_inside_workspace,
    list_workspace_tree,
    resolve_in_workspace,
    scrub_env,
    workspace_roots,
)

# --- boundary checks --------------------------------------------------------


def test_inside_cwd_is_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roots = workspace_roots(SimpleNamespace(workspace=None))  # cwd only
    (tmp_path / "chal.txt").write_text("x")
    assert is_inside_workspace("chal.txt", roots)
    # a not-yet-existing nested path under cwd is still in-workspace
    assert is_inside_workspace(tmp_path / "nested" / "deep.txt", roots)


def test_dotdot_and_absolute_escape_is_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roots = workspace_roots(SimpleNamespace(workspace=None))
    assert not is_inside_workspace("../../etc/passwd", roots)
    assert not is_inside_workspace("/etc/passwd", roots)
    assert resolve_in_workspace("/etc/passwd", roots) is None


def test_symlink_escape_is_denied(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    roots = [ws]
    secret = tmp_path / "secret.txt"  # sibling of ws -> outside the roots
    secret.write_text("pwn")
    link = ws / "link.txt"
    link.symlink_to(secret)
    # link resolves to secret.txt, which is outside ws -> denied
    assert not is_inside_workspace(link, roots)
    # a normal file inside ws is allowed
    (ws / "ok.txt").write_text("ok")
    assert is_inside_workspace(ws / "ok.txt", roots)


def test_scratch_workspace_root_is_added(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    roots = workspace_roots(SimpleNamespace(workspace=scratch))
    assert scratch in roots
    (scratch / "dl.bin").write_bytes(b"\x00")
    assert is_inside_workspace(scratch / "dl.bin", roots)


# --- env scrub --------------------------------------------------------------


def test_scrub_env_strips_secret_names_and_values():
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/users/me",
        "USER": "me",
        "SHELL": "/bin/zsh",
        "LANG": "en_US.UTF-8",
        "TERM": "xterm",
        "TMPDIR": "/var/tmp",
        "CAIRN_LLM__API_KEY": "sk-ant-leak",
        "CAIRN_CONFIG_DIR": "/tmp/x",
        "OPENAI_API_KEY": "sk-leak-1234567890abc",
        "GITHUB_TOKEN": "ghp_abcdefghijklmnopqrstuv",
        "AWS_SECRET_ACCESS_KEY": "AKIAIOSFODNN7EXAMPLE",
        "AUTHORIZATION": "Bearer abcdef",
        "MY_PASSWORD": "hunter2",
        "BEARER": "xyz",
        # innocuous name, secret-shaped value -> still scrubbed
        "INNOCUOUS": "sk-somethinglongenough16",
        "SAFE_VAR": "hello world",
    }
    out = scrub_env(env)
    # kept
    for kept in ("PATH", "HOME", "USER", "SHELL", "LANG", "TERM", "TMPDIR", "SAFE_VAR"):
        assert kept in out, kept
    # stripped (by name or value)
    for banned in (
        "CAIRN_LLM__API_KEY",
        "CAIRN_CONFIG_DIR",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "AUTHORIZATION",
        "MY_PASSWORD",
        "BEARER",
        "INNOCUOUS",
    ):
        assert banned not in out, banned


def test_scrub_env_catches_broadened_secret_names():
    """Names/values the original narrow allowlist missed (review-found regression).

    Covers the broadened NAME regex (AUTH, COOKIE, PRIVATE_KEY, PASSWD, APIKEY,
    ACCESS_KEY, …) and the broadened VALUE backstop (AWS STS ``ASIA`` prefix,
    GitHub ``ghp_`` PAT under an innocuous name).
    """
    env = {
        "AUTH": "Bearer x",
        "COOKIE": "session=x",
        "SESSION_COOKIE": "s=1",
        "PRIVATE_KEY": "-----BEGIN-----",
        "PRIVATEKEY": "deadbeef",
        "PASSWD": "hunter2",
        "APIKEY": "abc123",
        "ACCESS_KEY": "k",
        "AWS_ACCESS_KEY_ID": "ASIA" + "Z" * 16,
        "HARMLESS_NAME": "ghp_" + "b" * 36,
        "ALSO_HARMLESS": "ASIA" + "9" * 16,
        "KEEP_ME": "ordinary",
    }
    out = scrub_env(env)
    assert "KEEP_ME" in out
    for banned in env:
        if banned != "KEEP_ME":
            assert banned not in out, banned


# --- permission gate --------------------------------------------------------


async def test_decide_allows_in_workspace_denies_outside(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roots = workspace_roots(SimpleNamespace(workspace=None))
    assert isinstance(decide("read", "file.txt", roots), Allow)
    assert isinstance(decide("write", "/etc/x", roots), Deny)


async def test_authorize_allows_in_workspace_without_ui(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roots = workspace_roots(SimpleNamespace(workspace=None))
    assert isinstance(await authorize("read", "file.txt", roots, None), Allow)


async def test_authorize_denies_outside_without_ui():
    roots = [Path("/tmp/cairn-nonexistent-ws")]
    dec = await authorize("read", "/etc/passwd", roots, None)
    assert isinstance(dec, Deny)


async def test_null_permission_ui_denies_everything():
    ui = NullPermissionUI()
    assert (
        await ui.request(PermissionRequest("write", "/etc/x", "outside")) is False
    )


# --- workspace view ---------------------------------------------------------


def test_list_workspace_tree_lists_files(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    sub = tmp_path / "d"
    sub.mkdir()
    (sub / "b.txt").write_text("yo")
    out = list_workspace_tree([tmp_path])
    assert "a.txt" in out
    assert "b.txt" in out
    assert "d/" in out
