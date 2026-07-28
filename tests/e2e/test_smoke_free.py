"""End-to-end smoke against real FREE APIs (no key required).

Marked ``network`` — skipped by default. Run with: ``uv run pytest -m network``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.network


async def test_shodan_internetdb_live():
    from cairn.execution.base import PluginContext
    from cairn.plugins.identity.shodan_internetdb import (
        ShodanInternetDBInput,
        ShodanInternetDBPlugin,
    )

    out = await ShodanInternetDBPlugin().run(
        ShodanInternetDBInput(target="8.8.8.8"), PluginContext(http=None)
    )
    assert 53 in out.ports or out.ports  # tolerate index variance


async def test_whois_rdap_live():
    from cairn.execution.base import PluginContext
    from cairn.plugins.identity.whois_rdap import WhoisRdapInput, WhoisRdapPlugin

    out = await WhoisRdapPlugin().run(
        WhoisRdapInput(target="example.com"), PluginContext(http=None)
    )
    assert out.nameservers  # example.com always has nameservers


async def test_dns_lookup_live():
    from cairn.execution.base import PluginContext
    from cairn.plugins.infrastructure.dns_lookup import DnsLookupInput, DnsLookupPlugin

    out = await DnsLookupPlugin().run(
        DnsLookupInput(target="example.com", record_type="A"), PluginContext(http=None)
    )
    assert out.answers


async def test_github_live():
    from cairn.execution.base import PluginContext
    from cairn.plugins.identity.github import GithubInput, GithubPlugin

    out = await GithubPlugin().run(
        GithubInput(target="torvalds", include_repos=False), PluginContext(http=None)
    )
    assert out.login == "torvalds"
    assert out.html_url == "https://github.com/torvalds"


async def test_urlscan_live():
    from cairn.execution.base import PluginContext
    from cairn.plugins.web.urlscan import UrlscanInput, UrlscanPlugin

    out = await UrlscanPlugin().run(
        UrlscanInput(target="example.com", limit=5), PluginContext(http=None)
    )
    assert out.total >= 0  # tolerate rate limits / empty


async def test_hackertarget_live():
    from cairn.execution.base import PluginContext
    from cairn.plugins.infrastructure.hackertarget import HackertargetInput, HackertargetPlugin

    out = await HackertargetPlugin().run(
        HackertargetInput(target="example.com"), PluginContext(http=None)
    )
    assert out.query == "hostsearch"
    assert out.summary_markdown  # something came back (even a rate-limit message)
