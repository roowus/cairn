"""generate_dorks plugin (offline string generation)."""

from __future__ import annotations

from cairn.execution.base import PluginContext
from cairn.plugins.identity.generate_dorks import (
    GenerateDorksInput,
    GenerateDorksPlugin,
    _build_dorks,
)


async def test_build_dorks_covers_sites_and_operators():
    dorks = _build_dorks("janedoe", site_dorks=True, extra="")
    blob = "\n".join(dorks)
    assert 'site:instagram.com' in blob
    assert 'site:github.com' in blob
    assert 'filetype:pdf' in blob
    assert 'resume OR cv' in blob
    assert 'leaked OR breach' in blob
    # every query is scoped to the quoted target
    assert all('"janedoe"' in d for d in dorks if d.startswith('"'))


async def test_build_dorks_appends_extra_terms():
    dorks = _build_dorks("janedoe", site_dorks=False, extra="email phone")
    assert dorks  # site-less dorks still produced
    # every query-scoped dork (those starting with the quoted target) carries
    # the extra terms; the lone `intitle:` dork intentionally does not.
    q_dorks = [d for d in dorks if d.startswith('"')]
    assert q_dorks
    assert all('"janedoe" email phone' in d for d in q_dorks)


async def test_plugin_run_emits_dorks_urls_entities():
    out = await GenerateDorksPlugin().run(
        GenerateDorksInput(target="janedoe"), PluginContext(http=None)
    )
    assert out.dorks and out.urls
    assert all(u.startswith("https://www.google.com/search?q=") for u in out.urls)
    tv = {(e.type, e.value) for e in out.entities}
    assert ("username", "janedoe") in tv
    assert ("person", "janedoe") in tv
    assert "janedoe" in out.summary_markdown
