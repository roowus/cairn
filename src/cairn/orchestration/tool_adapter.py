"""Wires each available plugin as a PydanticAI tool.

This is the crux of the **hard-stop execution** model: the LLM selects a tool and
supplies arguments, but the tool function we own validates them, runs the
deterministic plugin, captures entities/audit, and returns the result wrapped in
``<untrusted_external_data>``. The model never executes code and never sees raw
payloads.

Tool JSON schemas are derived from each plugin's ``PluginInput`` fields by
injecting a synthetic :class:`inspect.Signature` (validated against PydanticAI).
"""

from __future__ import annotations

import inspect
import time
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext
from pydantic_core import PydanticUndefined

from cairn.core.security import wrap_untrusted
from cairn.execution.base import PluginContext
from cairn.execution.registry import PluginRegistry
from cairn.execution.tool_progress import bind_tool_call_id

if TYPE_CHECKING:
    from cairn.orchestration.audit import AuditWriter
    from cairn.orchestration.usage import UsageTracker
    from cairn.storage.graph_store import NetworkXGraphStore


def register_tools(
    agent: Any,
    registry: PluginRegistry,
    ctx: PluginContext,
    *,
    audit: AuditWriter | None = None,
    graph: NetworkXGraphStore | None = None,
    usage: UsageTracker | None = None,
    model_name: str | None = None,
) -> int:
    """Register every available plugin as a tool on ``agent``.

    Registered via ``agent.tool`` (not ``tool_plain``) so each closure receives a
    :class:`~pydantic_ai.RunContext` carrying its per-call ``tool_call_id`` — the
    correlation key the Progress observer keys cards on. The LLM-facing JSON schema
    is unchanged (PydanticAI excludes the leading RunContext parameter).
    """
    count = 0
    for plugin in registry.available(ctx):
        agent.tool(
            _make_tool(plugin, ctx, audit=audit, graph=graph, usage=usage, model_name=model_name)
        )
        count += 1
    return count


def _make_tool(
    plugin: Any,
    ctx: PluginContext,
    *,
    audit: AuditWriter | None = None,
    graph: NetworkXGraphStore | None = None,
    usage: UsageTracker | None = None,
    model_name: str | None = None,
) -> Any:
    input_model = plugin.input_model

    async def _tool(rctx: RunContext[None], **kwargs: Any) -> str:
        # Per-call id (str|None on synthetic contexts; coerce to "" for the observer).
        # Observer-only: never written to audit/usage — those run on the raw summary.
        tool_call_id = rctx.tool_call_id or ""
        target = str(kwargs.get("target", ""))
        status = "ok"
        error: str | None = None
        result_size = 0
        out: Any = None
        progress = getattr(ctx, "progress", None)
        if progress is not None:
            progress.on_tool_start(plugin.name, target, kwargs, tool_call_id)
        start = time.perf_counter()
        try:
            # Bind this call's id so deep execution (plugin.run → run_shell)
            # can tag streamed stdout to the right ToolCard via progress_for().
            with bind_tool_call_id(tool_call_id):
                out = await plugin.run(input_model.model_validate(kwargs), ctx)
            if graph is not None:
                for entity in out.entities:
                    graph.add_entity(entity, source=plugin.name)
            summary = out.summary_markdown
            result_size = len(summary)
        except Exception as exc:
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            summary = f"Tool '{plugin.name}' failed: {error}"
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        usage_snap: dict[str, Any] | None = None
        if usage is not None:
            su = usage.record(plugin, elapsed_ms=elapsed_ms, status=status, output=out)
            from cairn.execution.base import CostSpec
            from cairn.orchestration.usage import snapshot as _snapshot

            # Per-call delta (not the cumulative su.consumed) so history aggregation
            # doesn't double-count. Only successful calls consume units.
            if status == "ok":
                per_call = (getattr(plugin, "cost", None) or CostSpec()).per_call
            else:
                per_call = 0.0
            usage_snap = _snapshot(su, per_call_consumed=per_call)
        if audit is not None:
            # Prefer the live audit.model_name so /model switches are reflected.
            live_model = getattr(audit, "model_name", None) or model_name
            audit.record(
                tool=plugin.name,
                target=target,
                params=kwargs,
                status=status,
                error=error,
                model=live_model,
                result_size=result_size,
                elapsed_ms=elapsed_ms,
                usage=usage_snap,
            )
        if progress is not None:
            progress.on_tool_end(plugin.name, target, status, summary, error, tool_call_id)
        return wrap_untrusted(plugin.name, target, summary)

    _apply_signature(_tool, input_model, plugin.name, plugin.describe())
    _prepend_runctx(_tool)  # agent.tool needs the leading RunContext; the CLI path must not see it
    return _tool


def _apply_signature(func: Any, input_model: type, name: str, doc: str) -> None:
    """Give ``func`` a signature mirroring ONLY the input model's fields.

    Shared by BOTH the agent-tool wrapper (:func:`_make_tool`) and the Typer plugin
    command (:mod:`cairn.interfaces.plugin_cli`), so it must stay free of any
    agent-only concern. In particular it must NOT inject the leading ``RunContext``
    parameter — that is a PydanticAI-tool concern added separately by
    :func:`_prepend_runctx`. (Leaking it here once made Typer reject every
    ``cairn plugin <name>`` command at startup with
    ``Type not yet supported: RunContext[NoneType]``.)
    """
    params: list[inspect.Parameter] = []
    for fname, finfo in input_model.model_fields.items():
        if finfo.is_required():
            default: Any = inspect.Parameter.empty
        else:
            default = (
                finfo.default if finfo.default is not PydanticUndefined else inspect.Parameter.empty
            )
        params.append(
            inspect.Parameter(
                fname,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=finfo.annotation,
                default=default,
            )
        )
    func.__signature__ = inspect.Signature(parameters=params)  # type: ignore[attr-defined]
    func.__annotations__ = {p.name: p.annotation for p in params}
    func.__name__ = name
    func.__doc__ = doc


def _prepend_runctx(func: Any) -> None:
    """Prepend an ``rctx: RunContext[None]`` param so ``agent.tool`` accepts ``func``.

    This is the ONLY place the agent-tool ``RunContext`` concern enters a signature.
    PydanticAI excludes the index-0 RunContext parameter from the LLM-facing JSON
    schema, so the model still sees only the input-model fields. Kept out of the
    shared :func:`_apply_signature` (also used by the Typer plugin command) so a
    ``RunContext`` annotation can never reach a Click parameter.
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    if params and params[0].name == "rctx":
        return  # idempotent — already has the leading RunContext param
    params.insert(
        0,
        inspect.Parameter(
            "rctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=RunContext[None]
        ),
    )
    func.__signature__ = inspect.Signature(parameters=params)  # type: ignore[attr-defined]
    anns = dict(func.__annotations__)
    anns["rctx"] = RunContext[None]
    func.__annotations__ = anns
