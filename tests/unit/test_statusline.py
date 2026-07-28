"""Statusline renderer: model · cumulative LLM tokens · tool calls · paid spend.

The statusline is pure presentation over :attr:`Session.llm_usage` (merged
PydanticAI ``RunUsage``) and :class:`~cairn.orchestration.usage.UsageTracker`. It
carries no payload and must render safely at any point mid-turn.
"""

from __future__ import annotations

from types import SimpleNamespace

from pydantic_ai.usage import RunUsage

from cairn.execution.base import BasePlugin, CostSpec, PluginInput, PluginOutput
from cairn.interfaces.tui.statusline import _compact, render_statusline
from cairn.orchestration.usage import UsageTracker


def _session(*, model="grok-4.5", llm=None, usage=None):
    return SimpleNamespace(
        model_name=model,
        llm_usage=llm if llm is not None else RunUsage(),
        usage=usage if usage is not None else UsageTracker(),
    )


# --- number formatting --------------------------------------------------------


def test_compact_number_formatting():
    assert _compact(0) == "0"
    assert _compact(999) == "999"
    assert _compact(1000) == "1.0k"
    assert _compact(1234) == "1.2k"
    assert _compact(999_949) == "999.9k"
    assert _compact(999_999) == "1.0M"  # k-band would round to 1000.0k → promoted
    assert _compact(1_000_000) == "1.0M"
    assert _compact(1_500_000) == "1.5M"


# --- model + hints ------------------------------------------------------------


def test_statusline_shows_model_and_repl_hints():
    txt = render_statusline(_session(), hints=True).plain
    assert "grok-4.5" in txt
    assert "/help" in txt and "Esc stop" in txt


def test_statusline_omits_hints_for_headless():
    txt = render_statusline(_session(), hints=False).plain
    assert "/help" not in txt
    assert "Esc stop" not in txt


# --- LLM tokens ---------------------------------------------------------------


def test_statusline_shows_tokens_once_present():
    llm = RunUsage(input_tokens=1234, output_tokens=567)
    txt = render_statusline(_session(llm=llm)).plain
    assert "↑1.2k" in txt
    assert "↓567" in txt
    assert "tok" in txt


def test_statusline_hides_tokens_until_a_turn_completes():
    # A fresh session (RunUsage defaults to 0) shows no token segment — avoids a
    # misleading "↑0 ↓0 tok" before the first turn captures any usage.
    txt = render_statusline(_session()).plain
    assert "tok" not in txt


# --- tool calls + paid spend --------------------------------------------------


class _In(PluginInput):
    pass


class _Out(PluginOutput):
    pass


class _PaidPlugin(BasePlugin):
    name = "unit_paid_src"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    cost = CostSpec(paid=True, per_call=2.0, unit="credits")
    __doc__ = "paid"

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_paid_src", summary_markdown="ok")


def test_statusline_shows_tool_count_and_paid_spend():
    tracker = UsageTracker()
    tracker.record(_PaidPlugin(), elapsed_ms=100.0, status="ok")
    txt = render_statusline(_session(usage=tracker)).plain
    assert "1 tool" in txt and "tools" not in txt  # singular for one call
    assert "2 credits" in txt  # paid, magenta — still present in the plain text


def test_statusline_pluralizes_tool_count():
    tracker = UsageTracker()
    tracker.record(_PaidPlugin(), elapsed_ms=10.0, status="ok")
    tracker.record(_PaidPlugin(), elapsed_ms=10.0, status="ok")
    txt = render_statusline(_session(usage=tracker)).plain
    assert "2 tools" in txt
