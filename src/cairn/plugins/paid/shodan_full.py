"""Shodan full API (key-gated) — deep host enrichment.

Activates automatically once ``CAIRN_SHODAN_KEY`` is set. Uses the REST API
directly (no SDK dependency).
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)


class ShodanFullInput(PluginInput):
    """`target` is an IP address."""


class ShodanFullOutput(PluginOutput):
    ports: list[int] = Field(default_factory=list)
    org: str | None = None
    hostnames: list[str] = Field(default_factory=list)
    vulns: list[str] = Field(default_factory=list)


class ShodanFullPlugin(BasePlugin[ShodanFullInput, ShodanFullOutput]):
    name = "shodan_full"
    category = "identity"
    requires_key = "shodan"
    input_model = ShodanFullInput
    output_model = ShodanFullOutput
    # /shodan/host/{ip} costs 1 query credit (waived if Shodan already scanned it)
    cost = CostSpec(unit="credits", per_call=1.0, paid=True, note="1 query credit/lookup")

    __doc__ = (
        "Deep Shodan host enrichment for an IP (target): ports, org, hostnames, vulns. Requires "
        "CAIRN_SHODAN_KEY."
    )

    async def run(self, inp: ShodanFullInput, ctx: PluginContext) -> ShodanFullOutput:
        key = ctx.key("shodan") or ""
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        r = await http.get(f"https://api.shodan.io/shodan/host/{inp.target}", params={"key": key})
        if r.status_code == 404:
            return ShodanFullOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — Shodan: no data.",
                entities=[Entity(type="ip", value=inp.target)],
            )
        r.raise_for_status()
        d: dict[str, Any] = r.json()
        ports = sorted(set(d.get("ports") or []))
        hostnames = sorted(set(d.get("hostnames") or []))
        vulns = sorted(set(d.get("vulns") or []))
        org = d.get("org") or d.get("isp")
        summary = (
            f"**{inp.target}** — Shodan (full)\n"
            f"- Org/ISP: {org or 'unknown'}\n"
            f"- Ports: {', '.join(map(str, ports)) or 'none'}\n"
            f"- Hostnames: {', '.join(hostnames) or 'none'}\n"
            f"- CVEs: {', '.join(vulns) or 'none'}\n"
        )
        return ShodanFullOutput(
            source=self.name,
            summary_markdown=summary,
            ports=ports,
            org=org,
            hostnames=hostnames,
            vulns=vulns,
            entities=[Entity(type="ip", value=inp.target)],
        )
