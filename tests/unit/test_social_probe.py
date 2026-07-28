"""First-party social probes (mocked HTTP)."""

from __future__ import annotations

import httpx
import pytest
import respx

from cairn.execution.social_probe import (
    probe_github,
    probe_instagram,
    probe_many,
    probe_reddit,
)


@respx.mock
@pytest.mark.asyncio
async def test_instagram_found_via_og_title():
    html = """
    <html><head>
      <title>lewis he (@roowus) • Instagram photos and videos</title>
      <meta property="og:title" content="lewis he (@roowus) • Instagram photos and videos"/>
      <meta property="og:description" content="690 Followers, 714 Following, 1 Posts"/>
    </head><body>profile</body></html>
    """
    respx.get("https://www.instagram.com/roowus/").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    async with httpx.AsyncClient() as client:
        r = await probe_instagram(client, "roowus")
    assert r.status == "found"
    assert r.display_name and "lewis" in r.display_name.lower()
    assert "690" in (r.bio or "")


@respx.mock
@pytest.mark.asyncio
async def test_instagram_empty_shell_is_unknown_not_missing():
    shell = "<html><head><title>Instagram</title></head><body>" + ("z" * 800) + "</body></html>"
    respx.get("https://www.instagram.com/missinguser/").mock(
        return_value=httpx.Response(200, text=shell, headers={"content-type": "text/html"})
    )
    async with httpx.AsyncClient() as client:
        r = await probe_instagram(client, "missinguser")
    assert r.status == "unknown"  # never false-negative a shell as not_found


@respx.mock
@pytest.mark.asyncio
async def test_github_api_found_and_missing():
    respx.get("https://api.github.com/users/torvalds").mock(
        return_value=httpx.Response(200, json={"login": "torvalds", "name": "Linus", "bio": "x"})
    )
    respx.get("https://api.github.com/users/nope-nope-nope").mock(
        return_value=httpx.Response(404)
    )
    async with httpx.AsyncClient() as client:
        ok = await probe_github(client, "torvalds")
        missing = await probe_github(client, "nope-nope-nope")
    assert ok.status == "found" and ok.display_name == "Linus"
    assert missing.status == "not_found"


@respx.mock
@pytest.mark.asyncio
async def test_reddit_about_json():
    respx.get("https://www.reddit.com/user/spez/about.json").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"name": "spez", "id": "1", "subreddit": {"title": "spez"}}},
        )
    )
    async with httpx.AsyncClient() as client:
        r = await probe_reddit(client, "spez")
    assert r.status == "found"


@respx.mock
@pytest.mark.asyncio
async def test_probe_many_dedupes_twitter_x():
    respx.get(url__regex=r"https://api\.github\.com/users/.*").mock(
        return_value=httpx.Response(404)
    )
    respx.get(url__regex=r"https://www\.instagram\.com/.*").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>Instagram</title></head></html>",
            headers={"content-type": "text/html"},
        )
    )
    respx.get(url__regex=r"https://www\.reddit\.com/.*").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://www\.youtube\.com/.*").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://www\.tiktok\.com/.*").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://x\.com/.*").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>X</title></head></html>",
            headers={"content-type": "text/html"},
        )
    )
    respx.get(url__regex=r"https://www\.threads\.net/.*").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        rows = await probe_many(client, "someone", ["twitter", "x", "github"])
    plats = [r.platform for r in rows]
    assert plats.count("x") == 1
    assert "twitter" not in plats
