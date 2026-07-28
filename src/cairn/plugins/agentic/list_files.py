"""list_files — list a workspace directory tree (agentic)."""

from __future__ import annotations

from pydantic import Field

from cairn.execution.base import BasePlugin, PluginContext, PluginInput, PluginOutput
from cairn.execution.workspace import (
    Deny,
    authorize,
    list_workspace_tree,
    resolve_in_workspace,
    workspace_roots,
)


class ListFilesInput(PluginInput):
    target: str = Field(..., description="Workspace directory to list (use '.' for cwd).")
    max_depth: int = 3
    max_entries: int = 500


class ListFilesOutput(PluginOutput):
    root: str = ""
    entry_count: int = 0


class ListFilesPlugin(BasePlugin[ListFilesInput, ListFilesOutput]):
    name = "list_files"
    category = "agentic"
    requires_key = None
    input_model = ListFilesInput
    output_model = ListFilesOutput

    __doc__ = (
        "List files under a workspace directory (target = path; use '.' for cwd). "
        "Depth-limited tree with file sizes — find challenge files and artifacts "
        "before reading/analyzing them."
    )

    async def run(self, inp: ListFilesInput, ctx: PluginContext) -> ListFilesOutput:
        roots = workspace_roots(ctx)
        target = inp.target or "."
        decision = await authorize("list", target, roots, getattr(ctx, "permission", None))
        if isinstance(decision, Deny):
            return ListFilesOutput(
                source=self.name,
                root=str(target),
                summary_markdown=f"**list_files denied**: {decision.reason}",
            )
        resolved = resolve_in_workspace(target, roots)
        assert resolved is not None
        tree = list_workspace_tree(
            [resolved], max_depth=inp.max_depth, max_entries=inp.max_entries
        )
        return ListFilesOutput(
            source=self.name,
            root=str(resolved),
            entry_count=tree.count(chr(10)),
            summary_markdown=tree or "(empty directory)",
        )
