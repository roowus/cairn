"""A pool of concurrently-running investigation sessions.

Cairn's single-session model — one :class:`~cairn.orchestration.session.Session`
per REPL/headless loop — is a throughput ceiling when an investigator wants
several independent lines of work at once (pivot on a domain here, enrich a
person there, triage a challenge pcap in a third). This module runs N sessions
concurrently on one asyncio loop, behind a Semaphore, sharing the plugin
registry and the audit *file* (every row tagged with the session that wrote it)
while keeping per-session history, graph, and usage isolated.

Invariants preserved
- **The hard-stop is unchanged.** Concurrency here is throughput/orchestration
  only — every session still rides the audited tool closure in
  :mod:`cairn.orchestration.tool_adapter`; every result is still wrapped in
  ``<untrusted_external_data>``. Nothing here relaxes Layer B.
- **``UsageTracker`` stays observer-only.** Spend/call ceilings are enforced
  *here* (the pool refuses to run a session's next turn once its tracker crosses
  a cap), never inside the tracker or a :class:`~cairn.orchestration.progress.Progress`
  hook.
- **No edit to ``Session``.** The pool constructs each
  ``Session(settings, registry=shared, db=None)`` and tracks session ids
  externally, so this is decoupled from the in-progress UI session-id work (U6)
  that will add a ``session_id`` attribute to ``Session``.

v1 is asyncio-on-one-loop (no subprocess workers); each session keeps its own
in-memory :class:`~cairn.storage.graph_store.NetworkXGraphStore` and the pool
merges them on demand. See ``docs/architecture/parallel-sessions.md``.

Shared audit, separate connections
    Every pooled session opens its own ``sqlite3`` connection to the same
    ``cairn.db`` file (the default ``Session`` behavior). WAL + ``busy_timeout``
    (set in :mod:`cairn.storage.db`) serialize the writes at the file level, and
    each ``Session.aclose`` closes only its own connection — so sharing the
    *file* (not the connection object) is both safe and gives the shared audit
    log issue #2 wants. Rows are tagged with the owning session's id.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cairn.core.config import Settings, load_settings
from cairn.core.logging import get_logger
from cairn.execution.registry import PluginRegistry, discover
from cairn.interfaces.interrupt import cancel_async_task, cancel_tasks
from cairn.orchestration.session import Session
from cairn.storage.graph_store import NetworkXGraphStore

_log = get_logger("cairn.pool")


class BudgetExceeded(Exception):
    """A pooled session's spend/call ceiling was reached — its next turn is refused."""


@dataclass
class SessionBudget:
    """Hard per-session ceilings enforced by the pool (None = unbounded).

    Enforced *between* turns (the pool checks before running a session's next
    turn), so a turn already in flight runs to completion. This keeps the
    observer-only :class:`~cairn.orchestration.usage.UsageTracker` contract
    intact — the tracker accumulates; the pool decides to stop.
    """

    max_spend: float | None = None
    max_calls: int | None = None

    def __post_init__(self) -> None:
        if self.max_calls is not None and self.max_calls < 0:
            raise ValueError("max_calls must be >= 0")
        if self.max_spend is not None and self.max_spend < 0:
            raise ValueError("max_spend must be >= 0")

    def exceeded_by(self, *, calls: int, spend: float) -> bool:
        return (self.max_calls is not None and calls >= self.max_calls) or (
            self.max_spend is not None and spend >= self.max_spend
        )


@dataclass
class PooledSession:
    """A live session's pool-side handle."""

    session_id: str
    prompt: str
    session: Session
    budget: SessionBudget | None
    answer: str | None = None
    error: str | None = None


class SessionPool:
    """Manages N concurrent ``Session``s behind a Semaphore with per-session budgets."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        max_concurrent: int | None = None,
        shared_registry: PluginRegistry | None = None,
        default_budget: SessionBudget | None = None,
        model_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        cap = (
            max_concurrent
            if max_concurrent is not None
            else self.settings.max_concurrent_sessions
        )
        if cap < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._cap = cap
        self._sem: asyncio.Semaphore = asyncio.Semaphore(self._cap)
        # Discover ONCE; share the registry across every session — the big
        # "cheaply instantiable" win (plugin discovery walks/imports every
        # module). Each session still builds its own agent+tools+http client.
        self._registry = shared_registry or discover()
        self._default_budget = default_budget
        self._model_factory = model_factory
        self._sessions: dict[str, PooledSession] = {}
        self._order: list[str] = []  # FIFO spawn order
        # The asyncio task currently running each session's turn (set inside
        # ``run`` via ``current_task`` so cancel-by-id works even when the caller
        # drives concurrency with ``asyncio.gather``).
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._closed = False

    @property
    def capacity(self) -> int:
        return self._cap

    def get(self, session_id: str) -> PooledSession | None:
        return self._sessions.get(session_id)

    def list_live(self) -> list[PooledSession]:
        """All pooled sessions in spawn (FIFO) order."""
        return [self._sessions[sid] for sid in self._order]

    def spawn(
        self,
        prompt: str,
        *,
        budget: SessionBudget | None = None,
        model: Any | None = None,
    ) -> str:
        """Construct a session and register it. Returns its id.

        Construction is cheap-ish (no LLM/network work — just agent + tool
        registration against the shared registry). The session does not run until
        :meth:`run` is called. ``budget`` overrides the pool default; the model
        defaults to ``model_factory()`` when set, else ``None`` (the session
        builds its own from settings). Raises :class:`~cairn.core.errors.ConfigError`
        if no LLM is configured (via ``Session.__init__`` → ``require_llm``).
        """
        if self._closed:
            raise RuntimeError("SessionPool is closed")
        sid = uuid.uuid4().hex[:12]
        if model is not None:
            eff_model = model
        elif self._model_factory is not None:
            eff_model = self._model_factory()
        else:
            eff_model = None
        session = Session(self.settings, registry=self._registry, model=eff_model)
        # Tag every audit row this session writes with its id (no Session edit).
        session.audit.session_id = sid
        ps = PooledSession(
            session_id=sid,
            prompt=prompt,
            session=session,
            budget=budget if budget is not None else self._default_budget,
        )
        self._sessions[sid] = ps
        self._order.append(sid)
        _log.info("spawned session %s (%d live)", sid, len(self._order))
        return sid

    async def run(
        self, session_id: str, prompt: str | None = None, *, model: Any | None = None
    ) -> str:
        """Run one turn on the session, gated by the pool Semaphore and budget.

        ``prompt`` defaults to the spawn prompt; ``model`` (e.g. a per-turn
        ``TestModel``) overrides the session's model for this turn. Returns the
        session's ``last_output``. Raises :class:`BudgetExceeded` if the session's
        usage has crossed its cap (checked before the turn, so an in-flight turn
        always completes). Safe to call repeatedly for multi-turn dialogue on one
        pooled session (history persists).
        """
        ps = self._require(session_id)
        if self._closed:
            raise RuntimeError("SessionPool is closed")
        # Budget guard: the pool is the enforcer; the tracker stays observer-only.
        self._check_budget(ps)
        async with self._sem:
            self._tasks[session_id] = asyncio.current_task()  # type: ignore[assignment]
            try:
                await ps.session.ask(prompt or ps.prompt, model=model)
                ps.answer = ps.session.last_output
                return ps.session.last_output
            except asyncio.CancelledError:
                ps.error = "cancelled"
                raise
            except Exception as exc:  # a failed turn is recorded, not fatal to the pool
                ps.error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                self._tasks.pop(session_id, None)

    async def run_all(self, *, model: Any | None = None) -> dict[str, str]:
        """Run every pooled session's stored prompt concurrently and return ``{id: answer}``.

        Convenience for "fire N independent investigations at once" — the
        Semaphore caps how many run simultaneously. Failed/cancelled sessions are
        omitted from the result (their ``error`` is on the :class:`PooledSession`).
        """
        if self._closed:
            raise RuntimeError("SessionPool is closed")

        async def _one(sid: str) -> tuple[str, str | None]:
            with contextlib.suppress(Exception):
                return sid, await self.run(sid, model=model)
            return sid, None

        pairs = await asyncio.gather(*(_one(sid) for sid in self._order))
        return {sid: ans for sid, ans in pairs if ans is not None}

    def cancel(self, session_id: str) -> bool:
        """Cancel a session's in-flight turn. Returns True if a cancel was issued."""
        task = self._tasks.get(session_id)
        if task is None:
            return False
        return cancel_async_task(task)

    def cancel_all(self) -> int:
        """Cancel every session's in-flight turn. Returns how many were cancelled."""
        return cancel_tasks(list(self._tasks.values()))

    def merge_graphs(self) -> NetworkXGraphStore:
        """Merge every session's entity graph into one, de-duping by ``type:value``.

        Call after the sessions have drained (their graphs are quiescent).
        """
        merged = NetworkXGraphStore()
        for ps in self._sessions.values():
            merged.merge(ps.session.graph)
        return merged

    def total_calls(self) -> int:
        """Aggregate tool-call count across all sessions (the global view)."""
        return sum(ps.session.usage.total_calls() for ps in self._sessions.values())

    def total_paid_consumed(self) -> float:
        """Aggregate paid-source spend across all sessions."""
        return sum(ps.session.usage.total_paid_consumed() for ps in self._sessions.values())

    async def aclose(self) -> None:
        """Cancel anything in flight, then close every session (its own db connection)."""
        self._closed = True
        self.cancel_all()
        for ps in self._sessions.values():
            with contextlib.suppress(Exception):
                await ps.session.aclose()
        self._sessions.clear()
        self._order.clear()

    # --- internals -----------------------------------------------------------

    def _require(self, session_id: str) -> PooledSession:
        ps = self._sessions.get(session_id)
        if ps is None:
            raise KeyError(f"unknown session {session_id!r}")
        return ps

    def _check_budget(self, ps: PooledSession) -> None:
        if ps.budget is None:
            return
        if ps.budget.exceeded_by(
            calls=ps.session.usage.total_calls(),
            spend=ps.session.usage.total_paid_consumed(),
        ):
            raise BudgetExceeded(
                f"session {ps.session_id} exceeded its budget "
                f"(calls={ps.session.usage.total_calls()}/"
                f"{ps.budget.max_calls}, "
                f"spend={ps.session.usage.total_paid_consumed()}/"
                f"{ps.budget.max_spend})"
            )
