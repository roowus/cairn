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
    assert "on-target" in out.summary_markdown
    ips = {e.value for e in out.entities if e.type == "ip"}
    assert {"93.184.216.34", "93.184.216.35"} <= ips


@respx.mock
async def test_urlscan_filters_off_domain_noise():
    body = {
        "total": 10000,
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
                    "url": "https://www.milb.com/columbus",
                    "domain": "www.milb.com",
                    "ip": "1.2.3.4",
                    "title": "noise",
                    "server": "cloud",
                }
            },
            {
                "page": {
                    "url": "https://keepassdx-customer-support-number.pages.dev/",
                    "domain": "keepassdx-customer-support-number.pages.dev",
                    "ip": "5.6.7.8",
                    "title": "scam",
                    "server": "cloudflare",
                }
            },
            {
                "page": {
                    "url": "https://api.example.com/v1",
                    "domain": "api.example.com",
                    "ip": "93.184.216.36",
                    "title": "API",
                    "server": "nginx",
                }
            },
        ],
    }
    respx.get("https://urlscan.io/api/v1/search/").mock(
        return_value=httpx.Response(200, json=body)
    )
    out = await UrlscanPlugin().run(UrlscanInput(target="example.com"), PluginContext(http=None))
    domains = {h.page_domain for h in out.hits}
    assert domains == {"example.com", "api.example.com"}
    assert "milb.com" not in out.summary_markdown
    assert "pages.dev" not in out.summary_markdown
    # entities must not include off-target noise
    entity_domains = {e.value for e in out.entities if e.type == "domain"}
    assert "www.milb.com" not in entity_domains
    assert "keepassdx-customer-support-number.pages.dev" not in entity_domains
    assert "1.2.3.4" not in {e.value for e in out.entities if e.type == "ip"}
    # summary must not claim 10000 as on-target
    assert "10000 scan" not in out.summary_markdown
    assert "2 on-target" in out.summary_markdown


@respx.mock
async def test_urlscan_dedupes_by_url():
    body = {
        "total": 2,
        "results": [
            {
                "page": {
                    "url": "https://example.com/",
                    "domain": "example.com",
                    "ip": "1.1.1.1",
                    "title": "A",
                    "server": "a",
                }
            },
            {
                "page": {
                    "url": "https://example.com/",
                    "domain": "example.com",
                    "ip": "1.1.1.1",
                    "title": "A again",
                    "server": "a",
                }
            },
        ],
    }
    respx.get("https://urlscan.io/api/v1/search/").mock(
        return_value=httpx.Response(200, json=body)
    )
    out = await UrlscanPlugin().run(UrlscanInput(target="example.com"), PluginContext(http=None))
    assert len(out.hits) == 1


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
