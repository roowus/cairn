"""Common Crawl index — historical page references (free, no key)."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput


class CommonCrawlInput(PluginInput):
    """`target` is a domain or URL."""

    limit: int = 15


class CommonCrawlOutput(PluginOutput):
    matches: list[dict[str, Any]] = Field(default_factory=list)


class CommonCrawlPlugin(BasePlugin[CommonCrawlInput, CommonCrawlOutput]):
    name = "common_crawl"
    category = "web"
    requires_key = None
    input_model = CommonCrawlInput
    output_model = CommonCrawlOutput

    __doc__ = (
        "Search the Common Crawl index for historical references to a domain/URL (target). Free."
    )

    async def run(self, inp: CommonCrawlInput, ctx: PluginContext) -> CommonCrawlOutput:
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        # Discover the latest crawl index.
        idx = await http.get("https://index.commoncrawl.org/collinfo.json")
        idx.raise_for_status()
        indexes = idx.json()
        if not indexes:
            return CommonCrawlOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — Common Crawl: no index available.",
                entities=[Entity(type="url", value=inp.target)],
            )
        latest = indexes[0]["id"]
        r = await http.get(
            f"https://index.commoncrawl.org/{latest}-index",
            params={"url": inp.target, "output": "json", "limit": str(inp.limit)},
        )
        if r.status_code != 200 or not r.text.strip():
            return CommonCrawlOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — Common Crawl ({latest}): no matches.",
                entities=[Entity(type="url", value=inp.target)],
            )
        # The response is newline-delimited JSON.
        matches: list[dict[str, Any]] = Field(default_factory=list)
        for line in r.text.splitlines():
            line = line.strip()
            if line:
                try:
                    matches.append(__import__("json").loads(line))
                except ValueError:
                    continue
        preview = "\n".join(f"  - {m.get('timestamp')} {m.get('url')}" for m in matches[:8])
        return CommonCrawlOutput(
            source=self.name,
            summary_markdown=(
                f"**{inp.target}** — Common Crawl ({latest}): {len(matches)} matches:\n{preview}"
            ),
            matches=matches[: inp.limit],
            entities=[Entity(type="url", value=inp.target)],
        )
