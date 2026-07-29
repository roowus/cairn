"""wayback_fetch — archived_url redaction (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.web.wayback_fetch import WaybackFetchInput, WaybackFetchPlugin


@respx.mock
async def test_wayback_fetch_redacts_userinfo_in_summary_and_entities():
    snap_url = (
        "http://web.archive.org/web/20131008213727/http://user:pass@example.com/"
    )
    respx.get("https://archive.org/wayback/available").mock(
        return_value=httpx.Response(
            200,
            json={
                "archived_snapshots": {
                    "closest": {
                        "available": True,
                        "url": snap_url,
                        "timestamp": "20131008213727",
                    }
                }
            },
        )
    )
    respx.get(url__startswith="http://web.archive.org/web/").mock(
        return_value=httpx.Response(200, text="<html><body>hello world</body></html>")
    )
    out = await WaybackFetchPlugin().run(
        WaybackFetchInput(target="http://example.com/"), PluginContext(http=None)
    )
    assert "user:pass@" not in out.summary_markdown
    assert out.archived_url is not None
    assert "user:pass@" not in out.archived_url
    assert "http://example.com/" in (out.archived_url or "")
    for e in out.entities:
        assert "user:pass@" not in e.value
        archived = (e.attrs or {}).get("archived", "")
        assert "user:pass@" not in archived
