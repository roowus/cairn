"""The single PydanticAI-isolation seam for Cairn's streaming turn events.

This module lives in **orchestration** (not ``interfaces/tui``) because
:meth:`cairn.orchestration.session.Session.iter_turn` *produces* these events —
the controller owns the run — and the UI in ``interfaces/tui`` consumes them
*downward*. Putting the seam in ``interfaces`` would force orchestration to
import upward into the presentation layer, violating the dependency rule
(``interfaces → orchestration → execution``). The event types themselves are
UI-neutral: they describe a turn's text/thinking/tool-lifecycle stream.

PydanticAI's event classes (``PartStartEvent``, ``FunctionToolCallEvent``, …)
are pre-3.0 and may rename between minor releases. To keep that churn contained,
**every** PydanticAI event object that anything outside this module consumes is
converted here into a flat, stable :data:`TurnEvent` union. The UI
(``live_turn``, ``cards``, …) and any other consumer only ever see ``TurnEvent``s
— never a PydanticAI type. So a PydanticAI API change is a one-file patch in this
module, plus the recorded-sequence test in ``tests/unit/test_tui_events.py``.

The events arrive from :meth:`cairn.orchestration.session.Session.iter_turn`,
which drives ``agent.iter()`` and streams each node via ``node.stream(ctx)``.

The hard-stop is untouched: tool *execution* still flows through the audited
``_tool`` closure in :mod:`cairn.orchestration.tool_adapter`; these stream events
only carry the model's text/thinking deltas and the tool-call *lifecycle* (args
forming → call starting → result landing), never the result payload itself.
"""

from __future__ import annotations

from dataclasses import dataclass

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
)

__all__ = [
    "TextDelta",
    "TextEnd",
    "TextStart",
    "ThinkingDelta",
    "ThinkingEnd",
    "ThinkingStart",
    "ToolArgsDelta",
    "ToolArgsEnd",
    "ToolArgsStart",
    "ToolExecEnd",
    "ToolExecStart",
    "TurnEvent",
    "TurnFinal",
    "normalize",
]


# --- Assistant text / reasoning -------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextStart:
    """The model began emitting assistant text at this part index."""

    index: int


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A chunk of assistant text to append (the streaming payload)."""

    index: int
    text: str


@dataclass(frozen=True, slots=True)
class TextEnd:
    """The assistant text part at this index is complete."""

    index: int


@dataclass(frozen=True, slots=True)
class ThinkingStart:
    index: int


@dataclass(frozen=True, slots=True)
class ThinkingDelta:
    """A chunk of model reasoning (rendered collapsed by default)."""

    index: int
    text: str


@dataclass(frozen=True, slots=True)
class ThinkingEnd:
    index: int


# --- Tool-call argument streaming (the model composing a call) ------------------


@dataclass(frozen=True, slots=True)
class ToolArgsStart:
    """The model started composing a tool call's arguments."""

    index: int
    tool_name: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class ToolArgsDelta:
    """A fragment of a tool call's JSON args as the model types them out."""

    index: int
    tool_name: str | None
    tool_call_id: str | None
    fragment: str


@dataclass(frozen=True, slots=True)
class ToolArgsEnd:
    index: int
    tool_name: str
    tool_call_id: str


# --- Tool execution lifecycle (distinct from the audited closure) --------------


@dataclass(frozen=True, slots=True)
class ToolExecStart:
    """PydanticAI is about to invoke the tool (the closure's on_tool_start fires too)."""

    tool_call_id: str
    tool_name: str
    args_valid: bool | None


@dataclass(frozen=True, slots=True)
class ToolExecEnd:
    """The tool returned. ``is_error`` is True when the result is a RetryPromptPart."""

    tool_call_id: str
    tool_name: str | None
    is_error: bool


@dataclass(frozen=True, slots=True)
class TurnFinal:
    """The model is committing to its final answer for this model request."""

    tool_name: str | None = None


type TurnEvent = (
    TextStart | TextDelta | TextEnd
    | ThinkingStart | ThinkingDelta | ThinkingEnd
    | ToolArgsStart | ToolArgsDelta | ToolArgsEnd
    | ToolExecStart | ToolExecEnd | TurnFinal
)


def normalize(event: object) -> TurnEvent | None:
    """Convert one PydanticAI stream event into a stable ``TurnEvent`` (or ``None``).

    ``None`` is returned for events Cairn does not render (e.g. provider-only
    bookkeeping) so callers can simply skip them.
    """
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, TextPart):
            return TextStart(event.index)
        if isinstance(part, ThinkingPart):
            return ThinkingStart(event.index)
        if isinstance(part, ToolCallPart):
            return ToolArgsStart(event.index, part.tool_name, part.tool_call_id)
        return None

    if isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta):
            return TextDelta(event.index, delta.content_delta)
        if isinstance(delta, ThinkingPartDelta):
            return ThinkingDelta(event.index, delta.content_delta or "")
        if isinstance(delta, ToolCallPartDelta):
            fragment = delta.args_delta if isinstance(delta.args_delta, str) else ""
            return ToolArgsDelta(event.index, delta.tool_name_delta, delta.tool_call_id, fragment)
        return None

    if isinstance(event, PartEndEvent):
        part = event.part
        if isinstance(part, TextPart):
            return TextEnd(event.index)
        if isinstance(part, ThinkingPart):
            return ThinkingEnd(event.index)
        if isinstance(part, ToolCallPart):
            return ToolArgsEnd(event.index, part.tool_name, part.tool_call_id)
        return None

    if isinstance(event, FinalResultEvent):
        return TurnFinal(event.tool_name)

    if isinstance(event, FunctionToolCallEvent):
        return ToolExecStart(event.tool_call_id, event.part.tool_name, event.args_valid)

    if isinstance(event, FunctionToolResultEvent):
        is_error = isinstance(event.part, RetryPromptPart)
        tool_name = getattr(event.part, "tool_name", None)
        return ToolExecEnd(event.tool_call_id, tool_name, is_error)

    return None
