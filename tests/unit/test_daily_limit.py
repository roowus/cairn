"""Daily-quota gating: daily-limited free plugins are off by default, opt-in via ctx."""

from __future__ import annotations

from cairn.execution.base import BasePlugin, PluginContext, PluginInput, PluginOutput
from cairn.execution.registry import PluginRegistry


class _In(PluginInput):
    pass


class _Out(PluginOutput):
    pass


class _DailyPlugin(BasePlugin):
    name = "unit_daily"
    category = "infrastructure"
    requires_key = None
    daily_limited = True
    input_model = _In
    output_model = _Out

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_daily", summary_markdown="ok")


class _FreePlugin(BasePlugin):
    name = "unit_free2"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_free2", summary_markdown="ok")


def _reg() -> PluginRegistry:
    reg = PluginRegistry()
    reg.register(_DailyPlugin())
    reg.register(_FreePlugin())
    return reg


def test_daily_limited_hidden_by_default():
    reg = _reg()
    ctx = PluginContext()  # allow_daily_limited defaults False
    names = {p.name for p in reg.available(ctx)}
    assert "unit_free2" in names
    assert "unit_daily" not in names  # excluded by default


def test_daily_limited_enabled_when_opted_in():
    reg = _reg()
    ctx = PluginContext(allow_daily_limited=True)
    names = {p.name for p in reg.available(ctx)}
    assert {"unit_free2", "unit_daily"} == names


def test_hackertarget_is_marked_daily_limited():
    # the one real free plugin with a hard per-day quota
    from cairn.plugins.infrastructure.hackertarget import HackertargetPlugin

    assert HackertargetPlugin.daily_limited is True
