"""Skills — packaged investigation workflows (the OSINT analogue of Claude Code
skills / OpenOSINT YAML playbooks).

A skill is a Markdown playbook: a reusable investigation recipe (objective →
tool sequence → what to pivot on → how to phrase findings). The user invokes one
by name in the REPL (``/investigate-person <handle>``); the dispatcher injects
the playbook as extra context for that turn. **A skill orchestrates existing
tools — it adds no new capability, only know-how.**

Discovery: built-in skills ship under ``cairn/skills/builtins/``; user skills
live in ``~/.cairn/skills/``. A user skill with the same ``name`` overrides the
built-in. Markdown only — no YAML dependency (a tiny frontmatter parser).

The brain still does all the reasoning; the skill just primes it for a known
investigation shape (see docs/architecture/claude-code-model.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cairn.core import paths
from cairn.core.logging import get_logger

_log = get_logger("cairn.skills")
_BUILTIN_DIR = Path(__file__).parent / "builtins"


@dataclass(frozen=True)
class Skill:
    """One investigation playbook."""

    name: str  # invocation key, e.g. "investigate-person"
    description: str  # one-line summary for /skills
    usage: str  # e.g. "/investigate-person <username or handle>"
    body: str  # the playbook Markdown, prepended to the turn


def _parse(text: str, fallback_name: str) -> Skill:
    """Parse a skill file: optional ``---`` frontmatter (name/description/usage)
    then the body. Falls back to filename + first line if no frontmatter."""
    name = fallback_name
    description = ""
    usage = ""
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            header = parts[1]
            body = parts[2].lstrip("\n")
            for line in header.splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, _, val = line.partition(":")
                key, val = key.strip().lower(), val.strip()
                if key == "name":
                    name = val
                elif key == "description":
                    description = val
                elif key == "usage":
                    usage = val
    if not description:
        # first markdown heading or first non-empty line
        for line in body.splitlines():
            s = line.strip().lstrip("#").strip()
            if s:
                description = s
                break
    if not usage:
        usage = f"/{name} <target>"
    return Skill(
        name=name or fallback_name,
        description=description,
        usage=usage,
        body=body.strip(),
    )


def _load_dir(directory: Path) -> dict[str, Skill]:
    out: dict[str, Skill] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            _log.warning("could not read skill %s: %s", path, exc)
            continue
        skill = _parse(text, path.stem)
        out[skill.name] = skill
    return out


def discover_skills() -> dict[str, Skill]:
    """Built-in skills, overridden by the user's ``~/.cairn/skills/``."""
    skills = _load_dir(_BUILTIN_DIR)
    user_dir = paths.config_dir() / "skills"
    skills.update(_load_dir(user_dir))  # user overrides built-in on name clash
    _log.info("loaded %d skill(s): %s", len(skills), sorted(skills))
    return skills


def render_turn(skill: Skill, request: str) -> str:
    """Build the turn prompt: the playbook, then the user's actual request."""
    return f"{skill.body}\n\n---\n\nInvestigation request: {request.strip()}"
