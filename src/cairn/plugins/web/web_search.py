"""web_search — run a live web search query (free-first, pluggable backend).

The engine that makes dorks *do* something: given a query (often a dork like
``site:instagram.com "username"``), return real search results — titles, URLs,
snippets — plus any entities (domains, URLs, emails) mined from them for
pivoting.

**Backends (auto-selected, cheapest/free first):**
- Brave Search — used automatically when ``CAIRN_BRAVE_KEY`` is set. **This is
  the reliable path** (free tier, 2k/mo, no anti-bot walls). Strongly
  recommended: https://api.search.brave.com/
- DuckDuckGo HTML (no-key fallback) — free, but DDG increasingly returns an
  anti-bot **202 interstitial** instead of results. When that happens, the tool
  returns *no results* with an actionable message pointing to Brave — never a
  silent failure or fabricated hits.

Reality (2026): free no-key search is blocked by anti-bot on DDG/Google/Bing and
SearXNG public instances are unreliable. A free Brave key is the practical fix.

No paid backend by design. (Bright Data / SerpAPI are deliberately excluded.)
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from cairn.core.entities import extract_entities
from cairn.core.provenance import Confidence, Provenance
from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)
from cairn.execution.http_util import http_client

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


class WebSearchInput(PluginInput):
    """``target`` is a full search query (dorks welcome), e.g. ``site:reddit.com "jdoe"``."""

    limit: int = 8


class WebSearchOutput(PluginOutput):
    backend: str = ""
    results: list[SearchResult] = Field(default_factory=list)


class WebSearchPlugin(BasePlugin[WebSearchInput, WebSearchOutput]):
    name = "web_search"
    category = "web"
    requires_key = None  # always available (DDG fallback); brave auto-used if key set
    input_model = WebSearchInput
    output_model = WebSearchOutput
    cost = CostSpec(unit="queries/mo", monthly_quota=2000, note="DDG free (anti-bot) · Brave 2k/mo")

    __doc__ = (
        "Run a live web search (target = query, dorks supported like site:instagram.com \"user\"). "
        "Free DuckDuckGo by default; auto-upgrades to Brave if CAIRN_BRAVE_KEY is set. Returns "
        "titles/URLs/snippets + mined entities for pivoting."
    )

    async def run(self, inp: WebSearchInput, ctx: PluginContext) -> WebSearchOutput:
        async with http_client(ctx) as http:
            brave = ctx.key("brave")
            if brave:
                results, backend = await _brave(http, inp.target, inp.limit, brave, ctx)
            else:
                results, backend = await _ddg(http, inp.target, inp.limit, ctx)

            out = WebSearchOutput(source=self.name, backend=backend, results=results)
            out.summary_markdown = _summary(inp.target, out)
            out.entities = _entities(results)
            return out


async def _ddg(
    http: httpx.AsyncClient, query: str, limit: int, ctx: PluginContext
) -> tuple[list[SearchResult], str]:
    r = await http.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": _BROWSER_UA, "Referer": "https://duckduckgo.com/"},
    )
    # 202 = DDG anti-bot interstitial (a page with no result__a links). Common in
    # 2026; treat it as "blocked", not "no results", so the summary can advise.
    if r.status_code == 202:
        return [], "duckduckgo-blocked"
    if r.status_code != 200 or not r.text:
        return [], f"duckduckgo (HTTP {r.status_code})"
    soup = BeautifulSoup(r.text, "html.parser")
    results: list[SearchResult] = []
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        url = _unwrap_ddg(href)
        if not url:
            continue
        title = a.get_text(strip=True)
        snippet = ""
        # snippet usually follows in the same result block
        block = a.find_parent("div", class_="result") or a.find_parent("div")
        if block:
            snip = block.select_one(".result__snippet")
            snippet = snip.get_text(" ", strip=True) if snip else ""
        results.append(SearchResult(title=title or url, url=url, snippet=snippet))
        if len(results) >= limit:
            break
    return results, "duckduckgo"


async def _brave(
    http: httpx.AsyncClient, query: str, limit: int, token: str, ctx: PluginContext
) -> tuple[list[SearchResult], str]:
    r = await http.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": min(max(limit, 1), 20)},
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": token,
            "User-Agent": ctx.user_agent,
        },
    )
    if r.status_code != 200:
        return [], f"brave (HTTP {r.status_code})"
    data = r.json() if r.text else {}
    web = data.get("web", {}) or {}
    results: list[SearchResult] = []
    for item in (web.get("results") or [])[:limit]:
        results.append(
            SearchResult(
                title=item.get("title", "") or item.get("url", ""),
                url=item.get("url", ""),
                snippet=item.get("description", "") or "",
            )
        )
    return results, "brave"


def _unwrap_ddg(href: str) -> str:
    """DDG wraps result URLs in //duckduckgo.com/l/?uddg=<encoded>; unwrap."""
    h = href if href.startswith("http") else f"https:{href}" if href.startswith("//") else href
    parsed = urlparse(h)
    if "duckduckgo.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return h


def _summary(query: str, out: WebSearchOutput) -> str:
    if not out.results:
        if out.backend == "duckduckgo-blocked":
            return (
                f"**{query}** — web search is unavailable. DuckDuckGo is blocking "
                "automated requests (anti-bot, HTTP 202). For reliable search, get a "
                "FREE Brave Search API key (2,000 queries/month) at "
                "https://api.search.brave.com/ and set CAIRN_BRAVE_KEY."
            )
        hint = (
            " (Set CAIRN_BRAVE_KEY for reliable search.)"
            if out.backend.startswith("duckduckgo")
            else ""
        )
        return f"**{query}** — no results via {out.backend}.{hint}"
    lines = [f"**{query}** — {len(out.results)} result(s) [{out.backend}]:"]
    for res in out.results:
        lines.append(f"- [{res.title}]({res.url})")
        if res.snippet:
            lines.append(f"    {res.snippet[:200]}")
    return "\n".join(lines)


def _entities(results: list[SearchResult]) -> list[Entity]:
    blob = "\n".join(f"{r.title}\n{r.url}\n{r.snippet}" for r in results)
    ents: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    for ex in extract_entities(blob):
        key = (ex.type, ex.value.lower())
        if key in seen:
            continue
        seen.add(key)
        ents.append(
            Entity(
                type=ex.type,
                value=ex.value,
                confidence=Confidence.TENTATIVE,
                provenance=Provenance(tool="web_search"),
            )
        )
    return ents
