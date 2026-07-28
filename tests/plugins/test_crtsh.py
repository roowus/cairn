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
async def test_crtsh_empty_body_is_zero_subdomains_not_unavailable():
    respx.get("https://crt.sh/").mock(return_value=httpx.Response(200, text=""))
    out = await CrtshPlugin().run(CrtshInput(target="nodomain.xyz"), PluginContext(http=None))
    assert out.subdomains == []
    assert "0 subdomains" in out.summary_markdown
    assert "unavailable" not in out.summary_markdown


@respx.mock
async def test_crtsh_empty_list_is_zero_subdomains():
    respx.get("https://crt.sh/").mock(return_value=httpx.Response(200, json=[]))
    out = await CrtshPlugin().run(CrtshInput(target="nodomain.xyz"), PluginContext(http=None))
    assert out.subdomains == []
    assert "0 subdomains" in out.summary_markdown


@respx.mock
async def test_crtsh_http_error_surfaces_status():
    respx.get("https://crt.sh/").mock(return_value=httpx.Response(503, text="busy"))
    out = await CrtshPlugin().run(CrtshInput(target="example.com"), PluginContext(http=None))
    assert out.subdomains == []
    assert "HTTP 503" in out.summary_markdown


@respx.mock
async def test_crtsh_timeout_is_honest():
    respx.get("https://crt.sh/").mock(side_effect=httpx.ReadTimeout("slow"))
    out = await CrtshPlugin().run(CrtshInput(target="example.com"), PluginContext(http=None))
    assert out.subdomains == []
    assert "unreachable" in out.summary_markdown
    assert "ReadTimeout" in out.summary_markdown


@respx.mock
async def test_crtsh_invalid_json_surfaces_error():
    respx.get("https://crt.sh/").mock(return_value=httpx.Response(200, text="<html>nope</html>"))
    out = await CrtshPlugin().run(CrtshInput(target="example.com"), PluginContext(http=None))
    assert "not valid JSON" in out.summary_markdown
