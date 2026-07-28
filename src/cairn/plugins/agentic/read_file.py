"""read_file — read a workspace file's contents (agentic).

The agent's "look at this file" primitive for OSINT challenges: read a challenge
file, a downloaded artifact, or analyzer output. The ``target`` must resolve
inside the workspace (cwd + scratch); the *result* is wrapped as untrusted data
by the tool closure, so adversarial file contents cannot inject instructions.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from cairn.core.entities import extract_entities
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

_MAX_BYTES = 200_000  # cap a single physical read (~200KB)
_MAX_SUMMARY = 12_000  # cap what is surfaced to the model in the summary


class ReadFileInput(PluginInput):
    """``target`` is a workspace path to read."""

    target: str = Field(
        ...,
        description="Workspace path to read (cwd and ~/.cairn/workspace are both accessible).",
    )
    max_bytes: int = _MAX_BYTES


class ReadFileOutput(PluginOutput):
    path: str = ""
    bytes_read: int = 0
    truncated: bool = False


class ReadFilePlugin(BasePlugin[ReadFileInput, ReadFileOutput]):
    name = "read_file"
    category = "agentic"
    requires_key = None
    input_model = ReadFileInput
    output_model = ReadFileOutput

    __doc__ = (
        "Read a file inside the workspace (target = path; cwd and ~/.cairn/workspace "
        "are both accessible). Returns the text (capped) — useful for challenge "
        "files, downloaded artifacts, and analyzer output. Non-text bytes are "
        "decoded best-effort. Mines IOC entities (emails/IPs/domains/URLs) for pivoting."
    )

    async def run(self, inp: ReadFileInput, ctx: PluginContext) -> ReadFileOutput:
        roots = workspace_roots(ctx)
        decision = await authorize("read", inp.target, roots, getattr(ctx, "permission", None))
        if isinstance(decision, Deny):
            return ReadFileOutput(
                source=self.name,
                path=str(inp.target),
                summary_markdown=f"**read_file denied**: {decision.reason}",
            )
        resolved = resolve_in_workspace(inp.target, roots)
        assert resolved is not None  # Allow guarantees a resolved path
        try:
            data = resolved.read_bytes()
        except OSError as exc:
            return ReadFileOutput(
                source=self.name,
                path=str(resolved),
                summary_markdown=f"**read_file error**: cannot read `{resolved}` ({exc})",
            )
        total = len(data)
        truncated = total > inp.max_bytes
        if truncated:
            data = data[: inp.max_bytes]
        text = data.decode("utf-8", errors="replace")
        out = ReadFileOutput(
            source=self.name,
            path=str(resolved),
            bytes_read=total,
            truncated=truncated,
        )
        out.summary_markdown = _summary(resolved, text, total, truncated)
        out.entities = _entities(text)
        return out


def _summary(path: Path, text: str, total: int, truncated: bool) -> str:
    shown = text[:_MAX_SUMMARY]
    more = "…" if len(text) > _MAX_SUMMARY else ""
    tag = f" ({total} bytes, truncated)" if truncated else f" ({total} bytes)"
    return f"`{path}`{tag}\n\n```\n{shown}{more}\n```"


def _entities(text: str) -> list[Entity]:
    seen: set[tuple[str, str]] = set()
    ents: list[Entity] = []
    for ex in extract_entities(text):
        key = (ex.type, ex.value.lower())
        if key in seen:
            continue
        seen.add(key)
        ents.append(Entity(type=ex.type, value=ex.value))
    return ents
