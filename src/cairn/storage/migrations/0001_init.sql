-- Migration 0001: initial schema.
-- Canonical copy of storage/schema.sql. Forward-only migrations live here;
-- db.init() applies schema.sql directly today; a migration runner can adopt
-- these files later without changing the schema.

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    model        TEXT,
    tool         TEXT    NOT NULL,
    target       TEXT,
    params_json  TEXT,
    status       TEXT    NOT NULL,
    result_size  INTEGER,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS cases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT,
    created      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS entities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      INTEGER REFERENCES cases(id),
    type         TEXT    NOT NULL,
    value        TEXT    NOT NULL,
    attrs_json   TEXT,
    source       TEXT,
    first_seen   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(case_id, type, value, source)
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      INTEGER REFERENCES cases(id),
    role         TEXT    NOT NULL,
    content      TEXT,
    ts           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_tool   ON audit_log(tool);
CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_entities_val ON entities(type, value);
