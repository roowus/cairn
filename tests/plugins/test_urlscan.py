"""urlscan plugin (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.web.urlscan import UrlscanInput, UrlscanPlugin

_BODY = {
    "total": 2,
    "results": [
        {
            "page": {
                "url": "https://example.com/",
                "domain": "example.com",
                "ip": "93.184.216.34",
                "title": "Example",
                "server": "ECS",
            }
        },
        {
            "page": {
                "url": "https://sub.example.com/x",
                "domain": "sub.example.com",
                "ip": "93.184.216.35",
                "title": "Sub",
                "server": "nginx",
            }
        },
    ],
}


@respx.mock
async def test_urlscan_parses_hits_and_entities():
    respx.get("https://urlscan.io/api/v1/search/").mock(
        return_value=httpx.Response(200, json=_BODY)
    )
    out = await UrlscanPlugin().run(UrlscanInput(target="example.com"), PluginContext(http=None))
    assert out.total == 2
    assert len(out.hits) == 2
    assert out.hits[0].page_ip == "93.184.216.34"
    assert "example.com" in out.summary_markdown
    ips = {e.value for e in out.entities if e.type == "ip"}
    assert {"93.184.216.34", "93.184.216.35"} <= ips


@respx.mock
async def test_urlscan_ip_target_uses_ip_query():
    route = respx.get("https://urlscan.io/api/v1/search/").mock(
        return_value=httpx.Response(200, json={"total": 0, "results": []})
    )
    out = await UrlscanPlugin().run(UrlscanInput(target="8.8.8.8"), PluginContext(http=None))
    assert route.called
    # request went out with q=ip:8.8.8.8
    assert route.calls.last.request.url.params["q"] == "ip:8.8.8.8"
    assert "no public scans" in out.summary_markdown


@respx.mock
async def test_urlscan_5xx_degrades_gracefully():
    respx.get("https://urlscan.io/api/v1/search/").mock(return_value=httpx.Response(503))
    out = await UrlscanPlugin().run(UrlscanInput(target="example.com"), PluginContext(http=None))
    assert "temporarily unavailable" in out.summary_markdown
