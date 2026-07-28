"""DNS lookup — free, pure Python (dnspython)."""

from __future__ import annotations

import dns.asyncresolver
import dns.exception
import dns.resolver
from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput


class DnsLookupInput(PluginInput):
    """`target` is a hostname. `record_type` defaults to A."""

    record_type: str = "A"


class DnsLookupOutput(PluginOutput):
    record_type: str = "A"
    answers: list[str] = Field(default_factory=list)


class DnsLookupPlugin(BasePlugin[DnsLookupInput, DnsLookupOutput]):
    name = "dns_lookup"
    category = "infrastructure"
    requires_key = None
    input_model = DnsLookupInput
    output_model = DnsLookupOutput

    __doc__ = (
        "Resolve DNS records for a hostname (target). record_type defaults to A; try "
        "AAAA/MX/NS/TXT/CNAME."
    )

    async def run(self, inp: DnsLookupInput, ctx: PluginContext) -> DnsLookupOutput:
        qtype = inp.record_type.upper()
        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = ctx.timeout
        try:
            answer = await resolver.resolve(inp.target, qtype)
            records = sorted({r.to_text().rstrip(".") for r in answer})
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.DNSException) as exc:
            return DnsLookupOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** {qtype}: no records — {exc.__class__.__name__}",
                record_type=qtype,
                entities=[Entity(type="domain", value=inp.target)],
            )
        ent_type = "ip" if qtype in {"A", "AAAA"} else "domain"
        entities = [Entity(type="domain", value=inp.target)] + [
            Entity(type=ent_type, value=r) for r in records
        ]
        return DnsLookupOutput(
            source=self.name,
            summary_markdown=f"**{inp.target}** ({qtype}) — {', '.join(records) or 'none'}",
            record_type=qtype,
            answers=records,
            entities=entities,
        )
