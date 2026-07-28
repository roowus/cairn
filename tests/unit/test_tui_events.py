"""Streaming-UI bridge: the PydanticAI-isolation seam + streaming renderers.

These tests guard the three things most likely to break across a PydanticAI bump
or a refactor:

1. :func:`cairn.orchestration.events.normalize` — every PydanticAI stream event
   maps to the expected stable ``TurnEvent``. If PydanticAI renames a class or
   field, this is the canary (the whole point of confining event handling to one
   module).
2. :class:`cairn.interfaces.tui.markdown_stream.MarkdownStream` — throttle
   coalescing, fence trimming, dedupe, cap, and seal.
3. The wired path end-to-end — :meth:`Session.iter_turn` yields the full event
   lifecycle and :func:`run_turn` streams + seals without touching the network
   (driven by :class:`pydantic_ai.models.test.TestModel`).

The hard-stop is exercised implicitly: the audited ``_tool`` closure still fires
under ``iter_turn`` (the same path :mod:`tests.unit.test_usage` covers), so a tool
call still lands in the audit log.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

from pydantic_ai.messages import (
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel
from rich.console import Console

from cairn.execution.base import BasePlugin, PluginInput, PluginOutput
from cairn.execution.registry import PluginRegistry
from cairn.interfaces.tui.live_turn import run_turn
from cairn.interfaces.tui.markdown_stream import MarkdownStream, trim_trailing_fence
from cairn.orchestration.events import (
    TextDelta,
    TextEnd,
    TextStart,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    ToolArgsDelta,
    ToolArgsEnd,
    ToolArgsStart,
    ToolExecEnd,
    ToolExecStart,
    TurnFinal,
    normalize,
)
from cairn.orchestration.progress import Progress
from cairn.orchestration.session import Session
from cairn.storage.db import Database

# --- shared test plugin --------------------------------------------------------


class _In(PluginInput):
    pass


class _Out(PluginOutput):
    pass


class _EchoPlugin(BasePlugin):
    name = "unit_tui_echo"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    __doc__ = "echo"

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_tui_echo", summary_markdown="echoed ok")


def _session(fake_settings, tmp_path):
    reg = PluginRegistry()
    reg.register(_EchoPlugin())
    return Session(
        settings=fake_settings,
        registry=reg,
        model=TestModel(),
        db=Database(tmp_path / "tui.db"),
    )


# --- 1. normalize: PydanticAI event -> TurnEvent -------------------------------


def test_normalize_text_parts():
    assert normalize(PartStartEvent(index=0, part=TextPart(content=""))) == TextStart(0)
    assert (
        normalize(PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="Hi")))
        == TextDelta(0, "Hi")
    )
    assert normalize(PartEndEvent(index=0, part=TextPart(content="Hi"))) == TextEnd(0)


def test_normalize_thinking_parts():
    assert normalize(PartStartEvent(index=1, part=ThinkingPart(content=""))) == ThinkingStart(1)
    assert (
        normalize(PartDeltaEvent(index=1, delta=ThinkingPartDelta(content_delta="hm")))
        == ThinkingDelta(1, "hm")
    )
    # ThinkingPartDelta.content_delta may be None -> normalized to ""
    assert (
        normalize(PartDeltaEvent(index=1, delta=ThinkingPartDelta(content_delta=None)))
        == ThinkingDelta(1, "")
    )
    assert normalize(PartEndEvent(index=1, part=ThinkingPart(content="hm"))) == ThinkingEnd(1)


def test_normalize_tool_arg_streaming():
    assert normalize(
        PartStartEvent(index=2, part=ToolCallPart(tool_name="echo", args={}, tool_call_id="t1"))
    ) == ToolArgsStart(2, "echo", "t1")
    # string args fragment -> carried through; dict fragment -> empty string
    assert normalize(
        PartDeltaEvent(index=2, delta=ToolCallPartDelta(args_delta='{"x":'))
    ) == ToolArgsDelta(2, None, None, '{"x":')
    assert normalize(
        PartDeltaEvent(index=2, delta=ToolCallPartDelta(args_delta={"x": 1}))
    ) == ToolArgsDelta(2, None, None, "")
    assert normalize(
        PartEndEvent(index=2, part=ToolCallPart(tool_name="echo", args={}, tool_call_id="t1"))
    ) == ToolArgsEnd(2, "echo", "t1")


def test_normalize_tool_lifecycle():
    assert normalize(FinalResultEvent(tool_name=None, tool_call_id=None)) == TurnFinal(None)
    assert normalize(FinalResultEvent(tool_name="result", tool_call_id="t9")) == TurnFinal("result")
    assert normalize(
        FunctionToolCallEvent(
            part=ToolCallPart(tool_name="echo", args={}, tool_call_id="t1"), args_valid=True
        )
    ) == ToolExecStart("t1", "echo", True)
    # successful result
    assert normalize(
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="echo", content="ok", tool_call_id="t1")
        )
    ) == ToolExecEnd("t1", "echo", False)
    # RetryPromptPart -> is_error
    assert normalize(
        FunctionToolResultEvent(
            part=RetryPromptPart(content="bad", tool_name="echo", tool_call_id="t1")
        )
    ) == ToolExecEnd("t1", "echo", True)


def test_normalize_unknown_event_returns_none():
    class _Bookkeeping:
        pass

    assert normalize(_Bookkeeping()) is None


# --- 2. markdown_stream --------------------------------------------------------


def test_trim_trailing_fence_strips_lone_opener():
    assert trim_trailing_fence("hello") == "hello"
    # odd fence count -> the trailing opener is dropped so code renders as prose
    assert trim_trailing_fence("a\n```\ncode") == "a\n\ncode"
    # even fence count -> a complete block, left intact
    assert trim_trailing_fence("a\n```\ncode\n```") == "a\n```\ncode\n```"


def test_markdown_stream_throttle_coalesces_within_window():
    ms = MarkdownStream(min_interval=0.032)
    ms.append("Hello ")
    first = ms.render(now=0.0)
    ms.append("world")
    within = ms.render(now=0.01)  # inside the throttle window
    assert within is first, "within-window render must return the cached parse"
    after = ms.render(now=0.04)  # window elapsed -> re-parse
    assert after is not first
    assert ms.text == "Hello world"


def test_markdown_stream_dedupe_when_view_unchanged():
    ms = MarkdownStream(min_interval=0.032)
    ms.append("same")
    r1 = ms.render(now=0.0)
    r2 = ms.render(now=1.0)  # window elapsed, but view unchanged -> cached
    assert r2 is r1


def test_markdown_stream_caps_tail_then_seals_full():
    ms = MarkdownStream(max_stream_chars=10)
    ms.append("abcdefghij" * 5)  # 50 chars -> exceeds cap while streaming
    view = ms._view()
    assert view.startswith("…\n")
    assert len(view) <= 16
    sealed = ms.seal()
    assert ms._view() == "abcdefghij" * 5  # seal drops trim + cap
    assert sealed is not None


# --- 3. wired path: iter_turn + run_turn (no network) -------------------------


async def test_iter_turn_yields_full_lifecycle_and_sets_output(fake_settings, tmp_path):
    session = _session(fake_settings, tmp_path)
    try:
        kinds: list[str] = []
        async for ev in session.iter_turn(
            "hi",
            model=TestModel(call_tools=["unit_tui_echo"], custom_output_text="done"),
        ):
            kinds.append(type(ev).__name__)
    finally:
        await session.aclose()

    # tool args forming + execution
    assert "ToolArgsStart" in kinds and "ToolArgsEnd" in kinds
    assert "ToolExecStart" in kinds and "ToolExecEnd" in kinds
    # streamed final answer
    assert "TextDelta" in kinds and "TurnFinal" in kinds
    assert session.last_output == "done"
    assert session.history  # multi-turn memory persisted


async def test_iter_turn_merges_llm_usage_into_statusline(fake_settings, tmp_path):
    """End-to-end token accounting: a completed turn merges its ``RunUsage`` into
    ``session.llm_usage`` (the assignment runs after the stream drains), the
    statusline then surfaces the token counts, and a second turn accumulates
    rather than resetting. Guards the merge timing + the statusline read.
    """
    from cairn.interfaces.tui.statusline import render_statusline

    session = _session(fake_settings, tmp_path)
    try:
        async for _ in session.iter_turn(
            "hi", model=TestModel(call_tools=["unit_tui_echo"], custom_output_text="done")
        ):
            pass
        in1, out1 = session.llm_usage.input_tokens, session.llm_usage.output_tokens
        assert in1 > 0 and out1 > 0
        assert "tok" in render_statusline(session).plain

        async for _ in session.iter_turn(
            "again", model=TestModel(call_tools=["unit_tui_echo"], custom_output_text="done2")
        ):
            pass
        assert session.llm_usage.input_tokens > in1  # accumulated, not reset
        assert session.llm_usage.output_tokens > out1
    finally:
        await session.aclose()


async def test_run_turn_streams_tools_and_seals_markdown(fake_settings, tmp_path):
    session = _session(fake_settings, tmp_path)
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=60, color_system=None)
    try:
        out = await run_turn(
            session,
            "x",
            console=console,
            model=TestModel(
                call_tools=["unit_tui_echo"], custom_output_text="# Title\n\nbody text"
            ),
        )
    finally:
        await session.aclose()

    assert out == "# Title\n\nbody text"
    rendered = buf.getvalue()
    assert "unit_tui_echo" in rendered  # tool line rendered
    assert "Title" in rendered and "body text" in rendered  # markdown sealed into the frame


async def test_run_turn_chrome_zoned_frame(fake_settings, tmp_path):
    """U1: chrome=True renders the per-turn zoned block — a header line, a 'tools'
    panel around the tool card, an 'answer' panel around the sealed markdown, and a
    '/help · Esc stop' footer. This is the structured REPL layout."""
    session = _session(fake_settings, tmp_path)
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=60, color_system=None)
    try:
        await run_turn(
            session,
            "x",
            console=console,
            chrome=True,
            model=TestModel(
                call_tools=["unit_tui_echo"], custom_output_text="# Title\n\nbody"
            ),
        )
    finally:
        await session.aclose()
    rendered = buf.getvalue()
    assert "cairn" in rendered  # header line
    assert "tools" in rendered and "answer" in rendered  # the two panel titles
    assert "/help" in rendered  # footer
    assert "unit_tui_echo" in rendered  # tool still present inside the tools panel
    assert "Title" in rendered and "body" in rendered  # markdown inside the answer panel


async def test_run_turn_headless_flat_has_no_chrome(fake_settings, tmp_path):
    """U1 regression: chrome=False + show_status=False keeps the pre-U1 flat,
    pipe-friendly output — no header, no boxed panels, no footer. Headless
    (``cairn search``) must not gain chrome."""
    session = _session(fake_settings, tmp_path)
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=60, color_system=None)
    try:
        await run_turn(
            session,
            "x",
            console=console,
            chrome=False,
            show_status=False,
            model=TestModel(
                call_tools=["unit_tui_echo"], custom_output_text="# Title\n\nbody"
            ),
        )
    finally:
        await session.aclose()
    rendered = buf.getvalue()
    # flat output still carries the tool line + the sealed markdown...
    assert "unit_tui_echo" in rendered
    assert "Title" in rendered and "body" in rendered
    # ...but none of the chrome zones.
    assert "answer" not in rendered  # no answer panel title
    assert "/help" not in rendered  # no footer
    assert "v0.1.0" not in rendered  # no header


# --- 4. tool_call_id correlation (robust under parallel tool execution) --------


class _Echo2Plugin(BasePlugin):
    name = "unit_tui_echo2"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    __doc__ = "echo2"

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_tui_echo2", summary_markdown="echoed ok 2")


async def test_tool_call_id_matches_between_stream_and_closure(fake_settings, tmp_path):
    """The closure's Progress hooks receive the SAME per-call tool_call_id as the
    stream's ToolExecStart — the property that lets a card key on id and stay
    correct when PydanticAI runs tools in parallel (completion ≠ emission order).
    """
    reg = PluginRegistry()
    reg.register(_EchoPlugin())
    reg.register(_Echo2Plugin())
    session = Session(
        settings=fake_settings, registry=reg, model=TestModel(), db=Database(tmp_path / "ids.db")
    )

    stream_ids: dict[str, str] = {}  # tool_name -> tool_call_id (from the stream)
    closure_ids: dict[str, str] = {}  # tool_name -> tool_call_id (from the closure)

    class _IdRecorder(Progress):
        def on_tool_start(self, name, target, params, tool_call_id):  # type: ignore[override]
            closure_ids[name] = tool_call_id

        def on_tool_end(self, name, target, status, summary, error, tool_call_id):  # type: ignore[override]
            pass  # captured at start

    try:
        async for ev in session.iter_turn(
            "x",
            model=TestModel(
                call_tools=["unit_tui_echo", "unit_tui_echo2"], custom_output_text="done"
            ),
            progress=_IdRecorder(),
        ):
            if isinstance(ev, ToolExecStart):
                stream_ids[ev.tool_name] = ev.tool_call_id
    finally:
        await session.aclose()

    # both tools were called, each with its own distinct id...
    assert set(stream_ids) == {"unit_tui_echo", "unit_tui_echo2"}
    assert len(set(stream_ids.values())) == 2
    # ...and the closure saw the EXACT same per-call id as the stream for each tool.
    assert stream_ids == closure_ids


def test_composer_correlates_cards_by_id_under_interleaving():
    """Cards key by tool_call_id and finish correctly regardless of start/end
    interleaving (parallel tools complete out of order). Deterministic, no network.
    """
    from cairn.interfaces.tui.live_turn import _Composer

    c = _Composer(SimpleNamespace(model_name="m"))  # session only feeds the statusline
    # two tools compose (A, B); targets arrive; B finishes before A (parallel)
    c.args_started("id_a", "dns_lookup")
    c.args_started("id_b", "web_search")
    c.tool_started("id_a", "dns_lookup", "8.8.8.8")
    c.tool_started("id_b", "web_search", "8.8.8.8")
    c.tool_finished("id_b", "web_search", "8.8.8.8", "ok", "8.8.8.8 A: no records", None)
    c.tool_finished("id_a", "dns_lookup", "8.8.8.8", "error", "", "boom")

    cards = list(c.cards.values())
    # insertion (emission) order preserved, not completion order
    assert [x.tool_call_id for x in cards] == ["id_a", "id_b"]
    a, b = cards
    assert a.done and a.tool_name == "dns_lookup" and a.target == "8.8.8.8" and a.is_error
    assert b.done and b.tool_name == "web_search" and not b.is_error and "no records" in b.excerpt


def test_tool_card_transitions_are_idempotent_and_order_insensitive():
    """Late stream events after the closure already finalized don't clobber a card."""
    from cairn.interfaces.tui.cards import ToolCard

    card = ToolCard(tool_call_id="x", tool_name="t")
    card.set_target("8.8.8.8")  # closure start -> running, target set
    assert card.state == "running"
    card.finish("ok", "real summary", None)  # closure end -> done with excerpt
    assert card.done and card.excerpt == "real summary"
    card.finish_fallback(is_error=True)  # late stream ToolExecEnd must not override
    assert card.done and not card.is_error and card.excerpt == "real summary"


def test_tool_schema_excludes_runcontext_param(fake_settings, tmp_path):
    """The agent.tool switch must NOT leak the RunContext param into the LLM-facing
    JSON schema: the model still sees exactly the plugin's input fields. Guards the
    schema-exclusion invariant; if pydantic_ai renames these internals the test
    fails loudly (which is the point — re-confirm exclusion after a bump).
    """
    session = _session(fake_settings, tmp_path)
    try:
        tool = session.agent._function_toolset.tools["unit_tui_echo"]
        schema = tool.function_schema.json_schema
        assert tool.function_schema.takes_ctx is True  # receives RunContext -> tool_call_id
    finally:
        session.close()
    props = schema.get("properties", {})
    assert "rctx" not in props, "RunContext param leaked into the LLM tool schema"
    assert props, "expected at least the inherited 'target' field in the schema"

