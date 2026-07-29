"""JSONL conversation snapshots — /resume, /fork, /compact backing store.

One file per session at ``sessions_dir() / f"{session_id}.jsonl"``. Line 1 is a
header (``{"header": SessionMeta-dict}``); every subsequent line is one message
(``{"msg": <ModelMessage dump>}``), serialized via the singleton
``ModelMessagesTypeAdapter``. Malformed lines are skipped+logged, never raised.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pydantic
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,  # singleton TypeAdapter INSTANCE — use directly, do NOT instantiate
)

from cairn.core.logging import get_logger
from cairn.core.paths import sessions_dir

_log = get_logger("cairn.sessions")


class SessionMeta(pydantic.BaseModel):
    session_id: str
    model: str
    created_at: str  # ISO-8601 UTC
    prompt: str  # first user prompt
    turns: int  # len(history) at write time


def _path(session_id: str) -> Path:
    return sessions_dir() / f"{session_id}.jsonl"


def save_header(
    session_id: str, *, model: str, prompt: str, turns: int
) -> SessionMeta:
    """Truncate/create the session file and write its header line.

    Returns the constructed :class:`SessionMeta`. The parent dir is mkdir'd
    defensively — ``ensure_dirs()`` already creates it on REPL startup, but this
    mirrors how ``Database.__init__`` mkdirs its own parent so a direct caller
    (test, /fork, /compact) never has to know about that contract.
    """
    _path(session_id).parent.mkdir(parents=True, exist_ok=True)
    meta = SessionMeta(
        session_id=session_id,
        model=model,
        created_at=datetime.now(UTC).isoformat(),
        prompt=prompt,
        turns=turns,
    )
    with _path(session_id).open("w", encoding="utf-8") as f:
        f.write(json.dumps({"header": meta.model_dump()}) + "\n")
    return meta


def append_turn(session_id: str, messages: list[Any]) -> None:
    """Append each message as its own ``{"msg": ...}`` JSONL line.

    The caller (``Session``) guarantees ``save_header`` ran first via its
    ``_header_written`` flag, so the file already exists. Each message is run
    through the singleton ``ModelMessagesTypeAdapter`` (list-typed, hence the
    wrap/unwrap) so the on-disk dict is exactly what ``validate_python`` will
    accept on load.
    """
    with _path(session_id).open("a", encoding="utf-8") as f:
        for msg in messages:
            # mode="json": emit JSON-primitive types (datetime → ISO-8601 str) so
            # the dict round-trips through json.dumps. The default mode='python'
            # leaves datetime instances in-place, which json.dumps rejects.
            dumped = ModelMessagesTypeAdapter.dump_python([msg], mode="json")[0]
            f.write(json.dumps({"msg": dumped}) + "\n")


def load(session_id: str) -> list[Any]:
    """Load all messages for a session. Raises ``FileNotFoundError`` if absent.

    Per-line parse errors are skipped+logged (never raised); the batch is then
    validated through ``ModelMessagesTypeAdapter.validate_python`` (its list
    type). If the batch validation itself fails — possible only on a partial
    write — we fall back to per-element validate+skip so the "skip+log, never
    raise" guarantee holds for message bodies too.
    """
    msg_dicts: list[dict[str, Any]] = []
    with _path(session_id).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                _log.warning("skipping malformed line in %s: %r", session_id, line)
                continue
            if not isinstance(obj, dict) or "msg" not in obj:
                # Header line (or any non-msg dict) — skip silently.
                continue
            msg_dicts.append(obj["msg"])
    try:
        return ModelMessagesTypeAdapter.validate_python(msg_dicts)
    except Exception as exc:  # partial write / one bad msg dict
        _log.warning(
            "batch validate failed for %s (%s); falling back to per-message", session_id, exc
        )
        result: list[Any] = []
        for d in msg_dicts:
            try:
                result.append(ModelMessagesTypeAdapter.validate_python([d])[0])
            except Exception as inner:
                _log.warning("skipping unvalidatable message in %s: %s", session_id, inner)
                continue
        return result


def list_sessions() -> list[SessionMeta]:
    """List all saved sessions, newest-first by ``created_at``.

    Files with a missing/corrupt/invalid header are skipped+logged (a
    half-written file should never crash ``/sessions``).
    """
    metas: list[SessionMeta] = []
    for p in sessions_dir().glob("*.jsonl"):
        try:
            with p.open("r", encoding="utf-8") as f:
                first = ""
                for line in f:
                    first = line.strip()
                    if first:
                        break
                if not first:
                    continue
                obj = json.loads(first)
                if not isinstance(obj, dict) or "header" not in obj:
                    _log.warning("skipping %s: no header on first line", p.name)
                    continue
                metas.append(SessionMeta.model_validate(obj["header"]))
        except (json.JSONDecodeError, pydantic.ValidationError, OSError) as exc:
            _log.warning("skipping %s: %s", p.name, exc)
            continue
    metas.sort(key=lambda m: m.created_at, reverse=True)
    return metas


def rewrite(session_id: str, meta: SessionMeta, messages: list[Any]) -> None:
    """Replace a session file with just ``meta`` + ``messages`` (used by /compact).

    Equivalent to ``save_header`` + ``append_turn`` back-to-back; spelled out as
    its own function so the "discard the prior history" intent is named at the
    call site.
    """
    _path(session_id).parent.mkdir(parents=True, exist_ok=True)
    with _path(session_id).open("w", encoding="utf-8") as f:
        f.write(json.dumps({"header": meta.model_dump()}) + "\n")
        for msg in messages:
            dumped = ModelMessagesTypeAdapter.dump_python([msg], mode="json")[0]
            f.write(json.dumps({"msg": dumped}) + "\n")
