"""SessionPool: N concurrent sessions, one loop, shared audit + merged graph.

A TestModel drives fake plugins through real ``Session``s owned by a
``SessionPool``; we assert the Semaphore caps concurrency, per-session budgets
halt further turns, cancel-by-id stops an in-flight turn, the shared audit file
is tagged per session, and merged graphs de-dup by the entity node key. No real
LLM or network.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.models.test import TestModel

from cairn.execution.base import BasePlugin, CostSpec, Entity, PluginInput, PluginOutput
from cairn.execution.registry import PluginRegistry
from cairn.orchestration.session_pool import BudgetExceeded, SessionBudget, SessionPool


class _In(PluginInput):
    pass


class _Out(PluginOutput):
    pass


def _registry(*plugins: BasePlugin) -> PluginRegistry:  # type: ignore[type-arg]
    reg = PluginRegistry()
    for p in plugins:
        reg.register(p)
    return reg


class _CountingPlugin(BasePlugin):
    """Paid plugin that records peak concurrency and mines a fixed entity."""

    name = "fake_parallel_plugin"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    cost = CostSpec(paid=True, per_call=1.0)
    __doc__ = "fake parallel plugin for pool tests"

    def __init__(self, state: dict[str, int], delay: float = 0.03) -> None:
        self._state = state
        self._delay = delay

    async def run(self, inp, ctx):  # type: ignore[override]
        self._state["live"] += 1
        if self._state["live"] > self._state["max"]:
            self._state["max"] = self._state["live"]
        try:
            await asyncio.sleep(self._delay)
            return _Out(
                source="fake_parallel_plugin",
                summary_markdown="ok",
                entities=[Entity(type="ip", value="203.0.113.9")],
            )
        finally:
            self._state["live"] -= 1


def _tm() -> TestModel:
    return TestModel(call_tools=["fake_parallel_plugin"], custom_output_text="done")


async def test_pool_caps_concurrency(fake_settings):
    state = {"live": 0, "max": 0}
    pool = SessionPool(
        settings=fake_settings,
        max_concurrent=2,
        shared_registry=_registry(_CountingPlugin(state)),
    )
    sids = [pool.spawn(f"q{i}", model=_tm()) for i in range(6)]
    # FIFO spawn order is preserved while live.
    assert [ps.session_id for ps in pool.list_live()] == sids
    results = await pool.run_all()

    assert len(results) == 6
    # the cap was respected (never more than 2 live) and actually reached.
    assert state["max"] <= 2
    assert state["max"] == 2
    await pool.aclose()
    assert pool.list_live() == []  # cleared on aclose


async def test_capacity_property(fake_settings):
    pool = SessionPool(settings=fake_settings, max_concurrent=3, shared_registry=_registry())
    assert pool.capacity == 3
    await pool.aclose()


def test_rejects_zero_capacity(fake_settings):
    with pytest.raises(ValueError):
        SessionPool(settings=fake_settings, max_concurrent=0, shared_registry=_registry())


async def test_budget_refuses_turn_over_call_cap(fake_settings):
    """A session at its call cap refuses the next turn before it runs.

    The guard reads the observer-only tracker and raises from the pool (never
    inside the tracker). We pre-seed usage via the same ``record`` API the tool
    closure uses — TestModel doesn't re-invoke tools across turns, so seeding is
    the deterministic way to put a session at its cap.
    """
    state = {"live": 0, "max": 0}
    plugin = _CountingPlugin(state, delay=0.0)
    pool = SessionPool(
        settings=fake_settings,
        max_concurrent=1,
        shared_registry=_registry(plugin),
    )
    sid = pool.spawn("q", budget=SessionBudget(max_calls=2), model=_tm())
    sess = pool.get(sid).session
    sess.usage.record(plugin, elapsed_ms=1.0, status="ok")
    sess.usage.record(plugin, elapsed_ms=1.0, status="ok")
    assert sess.usage.total_calls() == 2
    # 2 calls already >= cap of 2 → next turn refused before it runs
    with pytest.raises(BudgetExceeded):
        await pool.run(sid, model=_tm())
    await pool.aclose()


async def test_budget_refuses_turn_over_spend_cap(fake_settings):
    state = {"live": 0, "max": 0}
    plugin = _CountingPlugin(state, delay=0.0)  # paid, per_call=1.0
    pool = SessionPool(
        settings=fake_settings,
        max_concurrent=1,
        shared_registry=_registry(plugin),
    )
    sid = pool.spawn("q", budget=SessionBudget(max_spend=1.0), model=_tm())
    sess = pool.get(sid).session
    sess.usage.record(plugin, elapsed_ms=1.0, status="ok")  # spend 1.0
    assert sess.usage.total_paid_consumed() == pytest.approx(1.0)
    # spend 1.0 >= cap 1.0 → next turn refused
    with pytest.raises(BudgetExceeded):
        await pool.run(sid, model=_tm())
    await pool.aclose()


def test_session_budget_exceeded_by():
    b = SessionBudget(max_calls=3, max_spend=None)
    assert not b.exceeded_by(calls=2, spend=0.0)
    assert b.exceeded_by(calls=3, spend=0.0)  # boundary: >=
    b2 = SessionBudget(max_spend=5.0)
    assert not b2.exceeded_by(calls=0, spend=4.9)
    assert b2.exceeded_by(calls=0, spend=5.0)  # boundary: >=
    assert not SessionBudget().exceeded_by(calls=9999, spend=9999.0)  # unbounded


async def test_cancel_in_flight_turn(fake_settings):
    class _SlowPlugin(BasePlugin):
        name = "fake_slow_plugin"
        category = "identity"
        requires_key = None
        input_model = _In
        output_model = _Out
        __doc__ = "slow plugin"

        async def run(self, inp, ctx):  # type: ignore[override]
            await asyncio.sleep(5)
            return _Out(source="fake_slow_plugin", summary_markdown="nope")

    pool = SessionPool(
        settings=fake_settings,
        max_concurrent=1,
        shared_registry=_registry(_SlowPlugin()),
    )
    sid = pool.spawn("q", model=TestModel(call_tools=["fake_slow_plugin"]))
    task = asyncio.create_task(pool.run(sid, model=TestModel(call_tools=["fake_slow_plugin"])))
    await asyncio.sleep(0.05)  # let it enter the slow tool
    assert pool.cancel(sid) is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert pool.get(sid).error == "cancelled"
    # cancelling an already-done / unknown session is a no-op
    assert pool.cancel(sid) is False
    await pool.aclose()


async def test_audit_rows_tagged_with_session_id(fake_settings):
    state = {"live": 0, "max": 0}
    pool = SessionPool(
        settings=fake_settings,
        max_concurrent=2,
        shared_registry=_registry(_CountingPlugin(state, delay=0.0)),
    )
    sid1 = pool.spawn("look up 1", model=_tm())
    sid2 = pool.spawn("look up 2", model=_tm())
    await pool.run(sid1, model=_tm())
    await pool.run(sid2, model=_tm())
    await pool.aclose()

    # sessions share the audit FILE; either connection sees both sessions' rows.
    from cairn.storage.db import Database

    db = Database(fake_settings.data_dir / "cairn.db")
    rows = db.execute(
        "SELECT session_id FROM audit_log WHERE tool = 'fake_parallel_plugin'"
    ).fetchall()
    tagged = {r["session_id"] for r in rows}
    assert tagged == {sid1, sid2}


async def test_merge_graphs_dedups_across_sessions(fake_settings):
    state = {"live": 0, "max": 0}
    pool = SessionPool(
        settings=fake_settings,
        max_concurrent=2,
        shared_registry=_registry(_CountingPlugin(state, delay=0.0)),
    )
    sid1 = pool.spawn("a", model=_tm())
    sid2 = pool.spawn("b", model=_tm())
    await pool.run(sid1, model=_tm())
    await pool.run(sid2, model=_tm())

    merged = pool.merge_graphs()
    ip_nodes = [n for n, d in merged.graph.nodes(data=True) if d.get("type") == "ip"]
    # both sessions mined the SAME fixed entity (ip:203.0.113.9) → one node.
    assert len(ip_nodes) == 1
    await pool.aclose()


async def test_unknown_session_raises(fake_settings):
    pool = SessionPool(settings=fake_settings, shared_registry=_registry())
    with pytest.raises(KeyError):
        await pool.run("nope")
    await pool.aclose()
