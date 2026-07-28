"""VirusTotal v3 (key-gated) — IP/domain reputation."""

from __future__ import annotations

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


class VirusTotalInput(PluginInput):
    """`target` is an IP or domain."""


class VirusTotalOutput(PluginOutput):
    malicious: int = 0
    suspicious: int = 0
    harmless: int = 0
    reputation: int = 0
    categories: list[str] = Field(default_factory=list)


class VirusTotalPlugin(BasePlugin[VirusTotalInput, VirusTotalOutput]):
    name = "virustotal"
    category = "identity"
    requires_key = "virustotal"
    input_model = VirusTotalInput
    output_model = VirusTotalOutput
    cost = CostSpec(unit="calls", note="free public tier ~4/min → 500/min with a premium key")

    __doc__ = "VirusTotal reputation for an IP/domain (target). Requires CAIRN_VIRUSTOTAL_KEY."

    async def run(self, inp: VirusTotalInput, ctx: PluginContext) -> VirusTotalOutput:
        key = ctx.key("virustotal") or ""
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        resource = inp.target
        endpoint = "ip_addresses" if _is_ip(resource) else "domains"
        r = await http.get(
            f"https://www.virustotal.com/api/v3/{endpoint}/{resource}",
            headers={"x-apikey": key},
        )
        r.raise_for_status()
        stats = (r.json().get("data") or {}).get("attributes", {}).get("last_analysis_stats", {})
        rep = (r.json().get("data") or {}).get("attributes", {}).get("reputation", 0)
        summary = (
            f"**{inp.target}** — VirusTotal\n"
            f"- Malicious: {stats.get('malicious', 0)}  Suspicious: {stats.get('suspicious', 0)}  "
            f"Harmless: {stats.get('harmless', 0)}\n"
            f"- Reputation: {rep}\n"
        )
        return VirusTotalOutput(
            source=self.name,
            summary_markdown=summary,
            malicious=stats.get("malicious", 0),
            suspicious=stats.get("suspicious", 0),
            harmless=stats.get("harmless", 0),
            reputation=rep,
            entities=[Entity(type="ip" if _is_ip(resource) else "domain", value=resource)],
        )


def _is_ip(s: str) -> bool:
    return s.count(".") == 3 and all(p.isdigit() for p in s.split("."))
