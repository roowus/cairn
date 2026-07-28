"""holehe — email → registered platforms, via the `holehe` CLI (free, no key).

Wraps the external `holehe` binary through the safe subprocess runner. If the
binary is missing, Cairn auto-installs the allowlisted ``holehe`` package via
``uv tool install`` (see ``execution.cli_tools``).

Holehe probes many sites and often needs well over the HTTP ``ctx.timeout``
(30s), so the process budget is independent of that default.
"""

from __future__ import annotations

import contextlib
import re

from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput
from cairn.execution.cli_tools import run_cli_tool
from cairn.execution.subprocess_util import SubprocessError

# holehe prints "[+] domain.tld …" for registered addresses only (--only-used).
_FOUND = re.compile(r"^\[\+\]\s+(\S+)", re.MULTILINE)

_DEFAULT_OVERALL_TIMEOUT = 180.0


class HoleheInput(PluginInput):
    """`target` is an email address."""

    overall_timeout: float = Field(
        default=_DEFAULT_OVERALL_TIMEOUT,
        ge=30.0,
        le=600.0,
        description="Wall-clock budget for the entire holehe process (seconds).",
    )


class HoleheOutput(PluginOutput):
    sites: list[str] = Field(default_factory=list)


class HolehePlugin(BasePlugin[HoleheInput, HoleheOutput]):
    name = "holehe"
    category = "identity"
    requires_key = None
    input_model = HoleheInput
    output_model = HoleheOutput

    __doc__ = (
        "Check which platforms an email (target) is registered on, via holehe. "
        "Can take 1-2 minutes. Auto-installs the binary if missing."
    )

    async def run(self, inp: HoleheInput, ctx: PluginContext) -> HoleheOutput:
        overall = max(float(inp.overall_timeout), 60.0)
        progress = getattr(ctx, "progress", None)
        status = getattr(progress, "_status", None) if progress is not None else None
        if status is not None and hasattr(status, "update"):
            with contextlib.suppress(Exception):
                status.update(
                    f"[cyan]holehe[/cyan]({inp.target})  "
                    f"[dim]up to {int(overall)}s…[/dim]"
                )

        try:
            # holehe v1.61 flags: --only-used (not --only-known), --no-color, --no-clear
            stdout, stderr = await run_cli_tool(
                "holehe",
                [
                    "--only-used",
                    "--no-color",
                    "--no-clear",
                    "-NP",  # skip password-recovery probes (faster, less noisy)
                    "-T",
                    "10",
                    inp.target,
                ],
                timeout=overall,
                auto_install=True,
                progress=progress,
            )
        except SubprocessError as exc:
            err = str(exc)
            if "timed out" in err.lower():
                msg = (
                    f"**{inp.target}** — holehe timed out after {int(overall)}s. "
                    f"Continue with other tools."
                )
            elif "not found" in err.lower() or "install" in err.lower():
                msg = (
                    f"**{inp.target}** — holehe binary/install problem: {exc}. "
                    f"Continue with other tools; do not ask the user to install."
                )
            else:
                msg = f"**{inp.target}** — holehe failed: {exc}. Continue with other tools."
            return HoleheOutput(
                source=self.name,
                summary_markdown=msg,
                entities=[Entity(type="email", value=inp.target)],
            )

        text = (stdout or b"").decode(errors="replace")
        if not text.strip() and stderr:
            text = stderr.decode(errors="replace")
        sites = sorted({m.group(1) for m in _FOUND.finditer(text)})
        preview = ", ".join(sites[:40])
        extra = f" (+{len(sites) - 40} more)" if len(sites) > 40 else ""
        return HoleheOutput(
            source=self.name,
            summary_markdown=(
                f"**{inp.target}** — holehe: {len(sites)} platforms: {preview}{extra}"
                if sites
                else f"**{inp.target}** — holehe: no registered platforms reported."
            ),
            sites=sites,
            entities=[Entity(type="email", value=inp.target)],
        )
