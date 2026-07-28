-- Migration 0003: parallel-session tagging on audit_log.
-- Adds session_id (the parallel session that wrote the row; NULL on the
-- single-session path) so a shared audit DB can be queried per session.
--
-- As with 0002, db._ensure_columns() applies this guarded against
-- PRAGMA table_info at runtime, and schema.sql now includes the column for
-- fresh databases. This file documents the change for a future migration
-- runner; db.init() applies schema.sql directly.

ALTER TABLE audit_log ADD COLUMN session_id TEXT;
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);
