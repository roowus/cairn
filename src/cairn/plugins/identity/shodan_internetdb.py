"""Shodan InternetDB — free, unauthenticated IP enrichment.

Endpoint: https://internetdb.shodan.io/{ip} — no API key required. Returns
hostnames, open ports, known CVEs, and tags Shodan has observed.
"""

from __future__ import annotations

import httpx
from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput


class ShodanInternetDBInput(PluginInput):
    """`target` is an IPv4/IPv6 address."""


class ShodanInternetDBOutput(PluginOutput):
    hostnames: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)
    vulns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ShodanInternetDBPlugin(BasePlugin[ShodanInternetDBInput, ShodanInternetDBOutput]):
    name = "shodan_internetdb"
    category = "identity"
    requires_key = None
    input_model = ShodanInternetDBInput
    output_model = ShodanInternetDBOutput

    __doc__ = (
        "Enrich an IP address (target) via Shodan's free InternetDB: hostnames, open ports, "
        "CVEs, tags."
    )

    async def run(self, inp: ShodanInternetDBInput, ctx: PluginContext) -> ShodanInternetDBOutput:
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        r = await http.get(f"https://internetdb.shodan.io/{inp.target}")
        if r.status_code == 404:
            return ShodanInternetDBOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — Shodan InternetDB: no data (not indexed).",
                entities=[Entity(type="ip", value=inp.target)],
            )
        r.raise_for_status()
        d = r.json() if r.text else {}
        hostnames = d.get("hostnames") or []
        ports = d.get("ports") or []
        vulns = d.get("vulns") or []
        tags = d.get("tags") or []
        summary = (
            f"**{inp.target}** — Shodan InternetDB\n"
            f"- Hostnames: {', '.join(hostnames) or 'none'}\n"
            f"- Open ports: {', '.join(map(str, ports)) or 'none'}\n"
            f"- Known CVEs: {', '.join(vulns) or 'none'}\n"
            f"- Tags: {', '.join(tags) or 'none'}\n"
        )
        return ShodanInternetDBOutput(
            source=self.name,
            summary_markdown=summary,
            hostnames=hostnames,
            ports=ports,
            vulns=vulns,
            tags=tags,
            entities=[
                Entity(type="ip", value=inp.target, attrs={"ports": ports, "cve_count": len(vulns)})
            ],
        )
