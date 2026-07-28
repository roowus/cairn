"""ripestat plugin (mocked) — network-info + prefix-overview + whois."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.infrastructure.ripestat import RipestatInput, RipestatPlugin


@respx.mock
async def test_ripestat_ip_uses_network_info_for_asn_prefix():
    respx.get("https://stat.ripe.net/data/network-info/data.json").mock(
        return_value=httpx.Response(200, json={"data": {"asns": ["15169"], "prefix": "8.8.8.0/24"}})
    )
    respx.get("https://stat.ripe.net/data/prefix-overview/data.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "resource": "8.8.8.0/24",
                    "asns": [{"asn": 15169, "holder": "GOOGLE - Google LLC"}],
                }
            },
        )
    )
    # whois alone is incomplete for many IPs (no origin/route) — still called for country.
    respx.get("https://stat.ripe.net/data/whois/data.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "records": [
                        [
                            {"key": "NetName", "value": "GOGL"},
                            {"key": "Country", "value": "US"},
                            {"key": "CIDR", "value": "8.8.8.0/24"},
                        ]
                    ]
                }
            },
        )
    )
    out = await RipestatPlugin().run(RipestatInput(target="8.8.8.8"), PluginContext(http=None))
    assert out.asn == "AS15169"
    assert out.prefix == "8.8.8.0/24"
    assert out.holder == "GOOGLE - Google LLC"
    assert out.country == "US"
    assert "AS15169" in out.summary_markdown
    assert "unknown" not in out.summary_markdown.split("ASN:")[1].splitlines()[0]
    asns = {e.value for e in out.entities if e.type == "asn"}
    assert "AS15169" in asns


@respx.mock
async def test_ripestat_whois_fallback_keys():
    respx.get("https://stat.ripe.net/data/network-info/data.json").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    respx.get("https://stat.ripe.net/data/prefix-overview/data.json").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    respx.get("https://stat.ripe.net/data/whois/data.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "records": [
                        [
                            {"key": "route", "value": "1.2.3.0/24"},
                            {"key": "origin", "value": "AS64496"},
                            {"key": "netname", "value": "EXAMPLE-NET"},
                            {"key": "country", "value": "NL"},
                        ]
                    ]
                }
            },
        )
    )
    out = await RipestatPlugin().run(RipestatInput(target="1.2.3.4"), PluginContext(http=None))
    assert out.asn == "AS64496"
    assert out.prefix == "1.2.3.0/24"
    assert out.holder == "EXAMPLE-NET"
    assert out.country == "NL"
