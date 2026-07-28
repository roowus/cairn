"""audit_log.session_id back-fill, AuditWriter tagging, and concurrent-write safety."""

from __future__ import annotations

import asyncio

from cairn.orchestration.audit import AuditWriter
from cairn.storage.db import Database


def test_session_id_backfilled_on_legacy_db(tmp_path):
    """A DB created before session_id existed gets the column on init()."""
    path = tmp_path / "legacy.db"
    # Hand-build a realistic pre-session_id audit_log (every column the schema
    # had before this change, minus session_id) so the index DDL in schema.sql
    # that references existing columns still applies.
    import sqlite3

    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE audit_log ("
        "id INTEGER PRIMARY KEY, ts TEXT, model TEXT, tool TEXT NOT NULL, "
        "target TEXT, params_json TEXT, status TEXT NOT NULL, result_size INTEGER, "
        "error TEXT, elapsed_ms REAL, usage_json TEXT)"
    )
    con.execute("INSERT INTO audit_log (tool, status) VALUES ('legacy_tool', 'ok')")
    con.commit()
    con.close()

    db = Database(path)
    db.init()
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert "session_id" in cols
    # existing rows back-fill to NULL, not a crash.
    row = db.execute("SELECT session_id FROM audit_log WHERE tool='legacy_tool'").fetchone()
    assert row["session_id"] is None
    db.close()


def test_session_id_present_on_fresh_db(tmp_path):
    db = Database(tmp_path / "fresh.db")
    db.init()
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert "session_id" in cols
    db.close()


def test_audit_writer_tags_session_id(tmp_path):
    db = Database(tmp_path / "t.db")
    db.init()
    writer = AuditWriter(db, model_name="m")

    # default: NULL
    writer.record(tool="t", target="x", params={}, status="ok")
    rows = db.execute("SELECT session_id FROM audit_log").fetchall()
    assert rows[-1]["session_id"] is None

    # tagged after the attribute is set (as a SessionPool does)
    writer.session_id = "sess-42"
    writer.record(tool="t", target="y", params={}, status="ok", elapsed_ms=1.0)
    rows = db.execute("SELECT session_id FROM audit_log WHERE target='y'").fetchall()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess-42"
    db.close()


def test_concurrent_writes_do_not_lock(tmp_path):
    """N separate connections writing to one WAL file must not raise 'database is locked'."""

    async def writer(i: int) -> None:
        db = Database(tmp_path / "shared.db")
        db.init()
        for _ in range(20):
            db.execute(
                "INSERT INTO audit_log (tool, status, session_id) VALUES (?, ?, ?)",
                (f"tool{i}", "ok", f"sess-{i}"),
            )
        db.close()

    async def main() -> None:
        # init once so the table exists before concurrent writers race.
        Database(tmp_path / "shared.db").init()
        await asyncio.gather(*(writer(i) for i in range(5)))

    asyncio.run(main())

    db = Database(tmp_path / "shared.db")
    total = db.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
    assert total == 5 * 20
    sids = {r["session_id"] for r in db.execute("SELECT session_id FROM audit_log").fetchall()}
    assert sids == {f"sess-{i}" for i in range(5)}
    db.close()
