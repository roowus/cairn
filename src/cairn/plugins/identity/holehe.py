"""holehe — email → registered platforms, via the `holehe` CLI (free, no key).

Wraps the external `holehe` binary through the safe subprocess runner. If the
binary is missing, Cairn auto-installs the allowlisted ``holehe`` package via
``uv tool install`` (see ``execution.cli_tools``).

Holehe probes many sites and often needs well over the HTTP ``ctx.timeout``
(30s), so the process budget is independent of that default.
"""

from __future__ import annotations

import re

from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput
from cairn.execution.cli_tools import run_cli_tool
from cairn.execution.subprocess_util import SubprocessError
from cairn.execution.tool_progress import progress_for

# holehe prints "[+] domain.tld …" per registered address (--only-used), but it
# also ends every run with a legend line whose first token is "[+] Email used"
# (followed by "[-] Email not used", "[x] Rate limit", "[!] Error"). That
# "Email" is NOT a platform, so require a domain-shaped token — a "." followed
# by a TLD — rather than matching every "[+] <word>" line.
_FOUND = re.compile(r"^\[\+\]\s+(\S+\.[A-Za-z]{2,})", re.MULTILINE)

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
    detectability = "medium"  # probes signup/recovery endpoints of services
    input_model = HoleheInput
    output_model = HoleheOutput

    __doc__ = (
        "Check which platforms an email (target) is registered on, via holehe. "
        "Can take 1-2 minutes. Auto-installs the binary if missing."
    )

    async def run(self, inp: HoleheInput, ctx: PluginContext) -> HoleheOutput:
        overall = max(float(inp.overall_timeout), 60.0)
        progress = getattr(ctx, "progress", None)
        on_line = progress_for(ctx)

        try:
            # holehe v1.61 flags: --only-used --no-color --no-clear.
            # NOTE: do NOT pass -NP/--no-password-recovery — those probes ARE
            # holehe's core detection. Skipping them makes holehe fast-fail every
            # site (~0.4s) and report "no platforms" — a false negative. Confirmed
            # empirically: without -NP, holehe finds real registrations in ~10s.
            stdout, stderr = await run_cli_tool(
                "holehe",
                ["--only-used", "--no-color", "--no-clear", inp.target],
                timeout=overall,
                auto_install=True,
                progress=progress,
                on_line=on_line,
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
        if sites:
            base = f"**{inp.target}** — holehe: {len(sites)} platform(s): {preview}{extra}"
        else:
            base = f"**{inp.target}** — holehe: no registered platforms reported."
        # holehe is best-effort: rate-limiting/anti-bot produce false negatives (a
        # non-hit does NOT mean no account), and it only covers its bundled site
        # list. Say so + steer toward complementary tools for breadth.
        return HoleheOutput(
            source=self.name,
            summary_markdown=(
                base
                + "\n\n_Caveat: holehe is best-effort — rate-limiting/anti-bot cause false "
                "negatives, and it only probes its bundled ~120 sites. For breadth, pivot to "
                "username_check/sherlock on a known handle (different sites), "
                "or hibp for breaches._"
            ),
            sites=sites,
            entities=[Entity(type="email", value=inp.target)],
        )
