"""scrape_url — fetch a URL and return clean text, links, and images (free).

The "read the page" primitive the investigator needs after a search: given a URL
(found via ``web_search`` or supplied directly), return the page title, its
visible text, the links it contains, and its image URLs (incl. the profile
picture via ``og:image``). Entities (emails, usernames, domains, …) are mined
from the text and links so the agent can pivot.

**Backends (free-first):**
- crawl4ai (open-source) — used automatically when installed (``uv sync --extra
  crawl``); renders JavaScript, so it works for JS-heavy social pages.
- httpx + BeautifulSoup (default) — no extra deps; static HTML only.

No paid backend by design (Bright Data Web Unlocker is deliberately excluded).
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup
from pydantic import Field

from cairn.core.entities import extract_entities
from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput
from cairn.execution.http_util import http_client

try:  # optional JS-rendering backend (open-source, free)
    from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]
    _HAS_CRAWL4AI = True
except Exception:  # pragma: no cover - optional dep absent
    AsyncWebCrawler = None  # type: ignore[assignment]
    _HAS_CRAWL4AI = False

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_MAX_TEXT = 8000  # bound what we surface to the model


class ScrapeUrlInput(PluginInput):
    """``target`` is the URL to fetch."""

    #: render JS via crawl4ai if installed (auto-on when available).
    render_js: bool = True


class ScrapeUrlOutput(PluginOutput):
    backend: str = ""
    title: str = ""
    text: str = ""
    links: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)


class ScrapeUrlPlugin(BasePlugin[ScrapeUrlInput, ScrapeUrlOutput]):
    name = "scrape_url"
    category = "web"
    requires_key = None
    input_model = ScrapeUrlInput
    output_model = ScrapeUrlOutput

    __doc__ = (
        "Fetch a URL (target) and return its title, visible text, links, and image URLs "
        "(incl. profile picture via og:image). Free httpx+BeautifulSoup by default; renders JS "
        "via crawl4ai automatically when installed. Mines entities for pivoting."
    )

    async def run(self, inp: ScrapeUrlInput, ctx: PluginContext) -> ScrapeUrlOutput:
        url = inp.target.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        async with http_client(ctx) as http:
            if _HAS_CRAWL4AI and inp.render_js:
                try:
                    out = await _crawl4ai(url, ctx)
                    if out is not None:
                        return out
                except Exception:  # pragma: no cover - fall back to static fetch
                    pass
            return await _static(http, url, ctx)


async def _crawl4ai(url: str, ctx: PluginContext) -> ScrapeUrlOutput | None:  # pragma: no cover
    assert AsyncWebCrawler is not None
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
    md = getattr(result, "markdown", "") or ""
    if not md:
        return None
    title = md.strip().splitlines()[0][:300] if md.strip() else ""
    text = md[:_MAX_TEXT]
    out = ScrapeUrlOutput(
        source="scrape_url", backend="crawl4ai", title=title, text=text, links=[], images=[]
    )
    out.summary_markdown = _summary(url, out)
    out.entities = _entities(text)
    return out


async def _static(http: httpx.AsyncClient, url: str, ctx: PluginContext) -> ScrapeUrlOutput:
    r = await http.get(url, headers={"User-Agent": _BROWSER_UA})
    if r.status_code >= 400:
        return ScrapeUrlOutput(
            source="scrape_url",
            backend="httpx",
            summary_markdown=f"**{url}** — fetch failed (HTTP {r.status_code}).",
            entities=[Entity(type="url", value=url)],
        )
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = soup.get_text(" ", strip=True)
    og_image = _meta(soup, "og:image")
    links = sorted(
        {str(a["href"]) for a in soup.select("a[href]") if str(a["href"]).startswith("http")}
    )
    images = sorted({str(i.get("src", "")) for i in soup.select("img[src]") if i.get("src")})
    if og_image:
        images = [og_image, *images]

    out = ScrapeUrlOutput(
        source="scrape_url",
        backend="httpx",
        title=title,
        text=text[:_MAX_TEXT],
        links=links[:100],
        images=images[:50],
    )
    out.summary_markdown = _summary(url, out)
    out.entities = _entities(text + "\n" + "\n".join(links))
    return out


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return tag.get("content") if tag and tag.get("content") else None


def _summary(url: str, out: ScrapeUrlOutput) -> str:
    head = out.title or "(no title)"
    preview = out.text[:600].replace("\n", " ")
    lines = [
        f"**{url}** — scraped [{out.backend}]",
        f"- Title: {head}",
        f"- Links: {len(out.links)} | Images: {len(out.images)}",
        f"- Text: {preview}{'…' if len(out.text) > 600 else ''}",
    ]
    if out.images:
        lines.append(f"- Image(s): {', '.join(out.images[:3])}")
    return "\n".join(lines)


def _entities(text: str) -> list[Entity]:
    seen: set[tuple[str, str]] = set()
    ents: list[Entity] = []
    for ex in extract_entities(text):
        key = (ex.type, ex.value.lower())
        if key in seen:
            continue
        seen.add(key)
        ents.append(Entity(type=ex.type, value=ex.value))
    return ents
