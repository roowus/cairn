"""install_cli — allowlisted external CLI installer the brain can call.

When ``sherlock`` / ``holehe`` (etc.) are missing, the model should call this
tool (or the plugins auto-install themselves). Only packages in
``execution.cli_tools`` may be installed — never arbitrary shell or PyPI names.
"""

from __future__ import annotations

from pydantic import Field

from cairn.execution.base import BasePlugin, PluginContext, PluginInput, PluginOutput
from cairn.execution.cli_tools import ensure_cli_tool, list_cli_tools, tool_is_installed


class InstallCliInput(PluginInput):
    """``target`` is the tool name (e.g. ``sherlock``, ``holehe``)."""

    # PluginInput requires `target`; document it.
    target: str = Field(  # type: ignore[assignment]
        ...,
        description=(
            "CLI tool to check/repair. Allowlisted: "
            + ", ".join(t.name for t in list_cli_tools())
            + ". Prefer calling sherlock/holehe directly (they auto-install). "
            "target='list' status; target='all' install any missing."
        ),
    )


class InstallCliOutput(PluginOutput):
    installed: bool = False
    detail: str = ""


class InstallCliPlugin(BasePlugin[InstallCliInput, InstallCliOutput]):
    name = "install_cli"
    category = "identity"
    requires_key = None
    input_model = InstallCliInput
    output_model = InstallCliOutput

    __doc__ = (
        "Check/repair allowlisted external CLIs (sherlock, holehe). "
        "Usually unnecessary: those plugins auto-install on first use and at "
        "session start. target='list' shows status; target='all' installs any "
        "missing. Uses `uv tool install <fixed-package>` only."
    )

    async def run(self, inp: InstallCliInput, ctx: PluginContext) -> InstallCliOutput:
        name = (inp.target or "").strip().lower()
        if name in {"list", "ls", "status", "?"}:
            lines = []
            for t in list_cli_tools():
                installed = tool_is_installed(t)
                if t.manager == "uv":
                    mark = "✓" if installed else "— (installs on demand via uv)"
                    pkg = f"`{t.uv_package}`"
                else:
                    mark = "✓" if installed else f"— system: {t.install_hint}"
                    pkg = "(system)"
                lines.append(f"- {mark} **{t.name}** {pkg} — {t.description}")
            body = (
                "Allowlisted CLI tools (Cairn installs these itself — "
                "you do not need to run anything):\n" + "\n".join(lines)
            )
            return InstallCliOutput(
                source=self.name,
                summary_markdown=body,
                installed=False,
                detail="list",
            )

        if name in {"all", "*", "missing"}:
            from cairn.execution.cli_tools import ensure_missing_cli_tools

            rows = await ensure_missing_cli_tools(
                install=True,
                timeout=max(ctx.timeout, 300.0),
                progress=ctx.progress,
            )
            lines = [f"- {'✓' if ok else '✗'} **{n}** — {msg}" for n, ok, msg in rows]
            all_ok = all(ok for _, ok, _ in rows)
            return InstallCliOutput(
                source=self.name,
                summary_markdown="CLI tool status:\n" + "\n".join(lines),
                installed=all_ok,
                detail="all",
            )

        ok, msg = await ensure_cli_tool(
            name,
            install=True,
            timeout=max(ctx.timeout, 300.0),
            progress=ctx.progress,
        )
        return InstallCliOutput(
            source=self.name,
            summary_markdown=f"**install_cli({name})** — {msg}",
            installed=ok,
            detail=msg,
            entities=[],
        )
