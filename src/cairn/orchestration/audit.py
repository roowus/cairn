"""Append-only audit log writer."""

from __future__ import annotations

import json
from typing import Any

from cairn.core.security import redact_secrets
from cairn.storage.db import Database


class AuditWriter:
    """Records every tool call to the ``audit_log`` table."""

    def __init__(self, db: Database, *, model_name: str | None = None) -> None:
        self._db = db
        self._model = model_name
        # Optional tag identifying the parallel session that owns this writer.
        # Set by a SessionPool on each pooled session (None on the single-session
        # path). Carried into every audit row so a shared DB can be queried per
        # session. Defaulting to None keeps every existing caller unchanged.
        self._session_id: str | None = None

    @property
    def model_name(self) -> str | None:
        return self._model

    @model_name.setter
    def model_name(self, value: str | None) -> None:
        self._model = value

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._session_id = value

    def record(
        self,
        *,
        tool: str,
        target: str | None,
        params: dict[str, Any],
        status: str,
        error: str | None = None,
        model: str | None = None,
        result_size: int = 0,
        elapsed_ms: float | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        params_json = json.dumps(redact_secrets(params), default=str)
        usage_json = json.dumps(usage, default=str, sort_keys=True) if usage else None
        self._db.execute(
            "INSERT INTO audit_log "
            "(model, tool, target, params_json, status, result_size, error, "
            "elapsed_ms, usage_json, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                model or self._model,
                tool,
                target,
                params_json,
                status,
                result_size,
                error,
                round(elapsed_ms, 2) if elapsed_ms is not None else None,
                usage_json,
                self._session_id,
            ),
        )
