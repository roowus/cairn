"""username_check — reliable first-party social presence for a handle.

Unlike Sherlock (wide net, some third-party ``urlProbe`` mirrors), this plugin
hits the real platform URLs with browser-like HTTP, retries empty JS shells, and
returns found / not_found / unknown per site with evidence.

Use this for Instagram, GitHub, Reddit, YouTube, TikTok, X, Threads. Use
``sherlock`` afterward if you still want a broad sweep of 300+ niche sites.
"""

from __future__ import annotations

from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput
from cairn.execution.http_util import http_client
from cairn.execution.social_probe import DEFAULT_PLATFORMS, probe_many


class UsernameCheckInput(PluginInput):
    """``target`` is the username/handle (with or without leading @)."""

    platforms: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PLATFORMS),
        description=(
            "Platforms to check with first-party probes. "
            f"Default: {', '.join(DEFAULT_PLATFORMS)}."
        ),
    )


class UsernameCheckOutput(PluginOutput):
    username: str = ""
    found: list[str] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class UsernameCheckPlugin(BasePlugin[UsernameCheckInput, UsernameCheckOutput]):
    name = "username_check"
    category = "identity"
    requires_key = None
    detectability = "medium"  # first-party HTTP presence probes touch platforms
    input_model = UsernameCheckInput
    output_model = UsernameCheckOutput

    __doc__ = (
        "Check whether a username exists on major platforms via **first-party** "
        "URLs (Instagram, GitHub, Reddit, YouTube, TikTok, X, Threads). Browser-like "
        "HTTP + retries — not Sherlock's third-party mirrors. Prefer this over "
        "sherlock for those sites; use sherlock for the long-tail sweep."
    )

    async def run(self, inp: UsernameCheckInput, ctx: PluginContext) -> UsernameCheckOutput:
        username = inp.target.strip().lstrip("@")
        async with http_client(ctx, timeout=max(ctx.timeout, 30.0)) as http:
            results = await probe_many(http, username, inp.platforms or list(DEFAULT_PLATFORMS))

        found, missing, unknown, errors = [], [], [], []
        lines = [
            f"**@{username}** — first-party username check "
            f"({len(results)} platform(s); no third-party mirrors)"
        ]
        entities: list[Entity] = [Entity(type="username", value=username)]

        for r in results:
            mark = {
                "found": "✓ found",
                "not_found": "✗ not found",
                "unknown": "? unknown",
                "error": "! error",
            }[r.status]
            extra = ""
            if r.display_name:
                extra += f" — {r.display_name}"
            if r.bio:
                extra += f" — {r.bio[:120]}"
            if r.detail and r.status != "found":
                extra += f" ({r.detail})"
            lines.append(f"- **{r.platform}**: {mark}{extra}")
            if r.url and r.status == "found":
                lines.append(f"  - {r.url}")

            bucket = {
                "found": found,
                "not_found": missing,
                "unknown": unknown,
                "error": errors,
            }[r.status]
            bucket.append(r.platform)

            if r.status == "found":
                entities.append(
                    Entity(
                        type="url",
                        value=r.url,
                        attrs={
                            "platform": r.platform,
                            "username": username,
                            "display_name": r.display_name,
                        },
                    )
                )
                if r.display_name:
                    entities.append(
                        Entity(
                            type="person_name",
                            value=r.display_name,
                            attrs={"platform": r.platform, "username": username},
                        )
                    )

        lines.append(
            "\nNote: `unknown` means the site returned a shell/challenge without a "
            "clear yes/no — not the same as not found. Prefer this tool over "
            "`sherlock` for Instagram/X/etc.; use `sherlock` for niche sites only."
        )

        return UsernameCheckOutput(
            source=self.name,
            summary_markdown="\n".join(lines),
            username=username,
            found=found,
            not_found=missing,
            unknown=unknown,
            errors=errors,
            entities=entities,
        )
