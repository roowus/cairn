"""RDAP/WHOIS plugin (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.identity.whois_rdap import WhoisRdapInput, WhoisRdapPlugin

_RDAP = {
    "events": [
        {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2026-08-13T04:00:00Z"},
    ],
    "entities": [
        {
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "ICANN"]]],
        }
    ],
    "nameservers": [{"ldhName": "A.ROOT-SERVERS.NET"}, {"ldhName": "B.ROOT-SERVERS.NET"}],
    "status": ["client transfer prohibited"],
}


@respx.mock
async def test_rdap_parses_record():
    respx.get("https://rdap.org/domain/example.com").mock(
        return_value=httpx.Response(200, json=_RDAP)
    )
    out = await WhoisRdapPlugin().run(
        WhoisRdapInput(target="example.com"), PluginContext(http=None)
    )
    assert out.registrar == "ICANN"
    assert out.created == "1995-08-14T04:00:00Z"
    assert out.expires == "2026-08-13T04:00:00Z"
    assert "A.ROOT-SERVERS.NET" in out.nameservers
