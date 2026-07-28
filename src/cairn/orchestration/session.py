"""A Cairn session: ties the agent, context, audit, and graph together.

Build one per investigation, call :meth:`ask` repeatedly for multi-turn dialogue,
and :meth:`aclose` when done. The session owns an ``httpx.AsyncClient`` and a
SQLite connection.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.usage import RunUsage

from cairn.core.config import Settings, load_settings, require_llm
from cairn.core.errors import ConfigError
from cairn.core.logging import get_logger
from cairn.execution.registry import PluginRegistry, discover
from cairn.execution.runner import build_context, close_context
from cairn.orchestration.audit import AuditWriter
from cairn.orchestration.events import TurnEvent, normalize
from cairn.orchestration.tool_adapter import register_tools
from cairn.orchestration.usage import UsageTracker
from cairn.reasoning.agent import build_model
from cairn.reasoning.catalog import apply_profile, current_profile_name, find_profile
from cairn.reasoning.system_prompt import build_system_prompt
from cairn.storage.db import Database
from cairn.storage.graph_store import NetworkXGraphStore

_log = get_logger("cairn.session")


class Session:
    """One investigation: agent + context + audit + graph + history."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        registry: PluginRegistry | None = None,
        model: Any | None = None,
        agent: Agent | None = None,
        db: Database | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        require_llm(self.settings)

        self.db = db or Database(self.settings.data_dir / "cairn.db")
        self.db.init()
        self.graph = NetworkXGraphStore()
        self.registry = registry or discover()
        self.ctx = build_context(self.settings)
        self.model = model or build_model(self.settings)
        model_name = getattr(self.model, "model_name", None) or self.settings.llm.model or "unknown"

        self.audit = AuditWriter(self.db, model_name=model_name)
        self.usage = UsageTracker()
        # Cumulative LLM token usage across turns (merged from each run's RunUsage).
        # Observer-only: never influences execution; surfaced by the statusline.
        self.llm_usage = RunUsage()
        self.agent = agent or Agent(
            self.model,
            system_prompt=build_system_prompt(self.settings),
            output_type=str,
            retries=2,
        )
        self._tools = register_tools(
            self.agent,
            self.registry,
            self.ctx,
            audit=self.audit,
            graph=self.graph,
            usage=self.usage,
            model_name=model_name,
        )
        self.history: list[Any] = []
        # Most recent turn's final output. Set by iter_turn() on successful
        # completion; left untouched on cancel. ask() returns it after draining.
        self.last_output: str = ""
        _log.info("session ready: %d tool(s), model=%s", self._tools, model_name)

    @property
    def tool_count(self) -> int:
        return self._tools

    @property
    def model_name(self) -> str:
        return (
            getattr(self.model, "model_name", None)
            or self.settings.llm.model
            or current_profile_name(self.settings)
            or "unknown"
        )

    def switch_model(self, name: str) -> str:
        """Switch the live agent to a named profile (see ``/model`` in the REPL).

        Rebuilds the PydanticAI model and points the existing agent at it. Tool
        registrations and conversation history are preserved. Raises
        :class:`~cairn.core.errors.ConfigError` if the name is unknown or the
        profile has no credentials.
        """
        profile = find_profile(name)
        if profile is None:
            raise ConfigError(
                f"Unknown model {name!r}. Try /model for the list "
                "(grok, glm, ollama, …)."
            )
        apply_profile(self.settings, profile)
        self.model = build_model(self.settings)
        self.agent.model = self.model
        self.audit.model_name = self.model_name
        _log.info("switched model → %s", self.model_name)
        return self.model_name

    async def iter_turn(
        self, prompt: str, *, progress: Any = None, model: Any | None = None
    ) -> AsyncGenerator[TurnEvent, None]:
        """Stream one turn as a sequence of :data:`~cairn.orchestration.events.TurnEvent`s.

        Drives ``agent.iter()`` and normalizes each PydanticAI stream event through
        :func:`~cairn.orchestration.events.normalize` — the single module that knows
        PydanticAI's event classes, so any future API churn is a one-file patch.
        ``progress`` is the optional :class:`~cairn.orchestration.progress.Progress`
        observer that receives live tool-call notifications for this turn only.

        On successful completion this sets :attr:`history` (so multi-turn memory
        persists) and :attr:`last_output`; on ``asyncio.CancelledError`` (Esc /
        Ctrl-C) history is left untouched so the user can retry or pivot without a
        half-written model message. Tool execution still flows through the audited
        ``_tool`` closure — these events carry only text/thinking deltas and the
        tool-call lifecycle, never the result payload.
        """
        from cairn.orchestration.progress import NullProgress

        progress = progress or NullProgress()
        self.ctx.progress = progress
        progress.on_turn_start(prompt)
        run_result = None
        try:
            async with self.agent.iter(
                prompt, message_history=(self.history or None), model=model
            ) as run:
                async for node in run:
                    if not (
                        self.agent.is_model_request_node(node)
                        or self.agent.is_call_tools_node(node)
                    ):
                        continue
                    async with node.stream(run.ctx) as stream:
                        async for ev in stream:
                            tev = normalize(ev)
                            if tev is not None:
                                yield tev
                run_result = run.result
                if run_result is not None:
                    # Merge this turn's LLM token usage into the session total.
                    # Observer-only: surfaced by the statusline, never audited, never
                    # influences execution. Raw token counts sum correctly, but do NOT
                    # derive $/cost from llm_usage — RunUsage.__add__ warns it is not
                    # pricing-safe. On cancel this line is skipped (CancelledError is
                    # re-raised in the except below before we reach here), so a cancelled
                    # turn's spent tokens aren't folded in — an acceptable under-count
                    # for a presentation-only counter.
                    self.llm_usage = self.llm_usage + run.usage
        except asyncio.CancelledError:
            # Esc / Ctrl-C during a turn — leave history untouched so the user
            # can retry or pivot without a half-written model message.
            _log.info("turn cancelled")
            raise
        finally:
            self.ctx.progress = None
        if run_result is not None:
            self.history = run_result.all_messages()
            self.last_output = run_result.output
            progress.on_turn_end(run_result.output)

    async def ask(self, prompt: str, *, progress: Any = None, model: Any | None = None) -> str:
        """Run one turn and return the final output (the non-streaming path).

        A thin back-compat wrapper that drains :meth:`iter_turn` and returns
        :attr:`last_output`. Headless runs, tests, and any non-UI caller use this;
        the UI consumes :meth:`iter_turn` directly for live rendering. Both paths
        share the identical run (history, audit, usage) — only the rendering differs.
        """
        async for _ in self.iter_turn(prompt, progress=progress, model=model):
            pass
        return self.last_output

    def graph_summary(self) -> str:
        return self.graph.summary()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.db.close()

    async def aclose(self) -> None:
        await close_context(self.ctx)
        self.close()
