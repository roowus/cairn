"""core/provenance.py — confidence, severity, provenance, findings (moat P2/P4)."""

from __future__ import annotations

from datetime import UTC

from cairn.core.provenance import (
    Confidence,
    Evidence,
    Finding,
    Provenance,
    Severity,
    make_id,
    utc_now,
)

# --- Confidence --------------------------------------------------------------


def test_confidence_from_sources():
    assert Confidence.from_sources(0) is Confidence.TENTATIVE
    assert Confidence.from_sources(1) is Confidence.TENTATIVE
    assert Confidence.from_sources(2) is Confidence.FIRM
    # count alone never earns confirmed
    assert Confidence.from_sources(5) is Confidence.FIRM


def test_confidence_aggregate_takes_max_but_never_manufactures_confirmed():
    assert Confidence.aggregate([]) is Confidence.TENTATIVE
    two_tent = Confidence.aggregate([Confidence.TENTATIVE, Confidence.TENTATIVE])
    assert two_tent is Confidence.TENTATIVE
    assert Confidence.aggregate([Confidence.TENTATIVE, Confidence.FIRM]) is Confidence.FIRM
    assert Confidence.aggregate([Confidence.FIRM, Confidence.CONFIRMED]) is Confidence.CONFIRMED
    # confirmed requires a real confirming signal — three tentatives stay tentative:
    assert Confidence.aggregate([Confidence.TENTATIVE] * 3) is Confidence.TENTATIVE


# --- Severity ----------------------------------------------------------------


def test_severity_ordering_and_escalation():
    assert Severity.HIGH > Severity.LOW
    assert Severity.CRITICAL >= Severity.CRITICAL
    assert not (Severity.LOW > Severity.MEDIUM)
    # one-way escalation: a higher target wins, a lower one is ignored
    assert Severity.escalate(Severity.MEDIUM, Severity.HIGH) is Severity.HIGH
    assert Severity.escalate(Severity.HIGH, Severity.MEDIUM) is Severity.HIGH


# --- Provenance / Evidence ---------------------------------------------------


def test_evidence_raw_is_capped_to_2kib():
    ev = Evidence(raw="A" * 5000)
    assert len(ev.raw) <= 2048
    assert ev.raw == "A" * 2048


def test_provenance_carries_chain_of_custody():
    p = Provenance(
        tool="download_url",
        source_url="https://example.com/leak.txt",
        raw_sha256="abc123",
    )
    assert p.tool == "download_url"
    assert p.archive_ref is None


def test_utc_now_is_timezone_aware():
    assert utc_now().tzinfo is UTC


# --- Finding -----------------------------------------------------------------


def test_finding_backfills_stable_id_and_renders():
    f = Finding(
        module="secret_scan",
        asset_key="secret:github_pat_abc",
        category="SECRET_LEAK",
        severity=Severity.CRITICAL,
        confidence=Confidence.FIRM,
        title="GitHub PAT in config.js",
        description="A fine-grained PAT was found hard-coded.",
        evidence=Evidence(url="file://repo/config.js", sha256="deadbeef"),
        remediation="Rotate the token; move secrets to env/secret store.",
    )
    assert f.id  # backfilled
    expected = make_id(
        "secret_scan", "secret:github_pat_abc", "SECRET_LEAK", "GitHub PAT in config.js"
    )
    assert f.id == expected
    md = f.to_markdown()
    assert "[CRITICAL]" in md
    assert "confidence **firm**" in md
    assert "secret:github_pat_abc" in md
    assert "Rotate the token" in md


def test_finding_id_is_deterministic_for_same_inputs():
    a = make_id("m", "k", "c", "t")
    b = make_id("m", "k", "c", "t")
    c = make_id("m", "k", "c", "different")
    assert a == b
    assert a != c


def test_explicit_finding_id_is_preserved():
    f = Finding(module="x", asset_key="ip:1.1.1.1", category="C", title="t", id="custom123")
    assert f.id == "custom123"
