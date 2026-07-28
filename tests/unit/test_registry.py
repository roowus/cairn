"""Plugin registry: discovery, availability gating, dedup."""

from __future__ import annotations

import pytest

from cairn.execution.base import BasePlugin, PluginContext, PluginInput, PluginOutput
from cairn.execution.registry import PluginRegistry, discover


class _In(PluginInput):
    pass


class _Out(PluginOutput):
    pass


class _FreePlugin(BasePlugin):
    name = "unit_free"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_free", summary_markdown="ok")


class _PaidPlugin(BasePlugin):
    name = "unit_paid"
    category = "identity"
    requires_key = "shodan"
    input_model = _In
    output_model = _Out

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_paid", summary_markdown="ok")


def test_register_and_available():
    reg = PluginRegistry()
    reg.register(_FreePlugin())
    reg.register(_PaidPlugin())
    ctx = PluginContext()
    assert len(reg) == 2
    assert {p.name for p in reg.available(ctx)} == {"unit_free"}


def test_available_with_key():
    from pydantic import SecretStr

    reg = PluginRegistry()
    reg.register(_PaidPlugin())
    ctx = PluginContext(keys={"shodan": SecretStr("SH-x")})
    assert reg.available(ctx)[0].name == "unit_paid"


def test_duplicate_name_raises():
    reg = PluginRegistry()
    reg.register(_FreePlugin())
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(_FreePlugin())


def test_discover_finds_real_plugins():
    reg = discover()
    names = {p.name for p in reg.all()}
    assert "shodan_internetdb" in names
    assert "whois_rdap" in names
    assert "dns_lookup" in names
    assert "shodan_full" in names  # paid, still discovered
