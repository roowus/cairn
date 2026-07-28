"""web_search plugin (DDG + Brave mocked)."""

from __future__ import annotations

import httpx
import respx
from pydantic import SecretStr

from cairn.execution.base import PluginContext
from cairn.plugins.web.web_search import WebSearchInput, WebSearchPlugin

_DDG_HTML = """
<div class="result">
  <a class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fjanedoe">Jane Doe Profile</a>
  <a class="result__snippet">contact janedoe@example.com on her page</a>
</div>
<div class="result">
  <a class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fjanedoe">janedoe (GitHub)</a>
  <a class="result__snippet">open-source contributor</a>
</div>
"""


@respx.mock
async def test_ddg_parses_unwraps_and_mines_entities():
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_DDG_HTML)
    )
    out = await WebSearchPlugin().run(
        WebSearchInput(target='site:instagram.com "janedoe"'), PluginContext(http=None)
    )
    assert out.backend == "duckduckgo"
    urls = {r.url for r in out.results}
    assert "https://example.com/janedoe" in urls
    assert "https://github.com/janedoe" in urls
    assert any(r.title == "Jane Doe Profile" for r in out.results)
    # entity mined from snippets
    tv = {(e.type, e.value.lower()) for e in out.entities}
    assert ("email", "janedoe@example.com") in tv


@respx.mock
async def test_ddg_empty_is_clean():
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text="<html><body>no results</body></html>")
    )
    out = await WebSearchPlugin().run(
        WebSearchInput(target="zzz-none"), PluginContext(http=None)
    )
    assert out.results == []
    assert "no results" in out.summary_markdown
    assert "duckduckgo" in out.backend


@respx.mock
async def test_ddg_blocked_202_is_actionable():
    # DDG anti-bot interstitial → no results, but an actionable Brave message
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(202, text="<html>anonymously</html>")
    )
    out = await WebSearchPlugin().run(
        WebSearchInput(target="lewishelh"), PluginContext(http=None)
    )
    assert out.results == []
    assert out.backend == "duckduckgo-blocked"
    assert "CAIRN_BRAVE_KEY" in out.summary_markdown
    assert "blocking" in out.summary_markdown.lower()


@respx.mock
async def test_brave_used_when_key_present():
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"title": "Jane Doe", "url": "https://example.com/jane",
                         "description": "a profile"}
                    ]
                }
            },
        )
    )
    ctx = PluginContext(http=None, keys={"brave": SecretStr("tok")})
    out = await WebSearchPlugin().run(WebSearchInput(target="janedoe"), ctx)
    assert out.backend == "brave"
    assert out.results[0].title == "Jane Doe"
    assert out.results[0].snippet == "a profile"
