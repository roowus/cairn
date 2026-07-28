"""RIPEstat — ASN/IP network metadata (free, no key)."""

from __future__ import annotations

from typing import Any

import httpx

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput


class RipestatInput(PluginInput):
    """`target` is an IP, ASN (e.g. AS15169), or prefix."""


class RipestatOutput(PluginOutput):
    asn: str | None = None
    holder: str | None = None
    prefix: str | None = None
    country: str | None = None


class RipestatPlugin(BasePlugin[RipestatInput, RipestatOutput]):
    name = "ripestat"
    category = "infrastructure"
    requires_key = None
    input_model = RipestatInput
    output_model = RipestatOutput

    __doc__ = (
        "Enrich an IP/ASN/prefix (target) via RIPEstat: announcing ASN, holder, prefix, "
        "country. Free."
    )

    async def run(self, inp: RipestatInput, ctx: PluginContext) -> RipestatOutput:
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        r = await http.get(
            "https://stat.ripe.net/data/whois/data.json",
            params={"resource": inp.target},
        )
        r.raise_for_status()
        d: dict[str, Any] = r.json()
        records = (d.get("data") or {}).get("records") or []
        asn = holder = prefix = country = None
        for rec in records:
            for item in rec:
                key = item.get("key", "").lower()
                val = item.get("value")
                if key == "route" and not prefix:
                    prefix = val
                elif key == "origin" and not asn:
                    asn = val
                elif key == "netname" and not holder:
                    holder = val
                elif key == "country" and not country:
                    country = val
        summary = (
            f"**{inp.target}** — RIPEstat\n"
            f"- ASN: {asn or 'unknown'}\n"
            f"- Holder/Netname: {holder or 'unknown'}\n"
            f"- Prefix: {prefix or 'unknown'}\n"
            f"- Country: {country or 'unknown'}\n"
        )
        ents = [
            Entity(type="asn" if (inp.target.upper().startswith("AS")) else "ip", value=inp.target)
        ]
        if asn:
            ents.append(Entity(type="asn", value=str(asn)))
        return RipestatOutput(
            source=self.name,
            summary_markdown=summary,
            asn=asn and str(asn),
            holder=holder,
            prefix=prefix,
            country=country,
            entities=ents,
        )
