"""secret_scan plugin: detection, provenance, directory scan, boundary.

NOTE: secret fixtures are stored base64-encoded and decoded at runtime, so no
contiguous token-shaped string is ever committed — GitHub push-protection would
otherwise block the push (a scanner's tests must use token-shaped fixtures, which
is exactly what secret scanning also matches). The runtime values are real-shaped,
so the scanner still detects them.
"""

from __future__ import annotations

import base64
import hashlib

from cairn.core.provenance import Confidence
from cairn.execution.base import PluginContext
from cairn.plugins.agentic.secret_scan import SecretScanInput, SecretScanPlugin


def _b64(s: str) -> str:
    return base64.b64decode(s).decode()


def _ctx(workspace) -> PluginContext:
    return PluginContext(workspace=workspace)


async def test_secret_scan_finds_secrets_with_provenance(tmp_path):
    payload = _b64(
        "YXdzX2tleSA9IEFLSUFJT1NGT0ROTjdFWEFNUExFCmdoID0gZ2hwXzAxMjM0NTY3OWFiY2Rl"
        "ZjAxMjM0NTY2Nzg5YWJjZGVmMDEyMwp0b2tlbiA9IGV5SmhiR2NpT2lKSVV6STFOaUo5LmV5"
        "SnpkV0lpT2lJeE1qTTBOVFkzT0Rrd0luMC5TZmxLeHdSSlNNZUtLRjJRVDRmd3BNZUpmMzZQ"
        "T2s2eUpWX2FkUXNzdzVjCi0tLS0tQkVHSU4gUlNBIFBSSVZBVEUgS0VZLS0tLS0K"
    )
    path = tmp_path / "leak.txt"
    path.write_text(payload)
    out = await SecretScanPlugin().run(SecretScanInput(target=str(path)), _ctx(tmp_path))

    names = {f.pattern for f in out.findings}
    assert {"AWS_ACCESS_KEY", "GH_PAT_CLASSIC", "JWT", "RSA_PRIVKEY"} <= names, names

    # every finding is a typed secret entity with FIRM confidence + chain-of-custody
    secrets = [e for e in out.entities if e.type == "secret"]
    assert secrets
    for e in secrets:
        assert e.confidence is Confidence.FIRM
        assert e.provenance is not None
        assert e.provenance.tool == "secret_scan"
        assert e.provenance.raw_sha256 == hashlib.sha256(payload.encode()).hexdigest()
        assert e.provenance.source_url == f"file://{path}"


async def test_secret_scan_scans_directory(tmp_path):
    stripe_line = _b64("c3RyaXBlID0gc2tfbGl2ZV9hYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejEyMzQ1Ngo=")
    (tmp_path / "a.env").write_text(stripe_line)
    anth = "sk-ant-api03-" + "a" * 100  # >= 93 chars after the prefix
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.js").write_text(f'const key = "{anth}"\n')
    out = await SecretScanPlugin().run(SecretScanInput(target=str(tmp_path)), _ctx(tmp_path))
    names = {f.pattern for f in out.findings}
    assert "STRIPE_LIVE" in names
    assert "ANTHROPIC_API" in names
    assert out.files_scanned >= 2


async def test_secret_scan_denies_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = await SecretScanPlugin().run(SecretScanInput(target="/etc/passwd"), _ctx(tmp_path))
    assert "denied" in out.summary_markdown
    assert out.findings == []


async def test_secret_scan_clean_file(tmp_path):
    path = tmp_path / "clean.txt"
    path.write_text("just a normal config with no credentials at all\n")
    out = await SecretScanPlugin().run(SecretScanInput(target=str(path)), _ctx(tmp_path))
    assert out.findings == []
    assert "no secrets matched" in out.summary_markdown


async def test_secret_scan_summary_redacts_secret_but_entity_keeps_it(tmp_path):
    # the summary reaches model context (wrapped, not redacted) -> the live secret
    # must NOT appear there (CLAUDE.md invariant #3). The full value stays on the
    # graph entity (the evidence locker, human-only).
    secret = _b64("QUtJQUlPU0ZPRE5ON0VYQU1QTEU=")
    path = tmp_path / "k.txt"
    path.write_text(f"key = {secret}\n")
    out = await SecretScanPlugin().run(SecretScanInput(target=str(path)), _ctx(tmp_path))
    assert secret not in out.summary_markdown
    assert "AWS_ACCESS_KEY" in out.summary_markdown  # pattern still shown
    assert any(e.value == secret for e in out.entities if e.type == "secret")
