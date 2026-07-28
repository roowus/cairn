"""crt.sh plugin (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.infrastructure.crtsh import CrtshInput, CrtshPlugin


@respx.mock
async def test_crtsh_extracts_subdomains():
    respx.get("https://crt.sh/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"name_value": "www.example.com"},
                {"name_value": "api.example.com\nmail.example.com"},
                {"name_value": "example.com"},  # the apex itself, ignored
                {"name_value": "*.dev.example.com"},
            ],
        )
    )
    out = await CrtshPlugin().run(CrtshInput(target="example.com"), PluginContext(http=None))
    subs = set(out.subdomains)
    assert {"www.example.com", "api.example.com", "mail.example.com", "dev.example.com"} <= subs
    assert "example.com" not in subs  # apex excluded


@respx.mock
async def test_crtsh_empty_response():
    respx.get("https://crt.sh/").mock(return_value=httpx.Response(200, text=""))
    out = await CrtshPlugin().run(CrtshInput(target="nodomain.xyz"), PluginContext(http=None))
    assert out.subdomains == []
