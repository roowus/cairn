"""h1_reference plugin: GraphQL parse, keyword filter, error paths (MockTransport)."""

from __future__ import annotations

from typing import Any

import httpx

from cairn.execution.base import PluginContext
from cairn.plugins.web.h1_reference import H1ReferenceInput, H1ReferencePlugin


def _client(data: Any, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=data)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ctx(http: httpx.AsyncClient) -> PluginContext:
    return PluginContext(http=http)


def _data() -> dict[str, Any]:
    return {
        "data": {
            "search": {
                "nodes": [
                    {
                        "severity_rating": "high", "total_awarded_amount": 5000, "currency": "USD",
                        "cwe": "CWE-918 SSRF", "cve_ids": [], "votes": 99,
                        "team": {"handle": "shopify"}, "reporter": {"username": "alice"},
                        "report": {"_id": "1", "title": "SSRF in webhook", "url": "https://hackerone.com/reports/1"},
                    },
                    {
                        "severity_rating": "medium", "total_awarded_amount": 500, "currency": "USD",
                        "cwe": "CWE-79", "cve_ids": [], "votes": 10,
                        "team": {"handle": "gitlab"}, "reporter": {"username": "bob"},
                        "report": {"_id": "2", "title": "XSS in profile", "url": "https://hackerone.com/reports/2"},
                    },
                ],
                "pageInfo": {"endCursor": None},
            }
        }
    }


async def test_h1_reference_parses_reports_and_entities():
    out = await H1ReferencePlugin().run(
        H1ReferenceInput(target="SSRF|XSS", limit=10),
        _ctx(_client(_data())),
    )
    assert len(out.reports) == 2
    titles = {r.title for r in out.reports}
    assert "SSRF in webhook" in titles
    urls = [e.value for e in out.entities if e.type == "url"]
    assert "https://hackerone.com/reports/1" in urls
    assert "SSRF in webhook" in out.summary_markdown


async def test_h1_reference_keyword_filter():
    out = await H1ReferencePlugin().run(
        H1ReferenceInput(target="SSRF"),
        _ctx(_client(_data())),
    )
    assert len(out.reports) == 1
    assert out.reports[0].title == "SSRF in webhook"


async def test_h1_reference_non_200_returns_message():
    out = await H1ReferencePlugin().run(
        H1ReferenceInput(target="SSRF"),
        _ctx(_client({}, status=503)),
    )
    assert out.reports == []
    assert "HTTP 503" in out.summary_markdown
