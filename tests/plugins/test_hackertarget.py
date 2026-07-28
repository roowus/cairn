"""hackertarget plugin (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.infrastructure.hackertarget import HackertargetInput, HackertargetPlugin


@respx.mock
async def test_hostsearch_parses_records():
    respx.get("https://api.hackertarget.com/hostsearch/").mock(
        return_value=httpx.Response(
            200,
            text="93.184.216.34,example.com\n93.184.216.34,www.example.com\n",
        )
    )
    out = await HackertargetPlugin().run(
        HackertargetInput(target="example.com"), PluginContext(http=None)
    )
    assert out.query == "hostsearch"
    assert ("93.184.216.34", "example.com") in out.host_records
    assert "www.example.com" in out.summary_markdown
    hosts = {e.value for e in out.entities if e.type == "hostname"}
    assert {"example.com", "www.example.com"} <= hosts


@respx.mock
async def test_reverseip_auto_selected_for_ip():
    route = respx.get("https://api.hackertarget.com/reverseiplookup/").mock(
        return_value=httpx.Response(200, text="dns.google\na.example.com\n")
    )
    out = await HackertargetPlugin().run(
        HackertargetInput(target="8.8.8.8"), PluginContext(http=None)
    )
    assert route.called
    assert out.query == "reverseip"
    assert "dns.google" in out.hostnames


@respx.mock
async def test_rate_limit_message_is_clean():
    respx.get("https://api.hackertarget.com/hostsearch/").mock(
        return_value=httpx.Response(200, text="API count exceeded - wait 24 hours")
    )
    out = await HackertargetPlugin().run(
        HackertargetInput(target="example.com"), PluginContext(http=None)
    )
    assert "api count exceeded" in out.summary_markdown.lower()
