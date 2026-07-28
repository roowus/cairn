"""wayback_cdx plugin (mocked) — credentialed original URLs redacted."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.infrastructure.wayback_cdx import WaybackCdxInput, WaybackCdxPlugin


@respx.mock
async def test_wayback_cdx_redacts_userinfo_in_summary_and_snapshots():
    body = [
        ["timestamp", "original", "statuscode", "mimetype"],
        ["20131008213727", "http://user:pass@example.com/", "200", "text/html"],
        ["20131010013448", "http://user:pass@example.com/login", "200", "text/html"],
        ["20200101000000", "https://example.com/", "200", "text/html"],
    ]
    respx.get("http://web.archive.org/cdx/search/cdx").mock(
        return_value=httpx.Response(200, json=body)
    )
    out = await WaybackCdxPlugin().run(
        WaybackCdxInput(target="example.com"), PluginContext(http=None)
    )
    assert "user:pass@" not in out.summary_markdown
    assert "http://example.com/" in out.summary_markdown
    assert "http://example.com/login" in out.summary_markdown
    originals = [s.get("original") for s in out.snapshots]
    assert "http://user:pass@example.com/" not in originals
    assert "http://example.com/" in originals
    assert "http://example.com/login" in originals
    assert "https://example.com/" in originals


@respx.mock
async def test_wayback_cdx_empty():
    respx.get("http://web.archive.org/cdx/search/cdx").mock(
        return_value=httpx.Response(200, json=[])
    )
    out = await WaybackCdxPlugin().run(
        WaybackCdxInput(target="nodomain.xyz"), PluginContext(http=None)
    )
    assert out.snapshots == []
    assert "no snapshots" in out.summary_markdown
