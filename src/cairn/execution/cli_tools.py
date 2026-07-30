"""Allowlisted external CLI tools that Cairn can install or hint at.

Plugins like ``sherlock`` and ``holehe`` wrap third-party binaries. Rather than
telling the user to leave the REPL and install them, Cairn can run a *fixed*
``uv tool install <package>`` command from an allowlist — never arbitrary shell,
never a model-supplied package name outside the map.

The allowlist is **two-tier** (see :data:`_TOOLS`):

- **Tier A — ``manager="uv"``** — installable via ``uv tool install``. The core
  identity tools (``sherlock``, ``holehe``) ``bootstrap=True`` (auto-installed at
  session start); the forensic analyzers (``binwalk``, ``oletools``,
  ``html2text``, ``pdfminer.six``) ``bootstrap=False`` (installed on demand via
  the ``install_cli`` plugin, to avoid startup bloat).
- **Tier B — ``manager="system"``** — system packages (``exiftool``, ``tshark``,
  ``nmap``, ``steghide``, …). Cairn never installs these; :func:`ensure_cli_tool`
  returns the ``install_hint`` (``brew`` / ``apt`` / ``gem``) for the brain to
  relay. ``bootstrap=False``.

Also exposed as the ``install_cli`` plugin so the brain can request an install
explicitly, and as ``/install`` in the REPL for humans.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cairn.core.logging import get_logger
from cairn.execution.subprocess_util import SubprocessError, run_subprocess
from cairn.execution.workspace import scrub_env

_log = get_logger("cairn.cli_tools")

# uv tool install puts shims here; ensure we look even if the parent shell PATH
# is thin (e.g. launched from a GUI).
_EXTRA_PATH_DIRS = (
    Path.home() / ".local" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


@dataclass(frozen=True)
class CliToolSpec:
    """One external CLI Cairn knows how to install or hint at."""

    name: str  # logical name / binary name (what users type)
    binary: str  # argv[0] expected on PATH after install
    uv_package: str  # exact package name for `uv tool install` ("" for system tools)
    description: str = ""
    aliases: tuple[str, ...] = ()
    # "uv" → install via `uv tool install <uv_package>`; "system" → never
    # auto-install, relay `install_hint` instead.
    manager: Literal["uv", "system"] = "uv"
    install_hint: str = ""  # shown for system tools (brew/apt/gem …)
    # True → auto-installed at session start (repl bootstrap). False → on demand.
    bootstrap: bool = True
    # OPSEC detectability of the tool itself (mirrors BasePlugin.detectability,
    # moat Pillar 3): "low" passive / "medium" targeted / "high" active scanning.
    # Default "low"; nmap etc. override to "high".
    detectability: str = "low"

    @property
    def install_args(self) -> list[str]:
        return ["uv", "tool", "install", self.uv_package]


# ONLY these packages may ever be installed by Cairn. Keep this tight.
# Tier A — uv-installable; core tools bootstrap, analyzers are on demand.
# Tier B — system packages; hint-only, never installed by Cairn.
_TOOLS: tuple[CliToolSpec, ...] = (
    # --- core identity tools (auto-bootstrap at session start) ---
    CliToolSpec(
        name="sherlock",
        binary="sherlock",
        uv_package="sherlock-project",
        description="Username → 300+ social profile URLs",
        aliases=("sherlock-project",),
        detectability="medium",
    ),
    CliToolSpec(
        name="holehe",
        binary="holehe",
        uv_package="holehe",
        description="Email → registered platforms",
        detectability="medium",
    ),
    # --- Tier A: forensic analyzers (uv, on demand) ---
    CliToolSpec(
        name="binwalk",
        binary="binwalk",
        uv_package="binwalk",
        description="Firmware/binary scan + carve extracted files",
        bootstrap=False,
    ),
    CliToolSpec(
        name="oletools",
        binary="olevba",
        uv_package="oletools",
        description="Office macro/OLE inspection (olevba, oleid, rtfobj)",
        aliases=("olevba", "oleid", "rtfobj"),
        bootstrap=False,
    ),
    CliToolSpec(
        name="html2text",
        binary="html2text",
        uv_package="html2text",
        description="HTML → clean text",
        bootstrap=False,
    ),
    CliToolSpec(
        name="pdfminer.six",
        binary="pdf2txt.py",
        uv_package="pdfminer.six",
        description="PDF → text (pure-python pdftotext)",
        aliases=("pdf2txt",),
        bootstrap=False,
    ),
    # --- Tier B: system packages (hint-only, never auto-installed) ---
    CliToolSpec(
        name="exiftool",
        binary="exiftool",
        uv_package="",
        description="Read/write file metadata (EXIF, doc props)",
        manager="system",
        bootstrap=False,
        install_hint="brew install exiftool (macOS) or apt install libimage-exiftool-perl (Debian)",
    ),
    CliToolSpec(
        name="foremost",
        binary="foremost",
        uv_package="",
        description="Carve files out of a disk/image",
        manager="system",
        bootstrap=False,
        install_hint="brew install foremost (macOS) or apt install foremost (Debian)",
    ),
    CliToolSpec(
        name="tshark",
        binary="tshark",
        uv_package="",
        description="pcap capture/analysis (CLI Wireshark)",
        manager="system",
        bootstrap=False,
        install_hint="brew install --cask wireshark (macOS) or apt install tshark (Debian)",
    ),
    CliToolSpec(
        name="nmap",
        binary="nmap",
        uv_package="",
        description="Network/port discovery (authorized/owned hosts only)",
        manager="system",
        bootstrap=False,
        detectability="high",
        install_hint="brew install nmap (macOS) or apt install nmap (Debian)",
    ),
    CliToolSpec(
        name="dig",
        binary="dig",
        uv_package="",
        description="DNS lookup",
        manager="system",
        bootstrap=False,
        install_hint="brew install bind (macOS) or apt install dnsutils (Debian)",
    ),
    CliToolSpec(
        name="pdftotext",
        binary="pdftotext",
        uv_package="",
        description="PDF → text (poppler)",
        manager="system",
        bootstrap=False,
        install_hint="brew install poppler (macOS) or apt install poppler-utils (Debian)",
    ),
    CliToolSpec(
        name="steghide",
        binary="steghide",
        uv_package="",
        description="Hide/extract data in JPEG/WAV",
        manager="system",
        bootstrap=False,
        install_hint="brew install steghide (macOS) or apt install steghide (Debian)",
    ),
    CliToolSpec(
        name="identify",
        binary="identify",
        uv_package="",
        description="Image format/geometry (ImageMagick)",
        manager="system",
        bootstrap=False,
        install_hint="brew install imagemagick (macOS) or apt install imagemagick (Debian)",
    ),
    CliToolSpec(
        name="zsteg",
        binary="zsteg",
        uv_package="",
        description="Stego detection in PNG/BMP (Ruby gem)",
        manager="system",
        bootstrap=False,
        install_hint="gem install zsteg (requires Ruby)",
    ),
    CliToolSpec(
        name="strings",
        binary="strings",
        uv_package="",
        description="Extract printable strings from a binary",
        manager="system",
        bootstrap=False,
        install_hint="part of binutils (usually present); brew install binutils if missing",
    ),
)


def _index() -> dict[str, CliToolSpec]:
    out: dict[str, CliToolSpec] = {}
    for t in _TOOLS:
        out[t.name.lower()] = t
        out[t.binary.lower()] = t
        if t.uv_package:
            out[t.uv_package.lower()] = t
        for a in t.aliases:
            out[a.lower()] = t
    return out


def list_cli_tools() -> list[CliToolSpec]:
    return list(_TOOLS)


def find_cli_tool(name: str) -> CliToolSpec | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    return _index().get(key)


def which_binary(binary: str) -> str | None:
    """Resolve a binary, augmenting PATH with common user install dirs."""
    found = shutil.which(binary)
    if found:
        return found
    # Search known dirs explicitly (covers thin PATH + post-install before rehash).
    for d in _EXTRA_PATH_DIRS:
        candidate = d / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def tool_is_installed(spec: CliToolSpec) -> bool:
    return which_binary(spec.binary) is not None


def _augment_path_env() -> dict[str, str]:
    """Return a *scrubbed* env with ~/.local/bin prepended so a fresh uv tool is findable.

    Scrubbing matters here, not just on the ``run_command`` path: CLI-tool
    subprocesses (sherlock, holehe, binwalk, …) are often networked, so a
    user-exported secret (``GITHUB_TOKEN``, an AWS key, the LLM key) must never
    reach them. Applies the same :func:`scrub_env` the agentic shell uses, so the
    CLI-tool path can't bypass the secret-hygiene invariant.
    """
    env = scrub_env(os.environ)
    prefix = os.pathsep.join(str(p) for p in _EXTRA_PATH_DIRS if p.is_dir())
    env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}" if prefix else env.get("PATH", "")
    return env


def _progress_start(progress: object | None, name: str, package: str) -> None:
    if progress is None or not hasattr(progress, "on_tool_start"):
        return
    with contextlib.suppress(Exception):
        # Synthetic tool_call_id: this caller is outside the agent loop (no RunContext),
        # but Progress.on_tool_start now requires one. Without it the TypeError is
        # swallowed by this suppress() and the install notification is silently lost.
        progress.on_tool_start("install_cli", name, {"package": package}, "install_cli")  # type: ignore[attr-defined]


def _progress_end(
    progress: object | None,
    name: str,
    status: str,
    summary: str,
    error: str | None,
) -> None:
    if progress is None or not hasattr(progress, "on_tool_end"):
        return
    with contextlib.suppress(Exception):
        progress.on_tool_end("install_cli", name, status, summary, error, "install_cli")  # type: ignore[attr-defined]


async def ensure_missing_cli_tools(
    *,
    install: bool = True,
    timeout: float = 300.0,
    progress: object | None = None,
) -> list[tuple[str, bool, str]]:
    """Ensure every **bootstrappable** CLI is present. Returns per-tool ``(name, ok, msg)``.

    Intended for session startup so the user never has to run ``/install``.
    Iterates only ``bootstrap=True`` uv tools (the core identity tools) —
    on-demand analyzers and system tools are never auto-installed at startup.
    Already-installed tools are skipped quickly.
    """
    results: list[tuple[str, bool, str]] = []
    for spec in _TOOLS:
        if not (spec.bootstrap and spec.manager == "uv"):
            continue
        if tool_is_installed(spec):
            results.append((spec.name, True, "already installed"))
            continue
        ok, msg = await ensure_cli_tool(
            spec.name, install=install, timeout=timeout, progress=progress
        )
        results.append((spec.name, ok, msg))
    return results


async def ensure_cli_tool(
    name: str,
    *,
    install: bool = True,
    timeout: float = 300.0,
    progress: object | None = None,
) -> tuple[bool, str]:
    """Ensure an allowlisted CLI is on PATH; install (uv) or hint (system).

    Returns ``(ok, message)``. Never installs anything outside :data:`_TOOLS`.
    A ``manager="system"`` tool that is missing is **never** installed — its
    ``install_hint`` is returned for the brain to relay to the user.
    """
    spec = find_cli_tool(name)
    if spec is None:
        known = ", ".join(t.name for t in _TOOLS)
        return False, f"Unknown CLI tool {name!r}. Allowlisted: {known}."

    path = which_binary(spec.binary)
    if path:
        return True, f"{spec.binary} already installed at {path}"

    if spec.manager == "system":
        return (
            False,
            f"`{spec.binary}` is a system package Cairn will not auto-install. "
            f"Install it yourself: {spec.install_hint}",
        )

    if not install:
        return (
            False,
            f"{spec.binary} not found (auto-install disabled).",
        )

    if which_binary("uv") is None:
        return (
            False,
            "Cannot auto-install: `uv` is not on PATH "
            "(https://docs.astral.sh/uv/). Cairn installs tools itself via "
            f"`uv tool install {spec.uv_package}` once uv is available.",
        )

    _progress_start(progress, spec.name, spec.uv_package)
    _log.info("auto-installing CLI tool %s via uv tool install %s", spec.name, spec.uv_package)
    try:
        stdout, stderr = await run_subprocess(
            spec.install_args,
            timeout=timeout,
            env=_augment_path_env(),
        )
    except SubprocessError as exc:
        msg = f"Failed to install {spec.name} (`uv tool install {spec.uv_package}`): {exc}"
        _progress_end(progress, spec.name, "error", msg, str(exc))
        return False, msg

    path = which_binary(spec.binary)
    detail = (stdout or stderr).decode(errors="replace").strip()
    if path:
        msg = f"Installed {spec.binary} → {path}"
        if detail:
            msg += f"\n{detail[:500]}"
        _progress_end(progress, spec.name, "ok", msg, None)
        return True, msg

    msg = (
        f"`uv tool install {spec.uv_package}` finished but `{spec.binary}` is still "
        f"not on PATH. Ensure `~/.local/bin` is on PATH and re-open the shell. "
        f"Output: {detail[:400]}"
    )
    _progress_end(progress, spec.name, "error", msg, msg)
    return False, msg


async def run_cli_tool(
    spec: CliToolSpec | str,
    args: list[str],
    *,
    timeout: float = 30.0,
    auto_install: bool = True,
    progress: object | None = None,
    check: bool = True,
    on_line: Callable[[str], None] | None = None,
) -> tuple[bytes, bytes]:
    """Resolve (and optionally install) a CLI, then run it with array args.

    ``args`` are the arguments *after* the binary name. Raises
    :class:`SubprocessError` if install/run fails.

    ``timeout`` is the *process* wall-clock budget (not install). Install uses
    its own ≥300s budget so a long tool run never starves ``uv tool install``.
    """
    if isinstance(spec, str):
        found = find_cli_tool(spec)
        if found is None:
            raise SubprocessError(f"unknown CLI tool: {spec!r}")
        spec = found

    ok, msg = await ensure_cli_tool(
        spec.name,
        install=auto_install,
        timeout=300.0,
        progress=progress,
    )
    if not ok:
        raise SubprocessError(msg)

    binary = which_binary(spec.binary) or spec.binary
    return await run_subprocess(
        [binary, *args],
        timeout=timeout,
        env=_augment_path_env(),
        check=check,
        on_line=on_line,
    )
