"""Enforces the unidirectional dependency rule.

``cairn.reasoning`` must not import from orchestration/execution/interfaces/
storage, nor touch ``subprocess``/``socket``. This is the architectural invariant
that keeps Layer 1 (the LLM) unable to execute anything.
"""

from __future__ import annotations

import ast
from pathlib import Path

REASONING_DIR = Path(__file__).resolve().parents[2] / "src" / "cairn" / "reasoning"
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


def test_reasoning_has_no_upward_or_io_imports():
    files = list(REASONING_DIR.rglob("*.py"))
    assert files, "reasoning package not found"
    offenders: list[str] = []
    for py in files:
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_banned(alias.name):
                        offenders.append(f"{py.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and _is_banned(node.module):
                offenders.append(f"{py.name}: from {node.module} import ...")
    assert not offenders, "reasoning layer violates dependency rule:\n  " + "\n  ".join(offenders)
