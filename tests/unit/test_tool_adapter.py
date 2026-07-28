"""Tool adapter + session: the hard-stop integration.

A TestModel drives a fake plugin through a real Session; we assert the result is
wrapped in <untrusted_external_data>, an audit row is written, and an entity is
captured in the graph. No real LLM or network is used.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from cairn.execution.base import BasePlugin, Entity, PluginInput, PluginOutput
from cairn.execution.registry import PluginRegistry
from cairn.orchestration.session import Session


class FakeInput(PluginInput):
    pass


class FakeOutput(PluginOutput):
    pass


class FakePlugin(BasePlugin):
    name = "fake_test_plugin"
    category = "identity"
    requires_key = None
    input_model = FakeInput
    output_model = FakeOutput
    __doc__ = "fake plugin for tests"

    async def run(self, inp, ctx):  # type: ignore[override]
        return FakeOutput(
            source="fake_test_plugin",
            summary_markdown=f"FAKE RESULT for {inp.target}",
            entities=[Entity(type="ip", value=inp.target)],
        )


@pytest.fixture
def fake_registry():
    reg = PluginRegistry()
    reg.register(FakePlugin())
    return reg


async def test_tool_result_is_wrapped(fake_settings, fake_registry):
    session = Session(settings=fake_settings, registry=fake_registry, model=TestModel())
    tm = TestModel(call_tools=["fake_test_plugin"], custom_output_text="synthesis")
    out = await session.ask("look up 1.2.3.4", model=tm)
    await session.aclose()
    # the synthesis is returned to the user
    assert out == "synthesis"
    # the tool result the model saw was wrapped (audit recorded a successful call)
    row = session.db.execute(
        "SELECT tool, status, result_size FROM audit_log WHERE tool = 'fake_test_plugin'"
    ).fetchone()
    assert row is not None
    assert row["status"] == "ok"
    assert row["result_size"] > 0


async def test_entity_captured_in_graph(fake_settings, fake_registry):
    session = Session(settings=fake_settings, registry=fake_registry, model=TestModel())
    await session.ask(
        "x", model=TestModel(call_tools=["fake_test_plugin"], custom_output_text="ok")
    )
    await session.aclose()
    types_values = {(e.type, e.value) for e in session.graph.entities()}
    assert any(t == "ip" for t, _ in types_values)


async def test_tool_error_does_not_crash_loop(fake_settings, monkeypatch):
    class BoomPlugin(BasePlugin):
        name = "boom_plugin"
        category = "identity"
        requires_key = None
        input_model = FakeInput
        output_model = FakeOutput
        __doc__ = "always fails"

        async def run(self, inp, ctx):  # type: ignore[override]
            raise RuntimeError("boom")

    reg = PluginRegistry()
    reg.register(BoomPlugin())
    session = Session(settings=fake_settings, registry=reg, model=TestModel())
    out = await session.ask(
        "x", model=TestModel(call_tools=["boom_plugin"], custom_output_text="recovered")
    )
    await session.aclose()
    assert out == "recovered"
    row = session.db.execute(
        "SELECT status, error FROM audit_log WHERE tool='boom_plugin'"
    ).fetchone()
    assert row["status"] == "error"
    assert "boom" in (row["error"] or "")


def test_apply_signature_does_not_leak_runcontext():
    """Regression: ``_apply_signature`` is shared with the Typer plugin command
    (``plugin_cli._make_cmd``), so it must NOT inject the agent-only ``rctx``
    parameter — only :func:`_prepend_runctx` does, on the agent-tool wrapper.
    Leaking it here once made Typer reject every ``cairn plugin <name>`` command
    at startup with ``Type not yet supported: RunContext[NoneType]``.
    """
    import inspect

    from cairn.execution.base import PluginInput
    from cairn.orchestration.tool_adapter import _apply_signature

    class _In(PluginInput):
        pass

    def _cmd(**kwargs):  # type: ignore[no-untyped-def]
        pass

    _apply_signature(_cmd, _In, "some_plugin", "doc")
    names = list(inspect.signature(_cmd).parameters)
    assert "rctx" not in names, "RunContext leaked into the shared CLI signature"
    assert "target" in names  # input-model field is mirrored


def test_plugin_cli_builds_click_command_group():
    """Regression guard for the startup crash: building the full Typer→Click
    command tree must not choke on an unsupported parameter type. This is the
    exact path ``cairn`` runs at ``app()`` and that crashed when the Phase-2
    RunContext injection leaked into every plugin command. Offline (discovery +
    signature building read no keys / make no network calls).
    """
    from typer.main import get_command

    from cairn.interfaces.plugin_cli import build_plugin_cli

    get_command(build_plugin_cli())  # raises RuntimeError if a command param is unsupported
