"""A Cairn session: ties the agent, context, audit, and graph together.

Build one per investigation, call :meth:`ask` repeatedly for multi-turn dialogue,
and :meth:`aclose` when done. The session owns an ``httpx.AsyncClient`` and a
SQLite connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
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
from cairn.storage import sessions as sessions_store
from cairn.storage.db import Database
from cairn.storage.graph_store import NetworkXGraphStore

_log = get_logger("cairn.session")

COMPACTION_PROMPT = (
    "Summarize this Cairn investigation so far in faithful detail: the target(s) "
    "investigated, key findings from tool calls (cite which tool/source produced "
    "each), entities discovered and pivoted on, and open threads / next steps not "
    "yet taken. Be concise and do not invent details not supported by the tool "
    "results. This summary will replace the prior conversation as context."
)


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
        session_id: str | None = None,
        persist: bool = False,
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
        # JSONL session id — decoupled from audit.session_id (which is set by
        # SessionPool for pooled sessions and stays None on the single-session
        # path). 12-hex matches SessionPool's format so /sessions lists both.
        self.session_id = session_id or uuid.uuid4().hex[:12]
        # When True, each successful turn is appended to sessions_dir()/id.jsonl
        # (header lazily written on turn 1). Headless/default stays False so a
        # one-shot `cairn search` writes nothing.
        self.persist = persist
        self._header_written = False  # header lazily written on first persisted turn
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
            if self.persist:
                # Lazily write the header on turn 1, then append just this run's
                # delta (new_messages() == all_messages()[_new_message_index:]).
                # Cancelled turns never reach here (CancelledError re-raised
                # above), so a half-finished turn is never persisted.
                if not self._header_written:
                    sessions_store.save_header(
                        self.session_id,
                        model=self.model_name,
                        prompt=prompt,  # iter_turn param == first user prompt on turn 1
                        turns=len(self.history),
                    )
                    self._header_written = True
                sessions_store.append_turn(self.session_id, run_result.new_messages())
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

    def load_history(self, session_id: str) -> list[Any]:
        """Replace history with a persisted session's messages (for /resume).

        Marks the header as already on disk so subsequent turns append rather
        than rewrite. The session's JSONL id is adopted as the live id so the
        resumed conversation continues to grow the same file.
        """
        self.history = sessions_store.load(session_id)
        self.session_id = session_id
        self._header_written = True  # header already on disk → appends, no rewrite
        return self.history

    async def compact(self) -> tuple[int, int]:
        """Summarize the conversation; replace history with the summary turn.

        Returns ``(messages_before, messages_after)``. The summarization turn is
        run with ``persist=False`` so it isn't appended to the live file;
        afterwards the file is rewritten with just the compacted
        ``[ModelRequest, ModelResponse]`` pair so on-disk state equals in-memory
        state.

        Note: with a real model that calls tools mid-summary, ``new_messages()``
        is longer (request → tool parts → response), and the
        ``self.history[n_before:]`` slice still captures the whole compaction
        turn. ``TestModel`` (no tools) yields exactly a 2-message turn.
        """
        if not self.history:
            return (0, 0)
        n_before = len(self.history)
        was_persist = self.persist
        self.persist = False
        try:
            await self.ask(COMPACTION_PROMPT)
        finally:
            self.persist = was_persist
        # history is now old_history + [compaction request, compaction response];
        # keep only the compaction turn as the new durable context. The system
        # prompt is injected by Agent(system_prompt=...) each run, so it does not
        # need to be re-added here. A trailing ModelResponse means the next user
        # prompt appends as a clean ModelRequest (no two consecutive user turns).
        self.history = self.history[n_before:]
        if self.persist and self._header_written:
            sessions_store.save_header(
                self.session_id,
                model=self.model_name,
                prompt=self.history[0].parts[0].content if self.history else "",
                turns=len(self.history),
            )
            sessions_store.append_turn(self.session_id, self.history)
        return (n_before, len(self.history))

    def fork_snapshot(self) -> str:
        """Write the current history under a fresh session_id; return the new id.

        Used by ``/fork`` so the user can branch an investigation without
        disturbing the live session's file. The new file is a complete snapshot
        (header + every current message), resumable via ``/resume <new_id>``.
        """
        new_id = uuid.uuid4().hex[:12]
        sessions_store.save_header(
            new_id,
            model=self.model_name,
            prompt=(self.history[0].parts[0].content if self.history else ""),
            turns=len(self.history),
        )
        sessions_store.append_turn(new_id, self.history)
        return new_id

    def graph_summary(self) -> str:
        return self.graph.summary()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.db.close()

    async def aclose(self) -> None:
        await close_context(self.ctx)
        self.close()
