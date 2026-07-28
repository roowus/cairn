"""hackertarget — hostsearch / reverse-IP / whois / DNS (free, no key).

Endpoints under ``https://api.hackertarget.com/`` — no API key required
(~50 lookups/day from one IP). The default ``hostsearch`` returns every hostname
sharing a target domain's IP (classic subdomain recon); reverse-IP lists every
domain resolving to a given IP. Great free complement to ``crtsh`` and
``dns_lookup`` for subdomain/host enumeration.
"""

from __future__ import annotations

from pydantic import Field

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)
from cairn.execution.http_util import http_client

_BASE = "https://api.hackertarget.com"


def _is_ip(target: str) -> bool:
    parts = target.strip().split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


class HackertargetInput(PluginInput):
    """``target`` is a domain or IP.

    ``query`` is one of hostsearch | reverseip | whois | dnslookup; ``auto``
    (default) picks hostsearch for domains and reverseip for IPs.
    """

    query: str = "auto"


class HackertargetOutput(PluginOutput):
    query: str = ""
    host_records: list[tuple[str, str]] = Field(default_factory=list)  # (ip, hostname)
    hostnames: list[str] = Field(default_factory=list)
    raw: str | None = None


class HackertargetPlugin(BasePlugin[HackertargetInput, HackertargetOutput]):
    name = "hackertarget"
    category = "infrastructure"
    requires_key = None
    # free tier is ~50 lookups/day per IP — opt in via CAIRN_ALLOW_DAILY_LIMITED=1
    daily_limited = True
    input_model = HackertargetInput
    output_model = HackertargetOutput
    cost = CostSpec(unit="lookups/day", daily_quota=50, note="~50/day per IP (free, no key)")

    __doc__ = (
        "Query hackertarget (free, no key): hostsearch (subdomains/IPs for a domain), reverse-IP "
        "(domains on an IP), whois, or DNS for a target. ~50/day per IP."
    )

    async def run(self, inp: HackertargetInput, ctx: PluginContext) -> HackertargetOutput:
        t = inp.target.strip()
        query = inp.query
        if query == "auto":
            query = "reverseip" if _is_ip(t) else "hostsearch"
        # endpoint name differs slightly from the input spelling
        ep = {
            "hostsearch": "hostsearch",
            "reverseip": "reverseiplookup",
            "whois": "whois",
            "dnslookup": "dnslookup",
        }.get(query, "hostsearch")

        async with http_client(ctx) as http:
            r = await http.get(f"{_BASE}/{ep}/", params={"q": t})
            r.raise_for_status()
            text = r.text.strip()

            out = HackertargetOutput(source=self.name, query=query)
            low = text.lower()
            if "api count exceeded" in low or "error" in low[:30].lower():
                out.raw = text
                out.quota_remaining = 0  # free daily quota (~50/day) exhausted
                out.summary_markdown = (
                    f"**{t}** — hackertarget: {text.splitlines()[0] if text else 'no response'}"
                )
                return out

            out.host_records, out.hostnames, out.raw = _parse(query, text)
            out.summary_markdown = _summary(out, t)
            out.entities = _entities(out, t)
            return out


def _parse(query: str, text: str) -> tuple[list[tuple[str, str]], list[str], str | None]:
    host_records: list[tuple[str, str]] = []
    hostnames: list[str] = []
    raw: str | None = None
    if query == "hostsearch":
        for line in text.splitlines():
            if "," in line:
                ip, _, host = line.partition(",")
                host_records.append((ip.strip(), host.strip()))
    elif query == "reverseip":
        for line in text.splitlines():
            h = line.strip()
            if h:
                hostnames.append(h)
    else:  # whois / dnslookup — keep verbatim
        raw = text
    return host_records, hostnames, raw


def _summary(out: HackertargetOutput, target: str) -> str:
    if out.query == "hostsearch":
        if not out.host_records:
            return f"**{target}** — hackertarget hostsearch: no hosts found."
        lines = [f"**{target}** — hackertarget hostsearch: {len(out.host_records)} host(s):"]
        for ip, host in out.host_records[:25]:
            lines.append(f"- {host} ({ip})")
        return "\n".join(lines)
    if out.query == "reverseip":
        if not out.hostnames:
            return f"**{target}** — hackertarget reverse-IP: no hosts found."
        lines = [f"**{target}** — hackertarget reverse-IP: {len(out.hostnames)} host(s):"]
        lines += [f"- {h}" for h in out.hostnames[:25]]
        return "\n".join(lines)
    head = (out.raw or "").splitlines()
    preview = "\n".join(head[:20])
    return f"**{target}** — hackertarget {out.query}:\n```\n{preview}\n```"


def _entities(out: HackertargetOutput, target: str) -> list[Entity]:
    ents = [Entity(type="ip" if _is_ip(target) else "domain", value=target)]
    for ip, host in out.host_records:
        ents.append(Entity(type="hostname", value=host, attrs={"ip": ip}))
        ents.append(Entity(type="ip", value=ip))
    for h in out.hostnames:
        ents.append(Entity(type="hostname", value=h))
    return ents
