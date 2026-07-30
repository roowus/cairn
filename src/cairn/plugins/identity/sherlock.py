"""sherlock — username → long-tail social profiles via the `sherlock` CLI.

Wide-net sweep across 300+ sites. For major platforms (Instagram, GitHub, …)
Sherlock sometimes uses third-party ``urlProbe`` mirrors that false-negative;
after the CLI run we **cross-check** those platforms with Cairn's first-party
probes (``execution.social_probe``) and merge the results.

Prefer ``username_check`` when you only care about major platforms (faster +
more accurate). Use ``sherlock`` for breadth.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput
from cairn.execution.cli_tools import run_cli_tool
from cairn.execution.http_util import http_client
from cairn.execution.social_probe import DEFAULT_PLATFORMS, probe_many
from cairn.execution.subprocess_util import SubprocessError
from cairn.execution.tool_progress import progress_for

_URL = re.compile(r"https?://[^\s,\]]+")

_DEFAULT_OVERALL_TIMEOUT = 240.0
_MIN_OVERALL_TIMEOUT = 90.0

# Host fragments → platform key for suppressing bad Sherlock URLs when first-party says otherwise
_HOST_PLATFORM = (
    ("instagram.com", "instagram"),
    ("threads.net", "threads"),
    ("github.com", "github"),
    ("reddit.com", "reddit"),
    ("youtube.com", "youtube"),
    ("tiktok.com", "tiktok"),
    ("twitter.com", "x"),
    ("x.com", "x"),
    ("imginn.com", "instagram"),  # third-party mirror — never trust alone
    ("nitter.", "x"),
)


class SherlockInput(PluginInput):
    """`target` is a username."""

    site_timeout: float = Field(
        default=8.0,
        ge=1.0,
        le=60.0,
        description="Per-site HTTP timeout passed to sherlock --timeout (seconds).",
    )
    overall_timeout: float = Field(
        default=_DEFAULT_OVERALL_TIMEOUT,
        ge=30.0,
        le=900.0,
        description="Wall-clock budget for the entire sherlock process (seconds).",
    )
    crosscheck_major: bool = Field(
        default=True,
        description=(
            "After Sherlock, re-check major platforms with first-party probes "
            "(fixes Instagram/imginn false negatives, etc.)."
        ),
    )


class SherlockOutput(PluginOutput):
    profiles: list[str] = Field(default_factory=list)
    first_party_found: list[str] = Field(default_factory=list)


class SherlockPlugin(BasePlugin[SherlockInput, SherlockOutput]):
    name = "sherlock"
    category = "identity"
    requires_key = None
    detectability = "medium"  # probes 300+ sites for the handle
    input_model = SherlockInput
    output_model = SherlockOutput

    __doc__ = (
        "Wide username sweep (300+ sites) via sherlock, then first-party "
        "cross-check of Instagram/GitHub/Reddit/YouTube/TikTok/X/Threads. "
        "Takes 1-3 minutes. For major sites only, prefer username_check."
    )

    async def run(self, inp: SherlockInput, ctx: PluginContext) -> SherlockOutput:
        overall = max(float(inp.overall_timeout), _MIN_OVERALL_TIMEOUT)
        progress = getattr(ctx, "progress", None)
        on_line = progress_for(ctx)

        profiles: list[str] = []
        cli_error: str | None = None
        try:
            stdout, stderr = await run_cli_tool(
                "sherlock",
                [
                    inp.target,
                    "--timeout",
                    str(inp.site_timeout),
                    "--print-found",
                    "--no-color",
                    "--no-txt",
                ],
                timeout=overall,
                auto_install=True,
                progress=progress,
                on_line=on_line,
            )
            text = (stdout or b"").decode(errors="replace")
            if not text.strip() and stderr:
                text = stderr.decode(errors="replace")
            profiles = sorted({m.group(0).rstrip(").,;") for m in _URL.finditer(text)})
            profiles = [u for u in profiles if u.startswith("http")]
        except SubprocessError as exc:
            cli_error = str(exc)

        # Drop known-bad third-party mirror URLs from Sherlock output.
        profiles = [u for u in profiles if not _is_mirror_url(u)]

        fp_lines: list[str] = []
        fp_found: list[str] = []
        fp_entities: list[Entity] = []
        if inp.crosscheck_major:
            async with http_client(ctx, timeout=max(ctx.timeout, 30.0)) as http:
                results = await probe_many(http, inp.target, DEFAULT_PLATFORMS)

            # If first-party says not_found, drop Sherlock URLs for that platform.
            deny_platforms = {r.platform for r in results if r.status == "not_found"}
            profiles = [u for u in profiles if _url_platform(u) not in deny_platforms]

            for r in results:
                if r.status == "found":
                    fp_found.append(r.platform)
                    if r.url and r.url not in profiles:
                        profiles.append(r.url)
                    label = r.display_name or ""
                    fp_lines.append(
                        f"- ✓ **{r.platform}** first-party: {r.url}"
                        + (f" ({label})" if label else "")
                    )
                    fp_entities.append(
                        Entity(
                            type="url",
                            value=r.url,
                            attrs={"platform": r.platform, "via": "first_party_crosscheck"},
                        )
                    )
                elif r.status == "not_found":
                    fp_lines.append(f"- ✗ **{r.platform}** first-party: not found")
                elif r.status == "unknown":
                    fp_lines.append(f"- ? **{r.platform}** first-party: unknown ({r.detail})")
                else:
                    fp_lines.append(f"- ! **{r.platform}** first-party: error ({r.detail})")

        entities = [Entity(type="username", value=inp.target), *fp_entities]
        for url in profiles:
            entities.append(Entity(type="url", value=url, attrs={"via": "sherlock"}))

        parts: list[str] = []
        if cli_error:
            if "timed out" in cli_error.lower():
                parts.append(
                    f"**{inp.target}** — sherlock CLI timed out after {int(overall)}s; "
                    f"showing first-party cross-check only."
                )
            else:
                parts.append(
                    f"**{inp.target}** — sherlock CLI problem: {cli_error}; "
                    f"showing first-party cross-check only."
                )
        elif profiles:
            preview = "\n  - ".join(profiles[:40])
            extra = f"\n  ...(+{len(profiles) - 40} more)" if len(profiles) > 40 else ""
            parts.append(
                f"**{inp.target}** — sherlock + first-party: {len(profiles)} profile URL(s):\n"
                f"  - {preview}{extra}"
            )
        else:
            parts.append(
                f"**{inp.target}** — no profile URLs from sherlock or first-party checks."
            )

        if fp_lines:
            parts.append("\n**First-party cross-check** (authoritative for major sites):")
            parts.extend(fp_lines)
            parts.append(
                "\nTip: for major platforms only, call `username_check` (faster, same probes)."
            )

        return SherlockOutput(
            source=self.name,
            summary_markdown="\n".join(parts),
            profiles=profiles,
            first_party_found=fp_found,
            entities=entities,
        )


def _is_mirror_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(
        bad in host
        for bad in ("imginn.com", "nitter.", "test1.venmo.com")
    )


def _url_platform(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for frag, plat in _HOST_PLATFORM:
        if frag in host:
            return plat
    return None
