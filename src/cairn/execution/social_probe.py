"""First-party username probes — no third-party mirrors.

Sherlock is useful as a wide net, but several of its high-value sites use
``urlProbe`` hosts that are not the real platform (e.g. Instagram → imginn.com,
Twitter → nitter forks). Those probes go stale and produce false negatives
while a normal browser (even incognito) still loads the real profile.

This module checks the **first-party** URL with browser-like HTTP and explicit
existence heuristics. Used by the ``username_check`` plugin and to cross-check
Sherlock hits/misses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

import httpx

from cairn.execution.browser_http import (
    browser_headers,
    browser_headers_json,
    html_title,
    looks_like_empty_shell,
    og_content,
    resilient_get,
)

Status = Literal["found", "not_found", "unknown", "error"]


@dataclass(frozen=True)
class ProbeResult:
    platform: str
    username: str
    status: Status
    url: str
    display_name: str | None = None
    bio: str | None = None
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.status == "found"


ProbeFn = Callable[[httpx.AsyncClient, str], Awaitable[ProbeResult]]


def _user_ok(username: str) -> str:
    u = username.strip().lstrip("@")
    if not u or any(c.isspace() for c in u):
        raise ValueError(f"invalid username: {username!r}")
    return u


async def _get_html(
    client: httpx.AsyncClient, url: str, *, retries: int = 3
) -> httpx.Response:
    return await resilient_get(
        client,
        url,
        headers=browser_headers(),
        retries=retries,
        empty_shell_retry=True,
    )


async def probe_instagram(client: httpx.AsyncClient, username: str) -> ProbeResult:
    u = _user_ok(username)
    url = f"https://www.instagram.com/{quote(u)}/"
    try:
        r = await _get_html(client, url, retries=4)
    except httpx.HTTPError as exc:
        return ProbeResult("instagram", u, "error", url, detail=str(exc))

    if r.status_code == 404:
        return ProbeResult("instagram", u, "not_found", url, detail="HTTP 404")

    text = r.text or ""
    title = html_title(text)
    ogt = og_content(text, "og:title") or ""
    ogd = og_content(text, "og:description") or ""
    combined = f"{title}\n{ogt}\n{ogd}"

    # Positive: "lewis he (@roowus) • Instagram photos and videos"
    if re.search(rf"\(@{re.escape(u)}\)", combined, re.I):
        disp = ogt or title
        disp = re.sub(r"\s*[•·].*$", "", disp).strip()
        disp = re.sub(rf"\s*\(@{re.escape(u)}\)\s*", " ", disp, flags=re.I).strip()
        return ProbeResult(
            "instagram",
            u,
            "found",
            url,
            display_name=disp or None,
            bio=ogd or None,
            detail="og/title match for (@username)",
            evidence={"title": title, "og:title": ogt, "og:description": ogd},
        )

    if re.search(r"sorry,? this page|page isn't available|user not found", text, re.I):
        return ProbeResult("instagram", u, "not_found", url, detail="not-available copy")

    if looks_like_empty_shell(text) or (title.lower() in {"", "instagram"} and not ogd):
        return ProbeResult(
            "instagram",
            u,
            "unknown",
            url,
            detail="empty shell / no profile markers (retry later or use browser)",
            evidence={"title": title, "status_code": r.status_code, "len": len(text)},
        )

    return ProbeResult(
        "instagram",
        u,
        "unknown",
        url,
        detail="page loaded but no definitive exists/not-exists signal",
        evidence={"title": title, "og:title": ogt},
    )


async def probe_github(client: httpx.AsyncClient, username: str) -> ProbeResult:
    u = _user_ok(username)
    url = f"https://api.github.com/users/{quote(u)}"
    profile = f"https://github.com/{u}"
    try:
        r = await resilient_get(
            client,
            url,
            headers={
                **browser_headers_json(),
                "Accept": "application/vnd.github+json",
            },
            retries=2,
            empty_shell_retry=False,
        )
    except httpx.HTTPError as exc:
        return ProbeResult("github", u, "error", profile, detail=str(exc))

    if r.status_code == 404:
        return ProbeResult("github", u, "not_found", profile, detail="API 404")
    if r.status_code == 200:
        data = r.json()
        return ProbeResult(
            "github",
            u,
            "found",
            profile,
            display_name=data.get("name") or data.get("login"),
            bio=data.get("bio"),
            detail="GitHub REST API",
            evidence={
                "id": data.get("id"),
                "public_repos": data.get("public_repos"),
                "followers": data.get("followers"),
            },
        )
    return ProbeResult("github", u, "unknown", profile, detail=f"API HTTP {r.status_code}")


async def probe_reddit(client: httpx.AsyncClient, username: str) -> ProbeResult:
    u = _user_ok(username)
    url = f"https://www.reddit.com/user/{quote(u)}/about.json"
    profile = f"https://www.reddit.com/user/{u}/"
    try:
        r = await resilient_get(
            client,
            url,
            headers={
                **browser_headers_json(referer="https://www.reddit.com/"),
                "Accept": "application/json",
            },
            retries=3,
            empty_shell_retry=False,
        )
    except httpx.HTTPError as exc:
        return ProbeResult("reddit", u, "error", profile, detail=str(exc))

    if r.status_code == 404:
        return ProbeResult("reddit", u, "not_found", profile, detail="HTTP 404")
    if r.status_code != 200:
        return ProbeResult("reddit", u, "unknown", profile, detail=f"HTTP {r.status_code}")
    try:
        data = r.json()
    except json.JSONDecodeError:
        return ProbeResult("reddit", u, "unknown", profile, detail="non-JSON body")
    if data.get("error") == 404 or data.get("message") == "Not Found":
        return ProbeResult("reddit", u, "not_found", profile)
    d = data.get("data") or {}
    if d.get("name") or d.get("id"):
        return ProbeResult(
            "reddit",
            u,
            "found",
            profile,
            display_name=d.get("subreddit", {}).get("title") or d.get("name"),
            bio=(d.get("subreddit") or {}).get("public_description"),
            detail="reddit about.json",
            evidence={"total_karma": d.get("total_karma"), "created": d.get("created_utc")},
        )
    return ProbeResult("reddit", u, "unknown", profile, detail="unexpected JSON shape")


async def probe_youtube(client: httpx.AsyncClient, username: str) -> ProbeResult:
    u = _user_ok(username)
    url = f"https://www.youtube.com/@{quote(u)}"
    try:
        r = await _get_html(client, url, retries=3)
    except httpx.HTTPError as exc:
        return ProbeResult("youtube", u, "error", url, detail=str(exc))
    if r.status_code == 404:
        return ProbeResult("youtube", u, "not_found", url, detail="HTTP 404")
    text = r.text or ""
    title = html_title(text)
    if re.search(r"this page isn.?t available|404", title, re.I):
        return ProbeResult("youtube", u, "not_found", url, detail=title)
    if "youtube" in title.lower() and ("@" in title or len(title) > 12):
        if "404" in text[:2000]:
            return ProbeResult("youtube", u, "not_found", url)
        return ProbeResult(
            "youtube",
            u,
            "found",
            url,
            display_name=title.replace("- YouTube", "").strip() or None,
            detail="channel page title",
            evidence={"title": title},
        )
    ogt = og_content(text, "og:title")
    if ogt and "youtube" not in ogt.lower():
        return ProbeResult("youtube", u, "found", url, display_name=ogt, detail="og:title")
    if looks_like_empty_shell(text):
        return ProbeResult("youtube", u, "unknown", url, detail="empty shell")
    return ProbeResult("youtube", u, "unknown", url, detail=f"title={title!r}")


async def probe_tiktok(client: httpx.AsyncClient, username: str) -> ProbeResult:
    u = _user_ok(username)
    url = f"https://www.tiktok.com/@{quote(u)}"
    try:
        r = await _get_html(client, url, retries=3)
    except httpx.HTTPError as exc:
        return ProbeResult("tiktok", u, "error", url, detail=str(exc))
    if r.status_code == 404:
        return ProbeResult("tiktok", u, "not_found", url)
    text = r.text or ""
    title = html_title(text)
    ogt = og_content(text, "og:title") or ""
    ogd = og_content(text, "og:description") or ""
    blob = f"{title} {ogt} {ogd}"
    if re.search(r"couldn.?t find this account|page not available", blob, re.I):
        return ProbeResult("tiktok", u, "not_found", url, detail=blob[:120])
    if re.search(rf"@{re.escape(u)}", blob, re.I) or (ogt and "tiktok" in title.lower()):
        return ProbeResult(
            "tiktok",
            u,
            "found",
            url,
            display_name=ogt or title,
            bio=ogd or None,
            detail="og/title",
            evidence={"title": title, "og:title": ogt},
        )
    if looks_like_empty_shell(text):
        return ProbeResult("tiktok", u, "unknown", url, detail="empty shell")
    return ProbeResult("tiktok", u, "unknown", url, detail=f"title={title!r}")


async def probe_x(client: httpx.AsyncClient, username: str) -> ProbeResult:
    """Best-effort logged-out X/Twitter check (often unknown without cookies)."""
    u = _user_ok(username)
    url = f"https://x.com/{quote(u)}"
    try:
        r = await _get_html(client, url, retries=3)
    except httpx.HTTPError as exc:
        return ProbeResult("x", u, "error", url, detail=str(exc))
    text = r.text or ""
    title = html_title(text)
    ogt = og_content(text, "og:title") or ""
    if re.search(r"this account (doesn.?t|does not) exist", text, re.I):
        return ProbeResult("x", u, "not_found", url)
    if re.search(rf"\(@{re.escape(u)}\)", f"{title} {ogt}", re.I):
        return ProbeResult(
            "x", u, "found", url, display_name=ogt or title, detail="og/title (@user)"
        )
    if "something went wrong" in title.lower():
        return ProbeResult("x", u, "unknown", url, detail=title)
    return ProbeResult(
        "x",
        u,
        "unknown",
        url,
        detail="logged-out X rarely exposes definitive signals; cookie session later",
        evidence={"title": title},
    )


async def probe_threads(client: httpx.AsyncClient, username: str) -> ProbeResult:
    u = _user_ok(username)
    url = f"https://www.threads.net/@{quote(u)}"
    try:
        r = await _get_html(client, url, retries=3)
    except httpx.HTTPError as exc:
        return ProbeResult("threads", u, "error", url, detail=str(exc))
    if r.status_code == 404:
        return ProbeResult("threads", u, "not_found", url)
    text = r.text or ""
    title = html_title(text)
    ogt = og_content(text, "og:title") or ""
    if re.search(rf"@{re.escape(u)}", f"{title} {ogt}", re.I):
        return ProbeResult(
            "threads", u, "found", url, display_name=ogt or title, detail="og/title"
        )
    if re.search(r"page not found|content not found", f"{title} {text[:1500]}", re.I):
        return ProbeResult("threads", u, "not_found", url)
    if looks_like_empty_shell(text):
        return ProbeResult("threads", u, "unknown", url, detail="empty shell")
    return ProbeResult("threads", u, "unknown", url, detail=f"title={title!r}")


# Platforms Sherlock often gets wrong via third-party urlProbe — always prefer these.
FIRST_PARTY_PROBES: dict[str, ProbeFn] = {
    "instagram": probe_instagram,
    "github": probe_github,
    "reddit": probe_reddit,
    "youtube": probe_youtube,
    "tiktok": probe_tiktok,
    "x": probe_x,
    "twitter": probe_x,
    "threads": probe_threads,
}

DEFAULT_PLATFORMS: tuple[str, ...] = (
    "instagram",
    "github",
    "reddit",
    "youtube",
    "tiktok",
    "x",
    "threads",
)


async def probe_platform(
    client: httpx.AsyncClient, platform: str, username: str
) -> ProbeResult:
    key = platform.strip().lower()
    fn = FIRST_PARTY_PROBES.get(key)
    if fn is None:
        return ProbeResult(
            key,
            username,
            "error",
            "",
            detail=f"no first-party probe registered for {platform!r}",
        )
    return await fn(client, username)


async def probe_many(
    client: httpx.AsyncClient,
    username: str,
    platforms: Sequence[str] | None = None,
) -> list[ProbeResult]:
    plats = list(platforms) if platforms else list(DEFAULT_PLATFORMS)
    seen: set[str] = set()
    out: list[ProbeResult] = []
    for p in plats:
        k = "x" if p.lower() in {"x", "twitter"} else p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(await probe_platform(client, k, username))
    return out
