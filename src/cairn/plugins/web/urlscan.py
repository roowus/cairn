"""urlscan — recent urlscan.io scans for a domain or IP (free, no key).

Endpoint: ``https://urlscan.io/api/v1/search/?q=domain:example.com`` — public,
no API key required (community rate limit ~1000/day). Returns the most recent
public scans urlscan has observed for the target: page URL, IP, server, page
title, and ASN — a strong pivot for domains/IPs the target has been hosted on.
A ``CAIRN_URLSCAN_KEY`` is used opportunistically if present for a higher limit.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)
from cairn.execution.http_util import http_client


def _looks_like_ip(target: str) -> bool:
    parts = target.strip().split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def _normalize_host(target: str) -> str:
    t = target.strip()
    if "://" in t:
        t = t.split("://", 1)[1]
    t = t.split("/")[0]
    # drop trailing dots / ports for domain targets (IPs never have ports here)
    if not _looks_like_ip(t) and ":" in t:
        t = t.rsplit(":", 1)[0]
    return t.rstrip(".").lower()


def _query(target: str) -> str:
    t = _normalize_host(target)
    return f"ip:{t}" if _looks_like_ip(t) else f"domain:{t}"


def _on_target_domain(domain: str | None, target: str) -> bool:
    """True when ``domain`` is the target or a subdomain of it."""
    if not domain:
        return False
    d = domain.lower().rstrip(".")
    t = _normalize_host(target)
    return d == t or d.endswith("." + t)


def _on_target_hit(page_domain: str | None, page_ip: str | None, target: str) -> bool:
    t = _normalize_host(target)
    if _looks_like_ip(t):
        return (page_ip or "").strip() == t
    return _on_target_domain(page_domain, t)


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
        async with http_client(ctx) as http:
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
            raw_total = int(data.get("total") or 0)
            hits: list[UrlscanHit] = []
            seen_urls: set[str] = set()
            for res in data.get("results", []) or []:
                page = res.get("page", {}) or {}
                task = res.get("task", {}) or {}
                page_domain = page.get("domain")
                page_ip = page.get("ip")
                if not _on_target_hit(page_domain, page_ip, inp.target):
                    continue
                page_url = page.get("url")
                dedupe_key = (page_url or "").rstrip("/") or f"{page_domain}|{page_ip}"
                if dedupe_key in seen_urls:
                    continue
                seen_urls.add(dedupe_key)
                hits.append(
                    UrlscanHit(
                        page_url=page_url,
                        page_domain=page_domain,
                        page_ip=page_ip,
                        page_title=page.get("title"),
                        server=page.get("server"),
                        task_url=task.get("url"),
                    )
                )
                if len(hits) >= inp.limit:
                    break

            out = UrlscanOutput(source=self.name, total=raw_total, hits=hits)
            out.summary_markdown = _summary(out, inp.target)
            out.entities = _entities(out, inp.target)
            return out


def _summary(out: UrlscanOutput, target: str) -> str:
    if not out.hits:
        if out.total:
            return (
                f"**{target}** — urlscan: {out.total} raw hit(s) but none on-target "
                f"after domain/IP filter."
            )
        return f"**{target}** — urlscan: no public scans found."
    # urlscan's ``total`` is the unfiltered index count and is often inflated /
    # off-domain noise for ``domain:`` queries — only claim on-target hits.
    lines = [
        f"**{target}** — urlscan: {len(out.hits)} on-target scan(s)"
        + (f" (of {out.total} raw)" if out.total and out.total != len(out.hits) else "")
        + ":"
    ]
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
