"""common_crawl plugin (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.web.common_crawl import (
    CommonCrawlInput,
    CommonCrawlPlugin,
    _index_url_pattern,
)

_COLLINFO = [{"id": "CC-MAIN-2026-30", "name": "July 2026 Index"}]

_NDJSON = "\n".join(
    [
        (
            '{"urlkey":"com,example)/","timestamp":"20260715000000",'
            '"url":"https://example.com/","status":"200","mime":"text/html"}'
        ),
        (
            '{"urlkey":"com,example)/about","timestamp":"20260716000000",'
            '"url":"https://example.com/about","status":"200","mime":"text/html"}'
        ),
        "not-json",
    ]
)


def test_index_url_pattern_normalizes_bare_domain():
    assert _index_url_pattern("example.com") == "example.com/*"
    assert _index_url_pattern(" https://example.com/path ") == "https://example.com/path"
    assert _index_url_pattern("*.example.com/*") == "*.example.com/*"
    assert _index_url_pattern("example.com/foo") == "example.com/foo"


@respx.mock
async def test_common_crawl_parses_ndjson_matches():
    respx.get("https://index.commoncrawl.org/collinfo.json").mock(
        return_value=httpx.Response(200, json=_COLLINFO)
    )
    route = respx.get("https://index.commoncrawl.org/CC-MAIN-2026-30-index").mock(
        return_value=httpx.Response(200, text=_NDJSON)
    )
    out = await CommonCrawlPlugin().run(
        CommonCrawlInput(target="example.com"), PluginContext(http=None)
    )
    assert route.called
    assert route.calls.last.request.url.params["url"] == "example.com/*"
    assert route.calls.last.request.url.params["output"] == "json"
    assert len(out.matches) == 2
    assert out.matches[0]["url"] == "https://example.com/"
    assert "2 matches" in out.summary_markdown
    assert "https://example.com/about" in out.summary_markdown
    assert out.source == "common_crawl"


@respx.mock
async def test_common_crawl_preserves_full_url_query():
    respx.get("https://index.commoncrawl.org/collinfo.json").mock(
        return_value=httpx.Response(200, json=_COLLINFO)
    )
    route = respx.get("https://index.commoncrawl.org/CC-MAIN-2026-30-index").mock(
        return_value=httpx.Response(200, text="")
    )
    out = await CommonCrawlPlugin().run(
        CommonCrawlInput(target="https://example.com/path"), PluginContext(http=None)
    )
    assert route.calls.last.request.url.params["url"] == "https://example.com/path"
    assert "0 matches" in out.summary_markdown
    assert out.matches == []


@respx.mock
async def test_common_crawl_http_error_surfaces_status():
    respx.get("https://index.commoncrawl.org/collinfo.json").mock(
        return_value=httpx.Response(200, json=_COLLINFO)
    )
    respx.get("https://index.commoncrawl.org/CC-MAIN-2026-30-index").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    out = await CommonCrawlPlugin().run(
        CommonCrawlInput(target="example.com"), PluginContext(http=None)
    )
    assert "HTTP 503" in out.summary_markdown
    assert "unavailable" in out.summary_markdown
    assert out.matches == []


@respx.mock
async def test_common_crawl_empty_index_list():
    respx.get("https://index.commoncrawl.org/collinfo.json").mock(
        return_value=httpx.Response(200, json=[])
    )
    out = await CommonCrawlPlugin().run(
        CommonCrawlInput(target="example.com"), PluginContext(http=None)
    )
    assert "no index available" in out.summary_markdown
    assert out.matches == []
