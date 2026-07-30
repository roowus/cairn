"""secret_scan — stdlib-only 48-pattern secret/credential scanner (agentic).

The "are there secrets in this artifact?" primitive for OSINT challenges /
forensics: scan a workspace file or directory for hard-coded credentials using a
curated 48-pattern catalog (AWS/GCP/GitHub/Stripe/Slack/AI APIs/package
registries/private keys/...), ported from Claude-OSINT's ``secret_scan.py``
(MIT, arsenal §17). Pure stdlib — no new dependencies.

Findings are emitted as typed ``secret`` entities carrying calibrated severity,
``FIRM`` confidence, and full provenance (producing tool + source file + the
file's SHA-256) — so a discovered key is citable evidence, not a free-floating
string. The ``target`` must resolve inside the workspace; results are wrapped as
untrusted data by the tool closure (the matches are real bytes from an artifact
that may be adversarial).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field

from cairn.core.provenance import Confidence, Provenance, Severity
from cairn.execution.base import (
    BasePlugin,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)
from cairn.execution.workspace import (
    Deny,
    authorize,
    resolve_in_workspace,
    workspace_roots,
)

# The 48-pattern secret catalog (Claude-OSINT arsenal §17). Order matters:
# most-specific patterns first so a generic catch doesn't pre-empt a typed one.
# (name, severity, category, regex)
_PATTERNS: list[tuple[str, Severity, str, str]] = [
    ("AWS_ACCESS_KEY", Severity.CRITICAL, "aws", r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("AWS_SECRET_TYPED", Severity.CRITICAL, "aws",
     r"(?i)aws[_\-]?secret[_\-]?access[_\-]?key['\"\s:=]+([A-Za-z0-9/+=]{40})"),
    ("AWS_SECRET_LOOSE", Severity.HIGH, "aws",
     r"(?i)aws(.{0,20})?(secret|sk)[\"'=: ]+([0-9a-z/+=]{40})"),
    ("GCP_SERVICE_ACCOUNT", Severity.CRITICAL, "gcp", r'"type"\s*:\s*"service_account"'),
    ("GOOGLE_API_KEY", Severity.HIGH, "gcp", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("GH_PAT_CLASSIC", Severity.CRITICAL, "github", r"\bghp_[A-Za-z0-9]{36}\b"),
    ("GH_PAT_FINEGRAINED", Severity.CRITICAL, "github", r"\bgithub_pat_[A-Za-z0-9_]{82}\b"),
    ("GH_OAUTH", Severity.HIGH, "github", r"\bgho_[A-Za-z0-9]{36}\b"),
    ("GH_S2S", Severity.HIGH, "github", r"\bgh[usr]_[A-Za-z0-9]{36,}\b"),
    ("STRIPE_LIVE", Severity.CRITICAL, "stripe", r"\bsk_live_[0-9A-Za-z]{24,}\b"),
    ("STRIPE_TEST", Severity.LOW, "stripe", r"\bsk_test_[0-9A-Za-z]{24,}\b"),
    ("SLACK_TOKEN", Severity.HIGH, "slack", r"\bxox[abpors]-[0-9A-Za-z\-]{10,48}\b"),
    ("SLACK_WEBHOOK", Severity.MEDIUM, "slack",
     r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    ("SENDGRID", Severity.HIGH, "email_svc", r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b"),
    ("MAILGUN_V1", Severity.HIGH, "email_svc", r"\bkey-[0-9a-zA-Z]{32}\b"),
    ("MAILGUN_LOOSE", Severity.HIGH, "email_svc", r"\bkey-[0-9a-f]{32}\b"),
    ("TWILIO_API", Severity.HIGH, "twilio", r"\bSK[0-9a-fA-F]{32}\b"),
    ("TWILIO_SID", Severity.MEDIUM, "twilio", r"\bAC[a-f0-9]{32}\b"),
    ("TWILIO_AUTH", Severity.HIGH, "twilio",
     r"(?i)twilio(.{0,20})?(auth|token)[\"'=: ]+([a-f0-9]{32})"),
    ("HEROKU_API", Severity.MEDIUM, "paas",
     r"(?i)heroku(.{0,20})?api[\"'=: ]+"
     r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"),
    ("FIREBASE_URL", Severity.LOW, "firebase", r"\bhttps?://[a-z0-9\-]+\.firebaseio\.com\b"),
    ("JWT", Severity.MEDIUM, "jwt",
     r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    ("BEARER_AUTH", Severity.MEDIUM, "bearer",
     r"(?i)authorization[\"'=: ]+bearer\s+[A-Za-z0-9._\-]{20,}"),
    ("BASIC_AUTH_URL", Severity.MEDIUM, "basic_auth", r"https?://[^/\s:@]+:[^/\s:@]+@[^/\s]+"),
    ("RSA_PRIVKEY", Severity.CRITICAL, "private_key", r"-----BEGIN RSA PRIVATE KEY-----"),
    ("EC_PRIVKEY", Severity.CRITICAL, "private_key", r"-----BEGIN EC PRIVATE KEY-----"),
    ("OPENSSH_PRIVKEY", Severity.CRITICAL, "private_key", r"-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("GENERIC_PRIVKEY", Severity.CRITICAL, "private_key",
     r"-----BEGIN (DSA |PGP |)PRIVATE KEY-----"),
    ("GENERIC_API_KEY", Severity.MEDIUM, "generic",
     r"(?i)(?:api[_\-]?key|apikey|api_secret|access_token|secret[_\-]?token)"
     r"['\"\s:=]+[\"']([A-Za-z0-9+/=_\-]{24,})[\"']"),
    ("ANTHROPIC_API", Severity.CRITICAL, "ai_api",
     r"\bsk-ant-(?:api03|admin01)-[A-Za-z0-9_\-]{93,}\b"),
    ("OPENAI_LEGACY", Severity.CRITICAL, "ai_api",
     r"\bsk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}\b"),
    ("OPENAI_PROJECT", Severity.CRITICAL, "ai_api",
     r"\bsk-proj-[A-Za-z0-9_\-]{40,}T3BlbkFJ[A-Za-z0-9_\-]{40,}\b"),
    ("OPENAI_SESSION", Severity.HIGH, "ai_api", r"\bsess-[A-Za-z0-9]{40}\b"),
    ("HUGGINGFACE", Severity.HIGH, "ai_api", r"\bhf_[A-Za-z0-9]{30,}\b"),
    ("CLOUDFLARE_API", Severity.CRITICAL, "infra_api",
     r"(?i)cf[_\-]?api[_\-]?key['\"\s:=]+([a-f0-9]{37})"),
    ("DIGITALOCEAN", Severity.HIGH, "infra_api", r"\bdop_v1_[a-f0-9]{64}\b"),
    ("NPM_TOKEN", Severity.HIGH, "package_registry", r"\bnpm_[A-Za-z0-9]{36}\b"),
    ("PYPI_TOKEN", Severity.HIGH, "package_registry", r"\bpypi-AgENdGV[A-Za-z0-9_\-]+\b"),
    ("DOCKER_HUB_PAT", Severity.HIGH, "package_registry", r"\bdckr_pat_[A-Za-z0-9_\-]{27,}\b"),
    ("ATLASSIAN_TOKEN", Severity.HIGH, "saas_api", r"\bATATT3xFfGF0[A-Za-z0-9_\-]{180,}\b"),
    ("LINEAR_API", Severity.MEDIUM, "saas_api", r"\blin_api_[A-Za-z0-9]{40}\b"),
    ("NEWRELIC_LICENSE", Severity.MEDIUM, "observability", r"\b(?:NRAA|NRAK|NRBR)-[A-F0-9]{27}\b"),
    ("DATADOG_API", Severity.HIGH, "observability",
     r"(?i)dd[_\-]?api[_\-]?key['\"\s:=]+([a-f0-9]{32})"),
    ("SENTRY_DSN", Severity.LOW, "observability", r"https://[a-f0-9]+@o[0-9]+\.ingest\.sentry\.io/[0-9]+"),
    ("NGROK_AUTH", Severity.MEDIUM, "tunneling", r"\b[12][A-Za-z0-9]{26}_[A-Za-z0-9]{32,}\b"),
    ("DISCORD_BOT", Severity.HIGH, "bot_token", r"\b[MN][A-Za-z\d]{23}\.[\w\-]{6}\.[\w\-]{27}\b"),
    ("TELEGRAM_BOT", Severity.HIGH, "bot_token", r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
]
_COMPILED = [(n, s, c, re.compile(p)) for (n, s, c, p) in _PATTERNS]

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".cache"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # skip files > 10 MiB
_MATCH_TRUNC = 80
_MAX_FINDINGS = 200


class SecretFinding(BaseModel):
    pattern: str
    severity: Severity
    category: str
    match: str  # truncated to _MATCH_TRUNC
    source: str  # file path
    line: int


class SecretScanInput(PluginInput):
    """``target`` is a workspace file or directory to scan for secrets."""

    target: str = Field(
        ...,
        description=(
            "Workspace path (file or dir) to scan. cwd + ~/.cairn/workspace both accessible."
        ),
    )
    max_findings: int = Field(default=_MAX_FINDINGS, ge=1, le=2000)


class SecretScanOutput(PluginOutput):
    findings: list[SecretFinding] = Field(default_factory=list)
    files_scanned: int = 0


class SecretScanPlugin(BasePlugin[SecretScanInput, SecretScanOutput]):
    name = "secret_scan"
    category = "agentic"
    requires_key = None
    detectability = "low"  # local artifact scan — no target contact
    input_model = SecretScanInput
    output_model = SecretScanOutput

    __doc__ = (
        "Scan a workspace file/dir for hard-coded secrets (target = path). 48-pattern "
        "catalog: AWS/GCP/GitHub/Stripe/Slack/AI APIs/npm/PyPI/private keys/... "
        "(Claude-OSINT arsenal). Returns findings (pattern/severity/match/source/line) "
        "as secret entities with provenance (tool + file + file SHA-256). "
        "For artifacts/challenge files; results are untrusted (wrapped)."
    )

    async def run(self, inp: SecretScanInput, ctx: PluginContext) -> SecretScanOutput:
        roots = workspace_roots(ctx)
        decision = await authorize("read", inp.target, roots, getattr(ctx, "permission", None))
        if isinstance(decision, Deny):
            return SecretScanOutput(
                source=self.name,
                summary_markdown=f"**secret_scan denied**: {decision.reason}",
            )
        resolved = resolve_in_workspace(inp.target, roots)
        assert resolved is not None  # authorize() Allow → inside the workspace

        files = _collect_files(resolved)
        findings: list[SecretFinding] = []
        entities: list[Entity] = []
        seen_values: set[str] = set()
        for path in files:
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if len(raw) > _MAX_FILE_BYTES:
                continue
            digest = hashlib.sha256(raw).hexdigest()
            text = raw.decode("utf-8", errors="replace")
            for name, sev, cat, rx in _COMPILED:
                for line_no, line in enumerate(text.splitlines(), start=1):
                    for m in rx.finditer(line):
                        match = m.group(0)[:_MATCH_TRUNC]
                        findings.append(
                            SecretFinding(
                                pattern=name, severity=sev, category=cat,
                                match=match, source=str(path), line=line_no,
                            )
                        )
                        if match not in seen_values:
                            seen_values.add(match)
                            entities.append(
                                Entity(
                                    type="secret",
                                    value=match,
                                    attrs={"pattern": name, "severity": sev.value, "category": cat},
                                    confidence=Confidence.FIRM,
                                    provenance=Provenance(
                                        tool="secret_scan",
                                        source_url=f"file://{path}",
                                        raw_sha256=digest,
                                    ),
                                )
                            )
                        if len(findings) >= inp.max_findings:
                            out = SecretScanOutput(
                                source=self.name,
                                findings=findings,
                                files_scanned=len(files),
                            )
                            out.entities = entities
                            out.summary_markdown = _summary(findings, len(files), capped=True)
                            return out

        out = SecretScanOutput(source=self.name, findings=findings, files_scanned=len(files))
        out.entities = entities
        out.summary_markdown = _summary(findings, len(files), capped=False)
        return out


def _collect_files(target: Path) -> list[Path]:
    if target.is_dir():
        out: list[Path] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            out.extend(Path(root) / f for f in files)
        return out
    return [target] if target.is_file() else []


def _summary(findings: list[SecretFinding], files_scanned: int, *, capped: bool) -> str:
    if not findings:
        return f"Scanned **{files_scanned}** file(s); no secrets matched."
    by_sev: dict[Severity, list[SecretFinding]] = {}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)
    order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
    lines = [f"Scanned **{files_scanned}** file(s); **{len(findings)}** secret(s) found:"]
    for sev in order:
        for f in by_sev.get(sev, []):
            # The live credential is NOT placed in the summary. The summary is
            # wrapped (anti-injection) but NOT redacted — it still reaches model
            # context, and CLAUDE.md invariant #3 forbids secrets there. The full
            # (length-truncated) value lives on the graph entity (the evidence
            # locker, human-only); here we show only the typed pattern + severity
            # + a length hint + location, so the model can act ("rotate the AWS
            # key at config.js:42") without seeing the secret itself.
            lines.append(
                f"- **[{sev.value.upper()}]** `{f.pattern}` ({f.category}) "
                f"— redacted secret ({len(f.match)} chars) @ {f.source}:{f.line}"
            )
    if capped:
        lines.append("- _(result cap reached; rerun on a narrower path for more)_")
    return "\n".join(lines)
