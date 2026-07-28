"""Browser-like HTTP helpers."""

from __future__ import annotations

from cairn.execution.browser_http import (
    browser_headers,
    html_title,
    looks_like_empty_shell,
    og_content,
)


def test_browser_headers_look_like_chrome_navigation():
    h = browser_headers()
    assert "Chrome/" in h["User-Agent"]
    assert h["Sec-Fetch-Mode"] == "navigate"
    assert "text/html" in h["Accept"]


def test_html_title_and_og():
    html = """
    <html><head>
      <title>lewis he (@roowus) • Instagram photos and videos</title>
      <meta property="og:title" content="lewis he (@roowus) • Instagram photos and videos" />
      <meta property="og:description" content="690 Followers, 714 Following, 1 Posts" />
    </head></html>
    """
    assert "roowus" in html_title(html)
    assert og_content(html, "og:title") and "roowus" in og_content(html, "og:title")
    assert "690" in (og_content(html, "og:description") or "")
    assert not looks_like_empty_shell(html)


def test_empty_shell_detection():
    shell = "<html><head><title>Instagram</title></head><body>" + ("x" * 500) + "</body></html>"
    assert looks_like_empty_shell(shell)
    assert looks_like_empty_shell("")
