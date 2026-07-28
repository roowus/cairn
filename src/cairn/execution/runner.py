"""Builds the :class:`PluginContext` for a session from settings."""

from __future__ import annotations

from pathlib import Path

import httpx

from cairn.core.config import Settings, load_settings
from cairn.execution.base import PluginContext
from cairn.execution.browser_http import DEFAULT_BROWSER_UA, make_browser_client


def _resolve_workspace(s: Settings) -> Path | None:
    """Resolve and ensure the scratch workspace dir; None when unset.

    cwd is ALSO a workspace root (challenge files in ``./``); this is only the
    scratch dir for downloads/artifacts (default ``~/.cairn/workspace``). Created
    on first use.
    """
    ws = s.workspace_dir
    if not ws or str(ws) in ("", "."):
        return None
    p = Path(ws).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_context(
    settings: Settings | None = None, *, http: httpx.AsyncClient | None = None
) -> PluginContext:
    """Construct a PluginContext populated from settings.

    A shared browser-like ``httpx.AsyncClient`` is created unless one is supplied
    (tests pass a client routed through ``respx``). The caller owns the client's
    lifecycle; close it via ``await ctx.http.aclose()`` when the session ends.

    Default headers mimic desktop Chrome so first-party profile pages (IG, etc.)
    behave closer to an incognito tab than a bare bot client.
    """
    s = settings or load_settings()
    ua = s.user_agent
    # Legacy default advertised Cairn; prefer a real browser UA for fetches.
    if not ua or ua.startswith("cairn/"):
        ua = DEFAULT_BROWSER_UA
    client = http or make_browser_client(
        timeout=s.request_timeout,
        proxy=s.proxy,
        user_agent=ua,
    )
    return PluginContext(
        timeout=s.request_timeout,
        proxy=s.proxy,
        user_agent=ua,
        keys=s.plugin_keys(),
        http=client,
        allow_daily_limited=s.allow_daily_limited,
        workspace=_resolve_workspace(s),
    )


async def close_context(ctx: PluginContext) -> None:
    """Close the shared HTTP client if we own it."""
    if ctx.http is not None:
        await ctx.http.aclose()
