"""run_command — arbitrary shell inside the workspace (agentic, full mode).

The full-agentic primitive. Runs ``bash -c <command>`` (array args via
:func:`cairn.execution.subprocess_util.run_shell` — never ``shell=True``) with
cwd = the workspace, so pipes/redirects/globs/``&&`` work. Any analyzer the
challenge needs (``file``, ``strings``, ``binwalk``, ``exiftool``, ``foremost``,
``tshark``, ``nmap``, ``dig``, ``curl``, ``pdftotext``, ``identify``, ``steghide``,
``zsteg``) is invoked through here. Missing tools: call ``install_cli`` first.

The subprocess env is scrubbed (:func:`cairn.execution.workspace.scrub_env`) so
no ``CAIRN_*`` / ``*_API_KEY`` / ``*_TOKEN`` leaks to the child. Containment is
policy-level (cwd is a workspace root → auto-allowed), not OS-enforced; the
result is wrapped as untrusted data by the tool closure.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field

from cairn.execution.base import BasePlugin, PluginContext, PluginInput, PluginOutput
from cairn.execution.cli_tools import _EXTRA_PATH_DIRS
from cairn.execution.subprocess_util import SubprocessError, run_shell
from cairn.execution.tool_progress import progress_for
from cairn.execution.workspace import scrub_env

_MAX_OUT = 8000  # cap stdout surfaced to the model
_MAX_ERR_LINES = 3  # stderr tail lines kept


class RunCommandInput(PluginInput):
    target: str = Field(
        ...,
        description="Shell command (pipes/redirects/globs/&& OK). cwd is the workspace.",
    )
    timeout: float = 120.0


class RunCommandOutput(PluginOutput):
    command: str = ""
    exit_code: int = 0
    stdout_len: int = 0


class RunCommandPlugin(BasePlugin[RunCommandInput, RunCommandOutput]):
    name = "run_command"
    category = "agentic"
    requires_key = None
    input_model = RunCommandInput
    output_model = RunCommandOutput

    __doc__ = (
        "Run an arbitrary shell command (target = command string) with cwd = the "
        "workspace. Pipes, redirects, globs, && all work. Use any analyzer: file, "
        "strings, binwalk, exiftool, foremost, tshark, nmap, dig, curl, pdftotext, "
        "identify, steghide, zsteg. Missing tools: call install_cli first. A "
        "non-zero exit is reported as data, not an error. Output is capped."
    )

    async def run(self, inp: RunCommandInput, ctx: PluginContext) -> RunCommandOutput:
        cmd = (inp.target or "").strip()
        if not cmd:
            return RunCommandOutput(
                source=self.name,
                command=cmd,
                summary_markdown="**run_command error**: empty command.",
            )
        ws = getattr(ctx, "workspace", None)
        cwd = Path(ws) if ws else Path.cwd()
        env = scrub_env(os.environ)
        prefix = os.pathsep.join(str(p) for p in _EXTRA_PATH_DIRS if Path(p).is_dir())
        if prefix:
            env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}"
        on_line = progress_for(ctx)
        try:
            result = await run_shell(
                cmd, timeout=max(inp.timeout, 1.0), env=env, cwd=cwd, on_line=on_line
            )
        except SubprocessError as exc:
            return RunCommandOutput(
                source=self.name, command=cmd, summary_markdown=f"**run_command failed**: {exc}"
            )
        out_text = result.stdout.decode(errors="replace")
        err_text = result.stderr.decode(errors="replace")
        return RunCommandOutput(
            source=self.name,
            command=cmd,
            exit_code=result.returncode,
            stdout_len=len(result.stdout),
            summary_markdown=_summary(cmd, out_text, err_text, result.returncode),
        )


def _summary(cmd: str, out: str, err: str, rc: int) -> str:
    shown = out[:_MAX_OUT]
    more = " …(truncated)" if len(out) > _MAX_OUT else ""
    lines = [f"`$ {cmd}` — **exit {rc}**", "", "```", f"{shown}{more}", "```"]
    err_tail = [ln for ln in err.strip().splitlines()[-_MAX_ERR_LINES:] if ln.strip()]
    if err_tail:
        lines += ["", "_stderr (tail):_", *(f"    {ln}" for ln in err_tail)]
    return "\n".join(lines)
