"""Browser-like HTTP client defaults + resilient GETs.

Many sites (Instagram, X, TikTok, …) answer a real browser in a normal or
incognito window, but return an empty JS shell — or a wrong answer via a
third-party mirror — to bare ``httpx``/``curl`` with a bot UA.

Cairn's shared session client should therefore look like a desktop Chrome
navigation: modern UA, ``Sec-Fetch-*``, HTTP/2 when available, retries with
backoff when the first response is a known "empty shell."

This does **not** claim to defeat every anti-bot system. It closes the gap
between "works in incognito" and "fails in our plugin" for the common case.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

# Keep in sync with a current desktop Chrome. Override via CAIRN_USER_AGENT.
DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_SHELL_TITLES = frozenset(
    {
        "",
        "instagram",
        "x",
        "twitter",
        "tiktok",
        "reddit",
        "youtube",
        "just a moment...",  # cloudflare
        "attention required! | cloudflare",
        "access denied",
    }
)


def browser_headers(
    *,
    user_agent: str | None = None,
    referer: str | None = None,
    accept: str | None = None,
) -> dict[str, str]:
    """Headers that resemble a top-level document navigation in Chrome."""
    h: dict[str, str] = {
        "User-Agent": user_agent or DEFAULT_BROWSER_UA,
        "Accept": accept
        or (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "same-origin",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
    }
    if referer:
        h["Referer"] = referer
    return h


def browser_headers_json(
    *,
    user_agent: str | None = None,
    referer: str | None = None,
) -> dict[str, str]:
    """Headers for XHR/fetch-style JSON endpoints."""
    h = browser_headers(user_agent=user_agent, referer=referer)
    h["Accept"] = "application/json, text/plain, */*"
    h["Sec-Fetch-Dest"] = "empty"
    h["Sec-Fetch-Mode"] = "cors"
    h["Sec-Fetch-Site"] = "same-origin" if referer else "cross-site"
    h.pop("Upgrade-Insecure-Requests", None)
    h.pop("Sec-Fetch-User", None)
    return h


def make_browser_client(
    *,
    timeout: float = 30.0,
    proxy: str | None = None,
    user_agent: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.AsyncClient:
    """Build the shared session client used by plugins."""
    base = browser_headers(user_agent=user_agent)
    if headers:
        base.update(dict(headers))
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "headers": base,
        "follow_redirects": True,
        "http2": True,
    }
    if proxy:
        kwargs["proxy"] = proxy
    try:
        return httpx.AsyncClient(**kwargs)
    except Exception:
        # httpx without http2 extra — fall back.
        kwargs.pop("http2", None)
        return httpx.AsyncClient(**kwargs)


def html_title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", _unescape(m.group(1))).strip()


def og_content(text: str, prop: str) -> str | None:
    # property= then name= variants
    for attr in ("property", "name"):
        m = re.search(
            rf'<meta[^>]+{attr}=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
            text,
            re.I | re.S,
        )
        if not m:
            m = re.search(
                rf'<meta[^>]+content=["\'](.*?)["\'][^>]+{attr}=["\']{re.escape(prop)}["\']',
                text,
                re.I | re.S,
            )
        if m:
            return _unescape(m.group(1)).strip()
    return None


def _unescape(s: str) -> str:
    import html as _html

    return _html.unescape(s.replace("&#064;", "@"))


def looks_like_empty_shell(text: str, *, min_len: int = 2000) -> bool:
    """Heuristic: SPA shell / challenge page without useful profile metadata."""
    if not text:
        return True
    title = html_title(text).lower()
    ogt = (og_content(text, "og:title") or "").lower()
    ogd = og_content(text, "og:description") or ""
    # Real profile pages usually carry (@handle) or a non-brand og:description.
    if "(@" in title or "(@" in ogt or (ogd and ogt and ogt not in _SHELL_TITLES):
        return False
    if len(text) < 400:
        return True
    # Brand title only, no useful og tags → shell (even if HTML is large).
    if (
        title in _SHELL_TITLES
        and not ogd
        and (len(text) < min_len or not ogt or ogt in _SHELL_TITLES or ogt == title)
    ):
        return True
    return "just a moment" in title or "cf-browser-verification" in text.lower()


async def resilient_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    retries: int = 3,
    retry_statuses: Sequence[int] = (429, 503, 502, 520, 521, 522, 523, 524),
    empty_shell_retry: bool = True,
    is_empty: Callable[[str], bool] | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    """GET with backoff on rate limits and empty JS shells.

    Empty-shell retries address the flaky case where Instagram (etc.) sometimes
    returns a full og-tagged profile and sometimes a bare ``<title>Instagram</title>``
    shell to the same client.
    """
    empty_fn = is_empty or looks_like_empty_shell
    last: httpx.Response | None = None
    req_headers = dict(headers) if headers else None

    for attempt in range(max(1, retries)):
        kwargs: dict[str, Any] = {}
        if req_headers is not None:
            kwargs["headers"] = req_headers
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            last = await client.get(url, **kwargs)
        except httpx.HTTPError:
            if attempt + 1 >= retries:
                raise
            await asyncio.sleep(0.4 * (2**attempt) + random.uniform(0, 0.3))
            continue

        if last.status_code in retry_statuses:
            await asyncio.sleep(0.6 * (2**attempt) + random.uniform(0, 0.4))
            continue

        ctype = (last.headers.get("content-type") or "").lower()
        if (
            empty_shell_retry
            and last.status_code == 200
            and "html" in ctype
            and empty_fn(last.text)
            and attempt + 1 < retries
        ):
            await asyncio.sleep(0.5 * (2**attempt) + random.uniform(0.1, 0.5))
            continue

        return last

    assert last is not None
    return last
