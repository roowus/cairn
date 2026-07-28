"""http_client helper — reuse injected client, close fallback browser client."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from cairn.execution.base import PluginContext
from cairn.execution.browser_http import DEFAULT_BROWSER_UA
from cairn.execution.http_util import http_client


@pytest.mark.asyncio
async def test_reuses_injected_client_without_closing():
    injected = AsyncMock(spec=httpx.AsyncClient)
    ctx = PluginContext(http=injected)
    async with http_client(ctx) as http:
        assert http is injected
    injected.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_is_browser_like_and_closed(monkeypatch):
    closed = {"n": 0}
    created = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)

        async def aclose(self) -> None:
            closed["n"] += 1

    def _fake_make_browser_client(**kwargs):
        return _FakeClient(**kwargs)

    monkeypatch.setattr(
        "cairn.execution.http_util.make_browser_client", _fake_make_browser_client
    )
    ctx = PluginContext(http=None, timeout=12.0, proxy="http://proxy.local:8080")
    async with http_client(ctx) as http:
        assert isinstance(http, _FakeClient)
        assert created["timeout"] == 12.0
        assert created["proxy"] == "http://proxy.local:8080"
        # bare PluginContext UA is browser default; fallback must keep Mozilla UA
        assert "Mozilla" in created["user_agent"]
    assert closed["n"] == 1


@pytest.mark.asyncio
async def test_fallback_timeout_override(monkeypatch):
    created = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(
        "cairn.execution.http_util.make_browser_client",
        lambda **kwargs: _FakeClient(**kwargs),
    )
    ctx = PluginContext(http=None, timeout=10.0)
    async with http_client(ctx, timeout=60.0) as _http:
        pass
    assert created["timeout"] == 60.0


@pytest.mark.asyncio
async def test_legacy_cairn_ua_is_replaced_on_fallback(monkeypatch):
    created = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(
        "cairn.execution.http_util.make_browser_client",
        lambda **kwargs: _FakeClient(**kwargs),
    )
    ctx = PluginContext(http=None, user_agent="cairn/0.1")
    async with http_client(ctx) as _http:
        pass
    assert created["user_agent"] == DEFAULT_BROWSER_UA


def test_plugin_context_default_ua_is_browser():
    assert "Mozilla" in PluginContext().user_agent
    assert PluginContext().user_agent == DEFAULT_BROWSER_UA


@pytest.mark.asyncio
async def test_plugin_without_injected_http_still_works_with_respx():
    """Direct plugin.run(PluginContext()) must not leak and must hit the network mock."""
    import respx

    from cairn.plugins.identity.shodan_internetdb import (
        ShodanInternetDBInput,
        ShodanInternetDBPlugin,
    )

    with respx.mock:
        respx.get("https://internetdb.shodan.io/1.1.1.1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "hostnames": ["one.one.one.one"],
                    "ports": [53, 443],
                    "vulns": [],
                    "tags": ["cdn"],
                },
            )
        )
        out = await ShodanInternetDBPlugin().run(
            ShodanInternetDBInput(target="1.1.1.1"), PluginContext(http=None)
        )
    assert "one.one.one.one" in out.summary_markdown
    assert 443 in out.ports
