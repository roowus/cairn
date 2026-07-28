"""write_file — create/overwrite/append a workspace file (agentic)."""

from __future__ import annotations

from pydantic import Field

from cairn.execution.base import BasePlugin, PluginContext, PluginInput, PluginOutput
from cairn.execution.workspace import (
    Deny,
    authorize,
    resolve_in_workspace,
    workspace_roots,
)


class WriteFileInput(PluginInput):
    target: str = Field(
        ...,
        description="Workspace path to write (created/overwritten, or appended).",
    )
    content: str = ""
    append: bool = False


class WriteFileOutput(PluginOutput):
    path: str = ""
    bytes_written: int = 0


class WriteFilePlugin(BasePlugin[WriteFileInput, WriteFileOutput]):
    name = "write_file"
    category = "agentic"
    requires_key = None
    input_model = WriteFileInput
    output_model = WriteFileOutput

    __doc__ = (
        "Write text to a workspace file (target = path; content = text). Creates "
        "parent directories. append=True adds to an existing file instead of "
        "overwriting. Use for notes, decoded output, or scripts to run with "
        "run_command."
    )

    async def run(self, inp: WriteFileInput, ctx: PluginContext) -> WriteFileOutput:
        roots = workspace_roots(ctx)
        decision = await authorize("write", inp.target, roots, getattr(ctx, "permission", None))
        if isinstance(decision, Deny):
            return WriteFileOutput(
                source=self.name,
                path=str(inp.target),
                summary_markdown=f"**write_file denied**: {decision.reason}",
            )
        resolved = resolve_in_workspace(inp.target, roots)
        assert resolved is not None
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with resolved.open("a" if inp.append else "w", encoding="utf-8") as f:
                f.write(inp.content)
        except OSError as exc:
            return WriteFileOutput(
                source=self.name,
                path=str(resolved),
                summary_markdown=f"**write_file error**: {exc}",
            )
        nb = len(inp.content.encode("utf-8"))
        verb = "Appended" if inp.append else "Wrote"
        return WriteFileOutput(
            source=self.name,
            path=str(resolved),
            bytes_written=nb,
            summary_markdown=f"{verb} {nb} bytes to `{resolved}`.",
        )
