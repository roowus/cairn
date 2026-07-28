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


def _as_label(val: Any) -> str | None:
    if val is None or val == "":
        return None
    s = str(val).strip()
    if not s:
        return None
    if s.upper().startswith("AS"):
        return s.upper() if s[2:].isdigit() else s
    if s.isdigit():
        return f"AS{s}"
    return s


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
        asn = holder = prefix = country = None

        # network-info is the reliable path for IP → announcing ASN + covering prefix.
        # whois alone often returns ARIN registry records without origin/route keys.
        try:
            ni = await http.get(
                "https://stat.ripe.net/data/network-info/data.json",
                params={"resource": inp.target},
            )
            if ni.status_code == 200:
                data = (ni.json().get("data") or {}) if ni.text.strip() else {}
                asns = data.get("asns") or []
                if asns:
                    asn = _as_label(asns[0])
                prefix = data.get("prefix") or prefix
        except (httpx.HTTPError, ValueError):
            pass

        # prefix-overview adds holder when we have a prefix (or the target is one).
        overview_resource = prefix or inp.target
        try:
            po = await http.get(
                "https://stat.ripe.net/data/prefix-overview/data.json",
                params={"resource": overview_resource},
            )
            if po.status_code == 200:
                data = (po.json().get("data") or {}) if po.text.strip() else {}
                asns = data.get("asns") or []
                if asns:
                    first = asns[0]
                    if isinstance(first, dict):
                        asn = asn or _as_label(first.get("asn"))
                        holder = holder or first.get("holder")
                    else:
                        asn = asn or _as_label(first)
                prefix = data.get("resource") or prefix
        except (httpx.HTTPError, ValueError):
            pass

        # whois fills netname / country and ARIN-style keys (NetName, OrgName, CIDR).
        try:
            r = await http.get(
                "https://stat.ripe.net/data/whois/data.json",
                params={"resource": inp.target},
            )
            if r.status_code == 200:
                d: dict[str, Any] = r.json()
                records = (d.get("data") or {}).get("records") or []
                for rec in records:
                    for item in rec:
                        key = (item.get("key") or "").lower()
                        val = item.get("value")
                        if not val:
                            continue
                        if key in ("route", "cidr") and not prefix:
                            prefix = val
                        elif key in ("origin", "originas", "originasnum") and not asn:
                            asn = _as_label(val)
                        elif key in ("netname", "orgname", "org-name", "descr") and not holder:
                            holder = val
                        elif key == "country" and not country:
                            country = val
        except (httpx.HTTPError, ValueError):
            pass

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
        if prefix:
            ents.append(Entity(type="prefix", value=str(prefix)))
        return RipestatOutput(
            source=self.name,
            summary_markdown=summary,
            asn=asn and str(asn),
            holder=holder,
            prefix=prefix,
            country=country,
            entities=ents,
        )
