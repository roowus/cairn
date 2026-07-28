"""Shodan InternetDB plugin (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.identity.shodan_internetdb import (
    ShodanInternetDBInput,
    ShodanInternetDBPlugin,
)


@respx.mock
async def test_shodan_internetdb_parses_payload():
    respx.get("https://internetdb.shodan.io/8.8.8.8").mock(
        return_value=httpx.Response(
            200,
            json={
                "hostnames": ["dns.google"],
                "ports": [53, 443],
                "vulns": [],
                "tags": ["dns"],
            },
        )
    )
    out = await ShodanInternetDBPlugin().run(
        ShodanInternetDBInput(target="8.8.8.8"), PluginContext(http=None)
    )
    assert out.hostnames == ["dns.google"]
    assert out.ports == [53, 443]
    assert out.tags == ["dns"]
    assert "dns.google" in out.summary_markdown


@respx.mock
async def test_shodan_internetdb_404_is_clean():
    respx.get("https://internetdb.shodan.io/203.0.113.1").mock(return_value=httpx.Response(404))
    out = await ShodanInternetDBPlugin().run(
        ShodanInternetDBInput(target="203.0.113.1"), PluginContext(http=None)
    )
    assert "no data" in out.summary_markdown
