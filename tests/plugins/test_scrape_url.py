"""scrape_url plugin (static httpx path mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.web.scrape_url import ScrapeUrlInput, ScrapeUrlPlugin

_HTML = """<!doctype html>
<html><head>
  <title>Jane Doe — Personal Site</title>
  <meta property="og:image" content="https://example.com/jane/avatar.jpg">
</head><body>
  <p>Reach me at janedoe@example.com or visit my projects.</p>
  <a href="https://github.com/janedoe">GitHub</a>
  <img src="/static/photo.png">
</body></html>"""


@respx.mock
async def test_scrape_static_extracts_title_links_images_entities():
    respx.get("https://example.com/jane").mock(return_value=httpx.Response(200, text=_HTML))
    out = await ScrapeUrlPlugin().run(
        # render_js=False forces the deterministic static path even if crawl4ai is installed
        ScrapeUrlInput(target="https://example.com/jane", render_js=False),
        PluginContext(http=None),
    )
    assert out.backend == "httpx"
    assert out.title == "Jane Doe — Personal Site"
    assert "https://github.com/janedoe" in out.links
    # og:image promoted to front of the image list
    assert out.images[0] == "https://example.com/jane/avatar.jpg"
    assert "/static/photo.png" in out.images
    assert "janedoe@example.com" in out.text
    # email mined as an entity for pivoting
    tv = {(e.type, e.value.lower()) for e in out.entities}
    assert ("email", "janedoe@example.com") in tv
    assert "scraped" in out.summary_markdown


@respx.mock
async def test_scrape_http_error_is_clean():
    respx.get("https://example.com/missing").mock(return_value=httpx.Response(404))
    out = await ScrapeUrlPlugin().run(
        ScrapeUrlInput(target="https://example.com/missing", render_js=False),
        PluginContext(http=None),
    )
    assert "404" in out.summary_markdown


async def test_scrape_adds_scheme_to_bare_target():
    # monkeypatch the network call: just assert the URL normalization path doesn't blow up
    import cairn.plugins.web.scrape_url as mod

    async def fake_static(http, url, ctx):
        return mod.ScrapeUrlOutput(
            source="scrape_url", backend="httpx", summary_markdown=f"ok {url}"
        )

    orig = mod._static
    mod._static = fake_static
    try:
        out = await ScrapeUrlPlugin().run(
            ScrapeUrlInput(target="example.com/path", render_js=False),
            PluginContext(http=None),
        )
        assert "https://example.com/path" in out.summary_markdown
    finally:
        mod._static = orig


async def test_scrape_summary_redacts_userinfo_from_image_urls():
    # issue #32: image URLs in the summary must not surface user:pass@host to the
    # model (the summary is wrapped but NOT redacted).
    from cairn.plugins.web.scrape_url import ScrapeUrlOutput, _summary

    out = ScrapeUrlOutput(
        source="scrape_url",
        backend="httpx",
        title="t",
        text="hello",
        links=[],
        images=["http://u:p@cdn.example/a.jpg"],
    )
    summary = _summary("https://example.com", out)
    assert "u:p@" not in summary
    assert "cdn.example/a.jpg" in summary  # path kept, credentials stripped
