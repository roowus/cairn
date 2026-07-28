"""urlscan — recent urlscan.io scans for a domain or IP (free, no key).

Endpoint: ``https://urlscan.io/api/v1/search/?q=domain:example.com`` — public,
no API key required (community rate limit ~1000/day). Returns the most recent
public scans urlscan has observed for the target: page URL, IP, server, page
title, and ASN — a strong pivot for domains/IPs the target has been hosted on.
A ``CAIRN_URLSCAN_KEY`` is used opportunistically if present for a higher limit.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)


def _looks_like_ip(target: str) -> bool:
    parts = target.strip().split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def _query(target: str) -> str:
    t = target.strip()
    if "://" in t:
        t = t.split("://", 1)[1]
    t = t.split("/")[0]
    return f"ip:{t}" if _looks_like_ip(t) else f"domain:{t}"


class UrlscanInput(PluginInput):
    """``target`` is a domain or IP address."""

    limit: int = 10


class UrlscanHit(BaseModel):
    page_url: str | None
    page_domain: str | None
    page_ip: str | None
    page_title: str | None
    server: str | None
    task_url: str | None


class UrlscanOutput(PluginOutput):
    total: int = 0
    hits: list[UrlscanHit] = Field(default_factory=list)


class UrlscanPlugin(BasePlugin[UrlscanInput, UrlscanOutput]):
    name = "urlscan"
    category = "web"
    requires_key = None
    input_model = UrlscanInput
    output_model = UrlscanOutput
    cost = CostSpec(unit="searches/day", note="community ~1000/day → higher with CAIRN_URLSCAN_KEY")

    __doc__ = (
        "Search urlscan.io (free) for recent public scans of a domain or IP (target): observed "
        "page URLs, IPs, servers, and titles. Good hosting-history pivot."
    )

    async def run(self, inp: UrlscanInput, ctx: PluginContext) -> UrlscanOutput:
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        headers = {"User-Agent": ctx.user_agent}
        token = ctx.key("urlscan")
        if token:
            headers["API-Key"] = token
        r = await http.get(
            "https://urlscan.io/api/v1/search/",
            params={"q": _query(inp.target), "size": min(max(inp.limit, 1), 100)},
            headers=headers,
        )
        if r.status_code == 404:
            return UrlscanOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — urlscan: no scans found.",
                entities=[Entity(type="domain", value=inp.target)],
            )
        if r.status_code in (429, 502, 503, 504):
            # urlscan's free community endpoint intermittently rate-limits / 503s.
            return UrlscanOutput(
                source=self.name,
                summary_markdown=(
                    f"**{inp.target}** — urlscan temporarily unavailable "
                    f"(HTTP {r.status_code}); retry later."
                ),
                entities=[Entity(type="domain", value=inp.target)],
            )
        r.raise_for_status()
        data = r.json()
        hits: list[UrlscanHit] = []
        for res in data.get("results", []) or []:
            page = res.get("page", {}) or {}
            task = res.get("task", {}) or {}
            hits.append(
                UrlscanHit(
                    page_url=page.get("url"),
                    page_domain=page.get("domain"),
                    page_ip=page.get("ip"),
                    page_title=page.get("title"),
                    server=page.get("server"),
                    task_url=task.get("url"),
                )
            )

        out = UrlscanOutput(source=self.name, total=data.get("total", len(hits)), hits=hits)
        out.summary_markdown = _summary(out, inp.target)
        out.entities = _entities(out, inp.target)
        return out


def _summary(out: UrlscanOutput, target: str) -> str:
    if not out.hits:
        return f"**{target}** — urlscan: no public scans found."
    lines = [f"**{target}** — urlscan: {out.total} scan(s); showing {len(out.hits)}:"]
    for h in out.hits:
        title = f"“{h.page_title}”" if h.page_title else "(no title)"
        lines.append(
            f"- {h.page_url or h.page_domain} — {title} "
            f"[ip={h.page_ip or '?'} server={h.server or '?'}]"
        )
    return "\n".join(lines)


def _entities(out: UrlscanOutput, target: str) -> list[Entity]:
    ents = [Entity(type="ip" if _looks_like_ip(target) else "domain", value=target)]
    seen_ips: set[str] = set()
    seen_domains: set[str] = set()
    for h in out.hits:
        if h.page_ip and h.page_ip not in seen_ips:
            seen_ips.add(h.page_ip)
            ents.append(Entity(type="ip", value=h.page_ip))
        if h.page_domain and h.page_domain not in seen_domains:
            seen_domains.add(h.page_domain)
            ents.append(Entity(type="domain", value=h.page_domain))
    return ents
