"""Enforces the unidirectional dependency rule.

``cairn.reasoning`` AND ``cairn.core`` must not import from
orchestration/execution/interfaces/storage/plugins, nor touch
``subprocess``/``socket``. This is the architectural invariant that keeps Layer 1
(the LLM) unable to execute anything — and keeps the evidence-grade models in
``core/`` (provenance/confidence/severity/typed-assets) free of any IO/exec path.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "src" / "cairn"
REASONING_DIR = _ROOT / "reasoning"
CORE_DIR = _ROOT / "core"
BANNED_PREFIXES = (
    "cairn.orchestration",
    "cairn.execution",
    "cairn.interfaces",
    "cairn.storage",
    "cairn.plugins",
    "subprocess",
    "socket",
)


def _is_banned(module: str) -> bool:
    mod = module.lstrip(".")
    return any(mod == p or mod.startswith(p + ".") for p in BANNED_PREFIXES)


def _upward_or_io_imports(directory: Path) -> list[str]:
    offenders: list[str] = []
    for py in directory.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_banned(alias.name):
                        offenders.append(f"{py.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and _is_banned(node.module):
                offenders.append(f"{py.name}: from {node.module} import ...")
    return offenders


def test_reasoning_has_no_upward_or_io_imports():
    files = list(REASONING_DIR.rglob("*.py"))
    assert files, "reasoning package not found"
    offenders = _upward_or_io_imports(REASONING_DIR)
    assert not offenders, "reasoning layer violates dependency rule:\n  " + "\n  ".join(offenders)


def test_core_has_no_upward_or_io_imports():
    # core/ now carries the load-bearing evidence models (provenance/confidence/
    # severity/typed-assets); it must stay free of any exec/IO/upward import.
    files = list(CORE_DIR.rglob("*.py"))
    assert files, "core package not found"
    offenders = _upward_or_io_imports(CORE_DIR)
    assert not offenders, "core layer violates dependency rule:\n  " + "\n  ".join(offenders)
