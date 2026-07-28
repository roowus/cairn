-- Cairn schema (applied on first run via db.init()).
-- The audit_log is append-only: there is no UPDATE/DELETE path for it in app code.

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    model        TEXT,
    tool         TEXT    NOT NULL,
    target       TEXT,
    params_json  TEXT,
    status       TEXT    NOT NULL,            -- 'ok' | 'error'
    result_size  INTEGER,
    error        TEXT,
    elapsed_ms   REAL,                        -- wall-clock of the tool call (ms)
    usage_json   TEXT,                        -- per-call cost/quota snapshot (see usage.snapshot)
    session_id   TEXT                         -- parallel session that wrote this row (None for single-session)
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
-- idx_audit_session is created in Database.init() after _ensure_columns adds
-- the session_id column (it cannot be created here on a legacy DB pre-migration).
