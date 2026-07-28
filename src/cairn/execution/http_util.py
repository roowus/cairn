"""Shared HTTP client acquisition for plugins.

Production paths always inject a browser-like client via :func:`build_context`.
Plugins that fall back to a bare ``httpx.AsyncClient(...)`` when ``ctx.http`` is
missing both **leak sockets** (no ``aclose``) and **skip browser headers** —
defeating the social-probe / anti-bot defaults.

Use :func:`http_client` instead:

```python
async with http_client(ctx) as http:
    r = await http.get(...)
```

When ``ctx.http`` is set, it is reused and **not** closed. When absent, a
temporary :func:`make_browser_client` is created and closed on exit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from cairn.execution.base import PluginContext
from cairn.execution.browser_http import DEFAULT_BROWSER_UA, make_browser_client


def _fallback_user_agent(ctx: PluginContext) -> str:
    ua = (ctx.user_agent or "").strip()
    if ua and "Mozilla" in ua:
        return ua
    return DEFAULT_BROWSER_UA


@asynccontextmanager
async def http_client(
    ctx: PluginContext,
    *,
    timeout: float | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an ``AsyncClient`` for this plugin call.

    * Injected ``ctx.http`` → reuse, do not close.
    * Otherwise → browser-like client, closed on context exit.
    """
    if ctx.http is not None:
        yield ctx.http
        return

    client = make_browser_client(
        timeout=ctx.timeout if timeout is None else timeout,
        proxy=ctx.proxy,
        user_agent=_fallback_user_agent(ctx),
    )
    try:
        yield client
    finally:
        await client.aclose()
