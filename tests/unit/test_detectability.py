"""OPSEC detectability tagging (moat Pillar 3) on plugins + CLI tools."""

from __future__ import annotations

from cairn.execution.cli_tools import list_cli_tools
from cairn.execution.registry import discover

_VALID = ("low", "medium", "high")


def test_every_plugin_has_valid_detectability():
    plugins = discover().all()
    assert plugins  # nonempty
    for p in plugins:
        assert p.detectability in _VALID, f"{p.name}: {p.detectability!r}"


def test_known_opsec_tags_on_plugins():
    by_name = {p.name: p for p in discover().all()}
    # active scanning
    assert by_name["run_command"].detectability == "high"
    # targeted probes the target's infra observes
    for med in ("holehe", "username_check", "sherlock", "scrape_url", "download_url"):
        assert by_name[med].detectability == "medium", med
    # passive (target never sees you)
    for low in ("crtsh", "whois_rdap", "shodan_internetdb", "dns_lookup"):
        assert by_name[low].detectability == "low", low


def test_cli_tool_detectability_tags():
    by_name = {t.name: t for t in list_cli_tools()}
    assert by_name["nmap"].detectability == "high"
    assert by_name["sherlock"].detectability == "medium"
    assert by_name["holehe"].detectability == "medium"
    assert by_name["dig"].detectability == "low"
