"""Agentic workspace: boundary checks, the permission gate, and env scrubbing.

Cairn's defining property is the anti-injection hard-stop: the *results* of every
read/download/command flow back to the model wrapped in
``<untrusted_external_data>`` (see :mod:`cairn.core.security`). The agentic file
tools (``cairn.plugins.agentic.*``) relax a *different* layer — *execution
permission* — letting the model freely read/write/run inside a workspace. These
two layers are independent; relaxing execution does **not** relax anti-injection.

The v1 permission policy is a pure function (no prompt): an op is allowed iff its
target resolves inside the workspace roots (cwd + scratch dir). Anything outside is
denied. :class:`PermissionUI` is the seam for a future interactive accept/deny
prompt (v2); v1 ships :class:`NullPermissionUI`, which denies without prompting.

Containment caveat: "auto-allow in sandbox" is a **policy/intent boundary, not
OS-enforced containment.** ``run_command`` can escape the workspace (a symlink,
``cp ~/``, ``curl | sh``). OS-level sandboxing (firejail / bubblewrap / container)
is flagged future work; we never claim airtight containment. See
``docs/architecture/security.md``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# --- boundary checks ---------------------------------------------------------


def workspace_roots(ctx: Any) -> list[Path]:
    """The trust boundary for agentic ops: cwd plus the scratch workspace dir.

    cwd is always a root so challenge files in ``./`` are directly accessible.
    ``PluginContext.workspace`` (the scratch dir, default ``~/.cairn/workspace``)
    is added when set.
    """
    roots = [Path.cwd()]
    ws = getattr(ctx, "workspace", None)
    if ws:
        roots.append(Path(ws).expanduser())
    return roots


def resolve_in_workspace(target: str | Path, roots: Sequence[Path]) -> Path | None:
    """Resolve ``target`` and return it iff it equals or sits under a workspace root.

    ``Path.resolve(strict=False)`` collapses ``..`` and follows symlinks, so an
    ``../../etc/passwd`` escape or a symlink pointing outside the workspace
    resolves outside the roots and is rejected. Returns ``None`` when the target
    is outside the workspace or cannot be resolved.
    """
    try:
        p = Path(target).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    for root in roots:
        try:
            r = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if p == r or r in p.parents:
            return p
    return None


def is_inside_workspace(target: str | Path, roots: Sequence[Path]) -> bool:
    """True iff ``target`` resolves inside one of ``roots``."""
    return resolve_in_workspace(target, roots) is not None


# --- permission gate ---------------------------------------------------------


@dataclass(frozen=True)
class Allow:
    """The op is permitted (target resolves inside the workspace)."""


@dataclass(frozen=True)
class Deny:
    """The op is denied; ``reason`` is human-readable (relayed to the model)."""

    reason: str


PermissionDecision = Allow | Deny


def decide(op: str, target: str | Path, roots: Sequence[Path]) -> PermissionDecision:
    """Pure v1 policy: allow iff ``target`` resolves inside the workspace roots."""
    if is_inside_workspace(target, roots):
        return Allow()
    return Deny(f"{op} target is outside the workspace (cwd + scratch dir).")


@dataclass(frozen=True)
class PermissionRequest:
    """An out-of-workspace op surfaced for interactive accept/deny (v2)."""

    op: str
    target: str
    reason: str


class PermissionUI(Protocol):
    """v2 seam: surface an out-of-workspace op for an interactive accept/deny."""

    async def request(self, decl: PermissionRequest) -> bool: ...


class NullPermissionUI:
    """v1 default: never prompt. ``request`` always denies, so out-of-workspace
    ops are blocked without a UI. In-workspace ops never reach ``request`` (they
    are :class:`Allow`-ed by :func:`decide` before the UI is consulted)."""

    async def request(self, decl: PermissionRequest) -> bool:
        return False


async def authorize(
    op: str,
    target: str | Path,
    roots: Sequence[Path],
    permission: PermissionUI | None,
) -> PermissionDecision:
    """Resolve a permission decision, consulting the UI only for denials.

    In-workspace ops return :class:`Allow` without prompting (the auto-allow
    policy). Out-of-workspace ops are denied unless a UI grants them — v1 has no
    UI, so they deny. Cancel-safe: a future interactive UI awaits an
    ``asyncio.Event`` (cancellable), so Esc/Ctrl-C (``task.cancel()``) always wins.
    """
    decision = decide(op, target, roots)
    if isinstance(decision, Allow):
        return decision
    if permission is None:
        return decision
    granted = await permission.request(
        PermissionRequest(op, str(target), decision.reason)
    )
    return Allow() if granted else decision


# --- secret hygiene before exec ---------------------------------------------


# Env var *names* that must never reach a subprocess. Keys in PluginContext.keys
# are SecretStr and never reach os.environ; this catches a key the user `export`ed.
# Env var *names* that must never reach a subprocess. Broad on purpose: a false
# positive only drops a (rarely-needed) var from the child env, while a false
# negative leaks a secret. Keys in PluginContext.keys are SecretStr and never
# reach os.environ; this catches a key the user `export`ed under a non-standard
# name (AUTH, COOKIE, PRIVATE_KEY, PASSWD, APIKEY, ACCESS_KEY, …).
_SECRET_NAME_RE = re.compile(
    r"(?i).*(API_KEY|APIKEY|TOKEN|SECRET|PASSWD|PASSWORD|"
    r"AUTHORIZATION|AUTH|BEARER|CREDENTIAL|COOKIE|"
    r"ACCESS_KEY|PRIVATE_KEY|PRIVATEKEY|KEYFILE|SIGNING_KEY).*"
)
# Secret shapes in env *values* — last-resort backstop when the *name* looks
# innocuous (mirrors the shapes cairn.core.security redacts).
_SECRET_VALUE_RES: tuple[re.Pattern[str], ...] = (
    # AWS access-key IDs: long-term (AKIA) + STS temporary (ASIA) + role/user.
    re.compile(r"(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),        # OpenAI-style keys
    re.compile(r"gh[opsu]_[A-Za-z0-9]{36,}"),     # GitHub PAT (ghp_/gho_/ghs_/ghu_)
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),  # GitHub fine-grained PAT
)


def scrub_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of ``env`` with secret-looking names/values removed.

    Strips: any ``CAIRN_*`` var; any var whose name matches a secret pattern
    (``*_API_KEY``, ``*_TOKEN``, ``AUTHORIZATION``, ``*PASSWORD``, …); any var
    whose value looks like a known secret shape (``sk-…``, ``AKIA…``). Keeps
    ``PATH``, ``HOME``, ``USER``, ``SHELL``, locale, ``TERM``, ``TMPDIR``.
    """
    out: dict[str, str] = {}
    for name, value in env.items():
        u = name.upper()
        if u.startswith("CAIRN_"):
            continue
        if _SECRET_NAME_RE.match(u):
            continue
        if isinstance(value, str) and any(p.search(value) for p in _SECRET_VALUE_RES):
            continue
        out[name] = value
    return out


# --- workspace view (for the /workspace command; Phase 4) -------------------


def list_workspace_tree(
    roots: Sequence[Path],
    *,
    max_depth: int = 3,
    max_entries: int = 500,
) -> str:
    """Render a depth-limited tree of the workspace roots with file sizes.

    Pure read; never raises on permission errors (skips unreadable entries). Used
    by the ``/workspace`` (``/files``) REPL command.
    """
    lines: list[str] = []
    seen = 0

    def _walk(path: Path, prefix: str, depth: int) -> None:
        nonlocal seen
        if seen >= max_entries or depth > max_depth:
            return
        try:
            entries = sorted(
                path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())
            )
        except (OSError, PermissionError):
            return
        for entry in entries:
            if seen >= max_entries:
                return
            seen += 1
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            if is_dir:
                lines.append(f"{prefix}{entry.name}/")
                _walk(entry, prefix + "    ", depth + 1)
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = -1
                lines.append(f"{prefix}{entry.name}  ({_human(size)})")

    for root in roots:
        try:
            resolved = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        lines.append(str(resolved))
        _walk(resolved, "", 1)
        lines.append("")
    return "\n".join(lines).rstrip()


def _human(n: int) -> str:
    if n < 0:
        return "?"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
