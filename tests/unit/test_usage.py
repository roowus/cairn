"""Usage & cost accounting — tracker, snapshots, history aggregation, migration.

Covers the per-call-vs-cumulative invariant (the audit snapshot must store the
per-call delta, not the running total, or aggregate_history over-counts), the
runtime column migration on legacy DBs, and the live session accounting.
"""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from cairn.execution.base import BasePlugin, CostSpec, PluginInput, PluginOutput, cost_label
from cairn.orchestration.audit import AuditWriter
from cairn.orchestration.session import Session
from cairn.orchestration.usage import (
    SourceUsage,
    UsageTracker,
    aggregate_history,
    snapshot,
)
from cairn.storage.db import Database


class _In(PluginInput):
    pass


class _Out(PluginOutput):
    pass


class _FreePlugin(BasePlugin):
    name = "unit_free_usage"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    __doc__ = "free"

    async def run(self, inp, ctx):  # type: ignore[override]
        return _Out(source="unit_free_usage", summary_markdown="ok")


class _PaidPlugin(BasePlugin):
    name = "unit_paid_usage"
    category = "identity"
    requires_key = None
    input_model = _In
    output_model = _Out
    cost = CostSpec(unit="credits", per_call=2.0, paid=True, note="2 credits/call")
    __doc__ = "paid"

    async def run(self, inp, ctx):  # type: ignore[override]
        # emulate a service that reports a credit balance
        return _Out(
            source="unit_paid_usage",
            summary_markdown="ok",
            rate_limit_remaining=5,
            credits_remaining=98,
        )


# --- tracker accounting ------------------------------------------------------


def test_record_accumulates_calls_time_and_consumed():
    tr = UsageTracker()
    p = _PaidPlugin()
    out = _Out(
        source="unit_paid_usage",
        summary_markdown="ok",
        rate_limit_remaining=5,
        credits_remaining=98,
    )
    tr.record(p, elapsed_ms=100.0, status="ok", output=out)
    tr.record(p, elapsed_ms=150.0, status="ok", output=out)
    su = tr.record(p, elapsed_ms=50.0, status="error")  # errors don't consume
    assert su.calls == 3
    assert su.ok == 2
    assert su.errors == 1
    assert su.elapsed_ms == 300.0
    assert su.consumed == 4.0  # 2 ok calls * 2 credits
    assert su.paid is True
    assert su.unit == "credits"
    # dynamic signals carried through from the outputs
    assert su.rate_remaining == 5
    assert su.credits_remaining == 98


def test_free_plugin_inherits_default_cost():
    tr = UsageTracker()
    su = tr.record(_FreePlugin(), elapsed_ms=10.0, status="ok")
    assert su.tier == "free"
    assert su.paid is False
    assert su.unit == "calls"
    assert su.consumed == 1.0
    assert not su.is_metered


def test_totals():
    tr = UsageTracker()
    tr.record(_PaidPlugin(), elapsed_ms=100.0, status="ok")  # 2 credits
    tr.record(_FreePlugin(), elapsed_ms=20.0, status="ok")
    assert tr.total_calls() == 2
    assert tr.total_elapsed_ms() == 120.0
    assert tr.total_paid_consumed() == 2.0


# --- per-call snapshot invariant (the over-counting bug) ---------------------


def test_snapshot_stores_per_call_not_cumulative():
    tr = UsageTracker()
    p = _PaidPlugin()  # per_call=2
    tr.record(p, elapsed_ms=10.0, status="ok")  # cumulative consumed now 2
    su = tr.record(p, elapsed_ms=10.0, status="ok")  # cumulative consumed now 4
    snap = snapshot(su, per_call_consumed=2.0)
    assert snap["consumed"] == 2.0  # the per-call delta, NOT the cumulative 4


def test_snapshot_defaults_to_cumulative_when_no_delta_given():
    su = SourceUsage(name="x", consumed=9.0)
    assert snapshot(su)["consumed"] == 9.0


# --- checkpoint / delta (REPL turn-end) --------------------------------------


def test_checkpoint_delta_is_per_turn():
    tr = UsageTracker()
    snap = tr.checkpoint()
    tr.record(_FreePlugin(), elapsed_ms=5.0, status="ok")
    tr.record(_PaidPlugin(), elapsed_ms=5.0, status="ok")
    delta = tr.delta(snap)
    names = {d.name for d in delta}
    assert names == {"unit_free_usage", "unit_paid_usage"}
    paid = next(d for d in delta if d.name == "unit_paid_usage")
    assert paid.calls == 1 and paid.consumed == 2.0 and paid.elapsed_ms == 5.0


def test_delta_omits_untouched_sources():
    tr = UsageTracker()
    tr.record(_FreePlugin(), elapsed_ms=1.0, status="ok")  # before checkpoint
    snap = tr.checkpoint()
    tr.record(_PaidPlugin(), elapsed_ms=1.0, status="ok")  # after
    delta = tr.delta(snap)
    assert [d.name for d in delta] == ["unit_paid_usage"]


# --- cost_label --------------------------------------------------------------


def test_cost_label():
    assert cost_label(_FreePlugin()) == "free"
    assert cost_label(_PaidPlugin()) == "credits · paid"
    assert cost_label(
        type(  # daily-quota plugin
            "P",
            (BasePlugin,),
            {
                "name": "p",
                "category": "x",
                "input_model": _In,
                "output_model": _Out,
                "cost": CostSpec(unit="lookups/day", daily_quota=50),
                "run": lambda self, inp, ctx: None,
            },
        )()
    ) == "50/day"


# --- history aggregation (regression: must NOT over-count) -------------------


def test_aggregate_history_sums_per_call_consumed(tmp_path):
    db = Database(tmp_path / "t.db")
    db.init()
    aw = AuditWriter(db, model_name="m")
    # Simulate 3 calls of a 2-credit paid source. Each row stores the PER-CALL
    # delta (2), so the sum must be 6 — not 2+4+6=12 (cumulative) .
    for _ in range(3):
        snap = snapshot(
            SourceUsage(name="unit_paid_usage", unit="credits", paid=True, consumed=999),
            per_call_consumed=2.0,
        )
        aw.record(
            tool="unit_paid_usage", target="x", params={}, status="ok",
            elapsed_ms=10.0, usage=snap,
        )
    db.close()
    db2 = Database(tmp_path / "t.db")
    db2.init()
    rows = aggregate_history(db2)
    paid = next(r for r in rows if r.name == "unit_paid_usage")
    assert paid.calls == 3
    assert paid.consumed == 6.0  # 3 * 2, NOT over-counted
    assert paid.paid is True
    db2.close()


def test_aggregate_history_tolerates_rows_without_usage_json(tmp_path):
    db = Database(tmp_path / "t.db")
    db.init()
    # old-style rows: no usage_json, no elapsed_ms (pre-migration data)
    db.execute(
        "INSERT INTO audit_log (tool, target, params_json, status) VALUES (?,?,?,?)",
        ("old_plugin", "x", "{}", "ok"),
    )
    rows = aggregate_history(db)
    r = next(x for x in rows if x.name == "old_plugin")
    assert r.calls == 1 and r.consumed == 0.0
    db.close()


# --- runtime column migration on a legacy DB ---------------------------------


def test_init_adds_usage_columns_to_legacy_db(tmp_path):
    """A DB created with the pre-0002 schema gets elapsed_ms + usage_json added."""
    db = Database(tmp_path / "legacy.db")
    # Create the OLD schema (no elapsed_ms / usage_json), mimicking a prior install.
    db.conn.executescript(
        """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            model TEXT,
            tool TEXT NOT NULL,
            target TEXT,
            params_json TEXT,
            status TEXT NOT NULL,
            result_size INTEGER,
            error TEXT
        );
        """
    )
    db.conn.commit()
    db.conn.close()
    db._conn = None

    # Reopen via init() → _ensure_columns must add the missing columns.
    db2 = Database(tmp_path / "legacy.db")
    db2.init()
    cols = {r["name"] for r in db2.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert {"elapsed_ms", "usage_json"} <= cols
    # and the existing row survived
    assert db2.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"] == 0
    db2.close()


def test_init_is_idempotent_on_fresh_db(tmp_path):
    db = Database(tmp_path / "f.db")
    db.init()
    db.init()  # second init must not error / not duplicate columns
    cols = [r["name"] for r in db.execute("PRAGMA table_info(audit_log)").fetchall()]
    assert cols.count("elapsed_ms") == 1
    assert cols.count("usage_json") == 1
    db.close()


# --- end-to-end through a real Session ---------------------------------------


async def test_session_records_per_call_usage_and_history(fake_settings, tmp_path):
    """A real turn writes a usage snapshot; history reads it back without over-count."""
    from cairn.execution.registry import PluginRegistry

    reg = PluginRegistry()
    reg.register(_PaidPlugin())
    session = Session(
        settings=fake_settings,
        registry=reg,
        model=TestModel(),
        db=Database(tmp_path / "e2e.db"),
    )
    try:
        await session.ask(
            "x", model=TestModel(call_tools=["unit_paid_usage"], custom_output_text="done")
        )
    finally:
        await session.aclose()

    db = Database(tmp_path / "e2e.db")
    db.init()
    rows = aggregate_history(db)
    paid = next(r for r in rows if r.name == "unit_paid_usage")
    assert paid.calls == 1
    assert paid.consumed == 2.0  # per_call=2, one call
    assert paid.paid is True
    db.close()
