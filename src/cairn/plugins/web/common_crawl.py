"""Common Crawl index — historical page references (free, no key)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput
from cairn.execution.http_util import http_client


def _index_url_pattern(target: str) -> str:
    """Normalize bare domains to a CDX-friendly path pattern.

    Common Crawl's CDX ``url`` param treats a bare host as an exact key; for
    domain recon we want path matches under that host (``example.com/*``). Full
    URLs, paths, and caller-supplied wildcards are left alone.
    """
    t = target.strip()
    if not t or "://" in t or "/" in t or "*" in t:
        return t
    return f"{t}/*"


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
        async with http_client(ctx) as http:
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
            query_url = _index_url_pattern(inp.target)
            r = await http.get(
                f"https://index.commoncrawl.org/{latest}-index",
                params={"url": query_url, "output": "json", "limit": str(inp.limit)},
            )
            if r.status_code != 200:
                return CommonCrawlOutput(
                    source=self.name,
                    summary_markdown=(
                        f"**{inp.target}** — Common Crawl ({latest}): "
                        f"index unavailable (HTTP {r.status_code})."
                    ),
                    entities=[Entity(type="url", value=inp.target)],
                )
            if not r.text.strip():
                return CommonCrawlOutput(
                    source=self.name,
                    summary_markdown=f"**{inp.target}** — Common Crawl ({latest}): 0 matches.",
                    entities=[Entity(type="url", value=inp.target)],
                )
            # The response is newline-delimited JSON.
            matches: list[dict[str, Any]] = []
            for line in r.text.splitlines():
                line = line.strip()
                if line:
                    try:
                        matches.append(json.loads(line))
                    except ValueError:
                        continue
            if not matches:
                return CommonCrawlOutput(
                    source=self.name,
                    summary_markdown=f"**{inp.target}** — Common Crawl ({latest}): 0 matches.",
                    entities=[Entity(type="url", value=inp.target)],
                )
            preview = "\n".join(f"  - {m.get('timestamp')} {m.get('url')}" for m in matches[:8])
            return CommonCrawlOutput(
                source=self.name,
                summary_markdown=(
                    f"**{inp.target}** — Common Crawl ({latest}): "
                    f"{len(matches)} matches:\n{preview}"
                ),
                matches=matches[: inp.limit],
                entities=[Entity(type="url", value=inp.target)],
            )
