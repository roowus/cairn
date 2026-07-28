"""AbuseIPDB (key-gated) — IP abuse reputation."""

from __future__ import annotations

from typing import Any

import httpx

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)


class AbuseIpdbInput(PluginInput):
    """`target` is an IP address."""

    max_age_days: int = 90


class AbuseIpdbOutput(PluginOutput):
    score: int = 0
    country: str | None = None
    isp: str | None = None
    total_reports: int = 0


class AbuseIpdbPlugin(BasePlugin[AbuseIpdbInput, AbuseIpdbOutput]):
    name = "abuseipdb"
    category = "identity"
    requires_key = "abuseipdb"
    input_model = AbuseIpdbInput
    output_model = AbuseIpdbOutput
    cost = CostSpec(unit="lookups/day", daily_quota=1000, note="free key: 1000/day")

    __doc__ = (
        "AbuseIPDB reputation for an IP (target): abuse confidence score, reports. Requires "
        "CAIRN_ABUSEIPDB_KEY."
    )

    async def run(self, inp: AbuseIpdbInput, ctx: PluginContext) -> AbuseIpdbOutput:
        key = ctx.key("abuseipdb") or ""
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        r = await http.get(
            "https://api.abuseipdb.com/api/v2/check",
            params={"ipAddress": inp.target, "maxAgeInDays": inp.max_age_days},
            headers={"Key": key, "Accept": "application/json"},
        )
        r.raise_for_status()
        d: dict[str, Any] = r.json().get("data", {})
        score = d.get("abuseConfidenceScore", 0)
        summary = (
            f"**{inp.target}** — AbuseIPDB\n"
            f"- Abuse score: {score}/100\n"
            f"- Reports: {d.get('totalReports', 0)}\n"
            f"- Country: {d.get('countryCode', 'unknown')}  ISP: {d.get('isp', 'unknown')}\n"
        )
        return AbuseIpdbOutput(
            source=self.name,
            summary_markdown=summary,
            score=score,
            country=d.get("countryCode"),
            isp=d.get("isp"),
            total_reports=d.get("totalReports", 0),
            entities=[Entity(type="ip", value=inp.target, attrs={"abuse_score": score})],
        )
