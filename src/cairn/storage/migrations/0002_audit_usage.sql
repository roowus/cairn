-- Migration 0002: usage/cost columns on audit_log.
-- Adds elapsed_ms (per-call wall-clock, ms) and usage_json (per-call cost/quota
-- snapshot from cairn.orchestration.usage.snapshot) to the append-only audit log.
--
-- SQLite has no IF NOT EXISTS for ADD COLUMN, so db._ensure_columns() applies
-- these guarded against PRAGMA table_info at runtime. This file documents the
-- change for a future migration runner; db.init() applies schema.sql directly
-- (which now includes these columns for fresh databases).

ALTER TABLE audit_log ADD COLUMN elapsed_ms REAL;
ALTER TABLE audit_log ADD COLUMN usage_json TEXT;
