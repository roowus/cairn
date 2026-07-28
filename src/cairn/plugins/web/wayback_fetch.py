"""Wayback Machine archive fetch — retrieve an archived page (free, no key)."""

from __future__ import annotations

import httpx

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput


class WaybackFetchInput(PluginInput):
    """`target` is a full URL."""

    timestamp: str | None = None  # YYYYMMDDHHMMSS; newest if omitted


class WaybackFetchOutput(PluginOutput):
    archived_url: str | None = None
    char_count: int = 0
    text_snippet: str = ""


class WaybackFetchPlugin(BasePlugin[WaybackFetchInput, WaybackFetchOutput]):
    name = "wayback_fetch"
    category = "web"
    requires_key = None
    input_model = WaybackFetchInput
    output_model = WaybackFetchOutput

    __doc__ = (
        "Fetch an archived copy of a URL (target) from the Wayback Machine, returning cleaned "
        "text. Free."
    )

    async def run(self, inp: WaybackFetchInput, ctx: PluginContext) -> WaybackFetchOutput:
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        url = inp.target if inp.target.startswith("http") else f"https://{inp.target}"
        avail = await http.get(
            "https://archive.org/wayback/available",
            params={"url": url, "timestamp": inp.timestamp or ""},
        )
        avail.raise_for_status()
        snap = (avail.json().get("archived_snapshots") or {}).get("closest") or {}
        if not snap.get("available"):
            return WaybackFetchOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — Wayback: no archived copy found.",
                entities=[Entity(type="url", value=url)],
            )
        archived_url = snap["url"]
        page = await http.get(archived_url)
        page.raise_for_status()
        text = _strip_html(page.text)
        snippet = text.strip()[:2000]
        return WaybackFetchOutput(
            source=self.name,
            summary_markdown=(
                f"**{inp.target}** — Wayback archived ({snap.get('timestamp')}):\n"
                f"{archived_url}\n\n{snippet[:1200]}{'…' if len(snippet) > 1200 else ''}"
            ),
            archived_url=archived_url,
            char_count=len(text),
            text_snippet=snippet,
            entities=[Entity(type="url", value=url, attrs={"archived": archived_url})],
        )


def _strip_html(html: str) -> str:
    import html as html_mod
    import re

    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html_mod.unescape(re.sub(r"\s+", " ", text)).strip()
