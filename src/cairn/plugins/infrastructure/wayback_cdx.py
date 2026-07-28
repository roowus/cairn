"""Wayback Machine CDX Server — historical URL snapshots (free, no key)."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field

from cairn.core.security import redact_url_userinfo
from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput


class WaybackCdxInput(PluginInput):
    """`target` is a domain or URL pattern (e.g. example.com/*)."""

    limit: int = 25


class WaybackCdxOutput(PluginOutput):
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    earliest: str | None = None
    latest: str | None = None


class WaybackCdxPlugin(BasePlugin[WaybackCdxInput, WaybackCdxOutput]):
    name = "wayback_cdx"
    category = "infrastructure"
    requires_key = None
    input_model = WaybackCdxInput
    output_model = WaybackCdxOutput

    __doc__ = (
        "List historical snapshots of a domain/URL (target) from the Wayback Machine CDX index. "
        "Free."
    )

    async def run(self, inp: WaybackCdxInput, ctx: PluginContext) -> WaybackCdxOutput:
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        url = (
            inp.target if "*" in inp.target or inp.target.startswith("http") else f"{inp.target}/*"
        )
        r = await http.get(
            "http://web.archive.org/cdx/search/cdx",
            params={
                "url": url,
                "output": "json",
                "fl": "timestamp,original,statuscode,mimetype",
                "collapse": "digest",
                "limit": str(inp.limit),
                "filter": "statuscode:200",
            },
        )
        r.raise_for_status()
        data = r.json() if r.text.strip() else []
        if not data or len(data) < 2:
            return WaybackCdxOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — Wayback CDX: no snapshots found.",
                entities=[Entity(type="url", value=inp.target)],
            )
        header, rows = data[0], data[1:]
        snaps = [dict(zip(header, row, strict=False)) for row in rows]
        # Drop historical basic-auth userinfo before it reaches summaries / model.
        for s in snaps:
            original = s.get("original")
            if isinstance(original, str):
                s["original"] = redact_url_userinfo(original)
        timestamps = [s["timestamp"] for s in snaps if s.get("timestamp")]
        preview = "\n".join(f"  - {s.get('timestamp')} {s.get('original')}" for s in snaps[:8])
        extra = f"\n  ...(+{len(snaps) - 8} more)" if len(snaps) > 8 else ""
        summary = f"**{inp.target}** — {len(snaps)} Wayback snapshots:\n{preview}{extra}"
        return WaybackCdxOutput(
            source=self.name,
            summary_markdown=summary,
            snapshots=snaps,
            earliest=min(timestamps) if timestamps else None,
            latest=max(timestamps) if timestamps else None,
            entities=[Entity(type="url", value=inp.target)],
        )
