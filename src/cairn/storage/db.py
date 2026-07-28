"""SQLite database connection + schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from cairn.core import paths

_SCHEMA = Path(__file__).resolve().parent / "schema.sql"


class Database:
    """Thin wrapper over a sqlite3 connection."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or paths.db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def init(self) -> None:
        """Apply the schema (idempotent), then reconcile columns on legacy DBs."""
        sql = _SCHEMA.read_text(encoding="utf-8")
        self.conn.executescript(sql)
        self.conn.commit()
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """Add columns introduced after the initial schema to existing DBs.

        ``CREATE TABLE IF NOT EXISTS`` won't alter an existing table, so columns
        added in later revisions are back-filled here with guarded
        ``ALTER TABLE ADD COLUMN``. Each statement runs only if the column is
        absent. Idempotent and safe on fresh DBs (columns already present).
        """
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        additions = {
            "elapsed_ms": "ALTER TABLE audit_log ADD COLUMN elapsed_ms REAL",
            "usage_json": "ALTER TABLE audit_log ADD COLUMN usage_json TEXT",
        }
        for col, ddl in additions.items():
            if col not in cols:
                self.conn.execute(ddl)
        self.conn.commit()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
