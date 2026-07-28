"""Progress observer: live tool-call notifications fire with correct status.

Drives a fake plugin through a real Session with a TestModel; records every
callback into a recording observer and asserts the sequence + status values.
No real LLM or network.
"""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from cairn.execution.base import BasePlugin, PluginInput, PluginOutput
from cairn.execution.registry import PluginRegistry
from cairn.orchestration.progress import NullProgress, Progress, excerpt
from cairn.orchestration.session import Session


class _In(PluginInput):
    pass


class _Out(PluginOutput):
    pass


class OkPlugin(BasePlugin):
    name = "ok_plugin"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    __doc__ = "ok"

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="ok_plugin", summary_markdown=f"OK for {inp.target}")


class FailPlugin(BasePlugin):
    name = "fail_plugin"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    __doc__ = "fails"

    async def run(self, inp, ctx):  # type: ignore[override]
        raise RuntimeError("kaboom")


class _Recorder(Progress):
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_tool_start(self, name, target, params, tool_call_id):  # type: ignore[override]
        self.events.append(("start", name, target, tool_call_id))

    def on_tool_end(self, name, target, status, summary, error, tool_call_id):  # type: ignore[override]
        self.events.append(("end", name, target, status, bool(error), tool_call_id))


def _registry(*plugins):
    reg = PluginRegistry()
    for p in plugins:
        reg.register(p())
    return reg


async def test_progress_fires_for_successful_call(fake_settings):
    session = Session(settings=fake_settings, registry=_registry(OkPlugin), model=TestModel())
    rec = _Recorder()
    await session.ask(
        "x",
        model=TestModel(call_tools=["ok_plugin"], custom_output_text="done"),
        progress=rec,
    )
    await session.aclose()
    start = next(e for e in rec.events if e[0] == "start")
    end = next(e for e in rec.events if e[0] == "end")
    assert start[1] == "ok_plugin"  # name recorded, target present
    assert end[3] == "ok" and end[4] is False  # status ok, no error
    # tool_call_id is threaded through the closure (RunContext.tool_call_id) and is
    # the same per-call id on start and end — the robust parallel-execution key.
    assert start[3] and start[3] == end[5]


async def test_progress_reports_error_status(fake_settings):
    session = Session(settings=fake_settings, registry=_registry(FailPlugin), model=TestModel())
    rec = _Recorder()
    await session.ask(
        "x",
        model=TestModel(call_tools=["fail_plugin"], custom_output_text="recovered"),
        progress=rec,
    )
    await session.aclose()
    end = next(e for e in rec.events if e[0] == "end")
    assert end[3] == "error"
    assert end[4] is True


def test_null_progress_is_safe_to_call():
    # NullProgress must accept every hook without error (default impls).
    np = NullProgress()
    np.on_turn_start("hi")
    np.on_tool_start("t", "8.8.8.8", {}, "call_1")
    np.on_tool_end("t", "8.8.8.8", "ok", "**x** — something", None, "call_1")
    np.on_turn_end("answer")


def test_excerpt_collapses_markdown_and_truncates():
    assert excerpt("**8.8.8.8** — open ports: 80, 443") == "8.8.8.8 — open ports: 80, 443"
    assert excerpt("a" * 200, limit=20).endswith("…")
    assert excerpt("") == ""
    assert excerpt("first line\nsecond line") == "first line"
