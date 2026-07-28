"""RDAP / WHOIS lookup — free, no key.

Uses the rdap.org bootstrap, which redirects to the authoritative RDAP server
for a domain. Returns registrar, key dates, and nameservers.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput
from cairn.execution.http_util import http_client


class WhoisRdapInput(PluginInput):
    """`target` is a domain name (e.g. example.com)."""


class WhoisRdapOutput(PluginOutput):
    registrar: str | None = None
    created: str | None = None
    updated: str | None = None
    expires: str | None = None
    status: list[str] = Field(default_factory=list)
    nameservers: list[str] = Field(default_factory=list)


class WhoisRdapPlugin(BasePlugin[WhoisRdapInput, WhoisRdapOutput]):
    name = "whois_rdap"
    category = "identity"
    requires_key = None
    input_model = WhoisRdapInput
    output_model = WhoisRdapOutput

    __doc__ = "Look up a domain's (target) RDAP/WHOIS record: registrar, dates, nameservers. Free."

    async def run(self, inp: WhoisRdapInput, ctx: PluginContext) -> WhoisRdapOutput:
        async with http_client(ctx) as http:
            r = await http.get(
                f"https://rdap.org/domain/{inp.target}",
                headers={"Accept": "application/rdap+json"},
            )
            r.raise_for_status()
            d: dict[str, Any] = r.json()

            def _event(date_kind: str) -> str | None:
                for e in d.get("events", []):
                    if e.get("eventAction") == date_kind:
                        return e.get("eventDate")
                return None

            registrar = None
            for ent in d.get("entities", []):
                roles = ent.get("roles", [])
                if "registrar" in roles:
                    registrar = ent.get("vcardArray", [None, []])[1]
                    # pull FN if structured
                    registrar = _vcard_fn(ent) or ent.get("handle") or "registrar"
                    break
            nameservers = sorted(
                {n.get("ldhName") for n in d.get("nameservers", []) if n.get("ldhName")}
            )

            summary = (
                f"**{inp.target}** — RDAP/WHOIS\n"
                f"- Registrar: {registrar or 'unknown'}\n"
                f"- Created: {_event('registration') or 'unknown'}\n"
                f"- Updated: {_event('last changed') or 'unknown'}\n"
                f"- Expires: {_event('expiration') or 'unknown'}\n"
                f"- Status: {', '.join(d.get('status', [])) or 'none'}\n"
                f"- Nameservers: {', '.join(nameservers) or 'none'}\n"
            )
            return WhoisRdapOutput(
                source=self.name,
                summary_markdown=summary,
                registrar=registrar,
                created=_event("registration"),
                updated=_event("last changed"),
                expires=_event("expiration"),
                status=list(d.get("status", [])),
                nameservers=nameservers,
                entities=[Entity(type="domain", value=inp.target, attrs={"registrar": registrar})],
            )


def _vcard_fn(entity: dict[str, Any]) -> str | None:
    vcard = entity.get("vcardArray") or [None, []]
    if len(vcard) < 2:
        return None
    for item in vcard[1]:
        if isinstance(item, list) and item and item[0] == "fn":
            return item[3] if len(item) > 3 else None
    return None
