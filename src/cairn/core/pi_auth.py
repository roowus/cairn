"""Read LLM credentials from the pi coding-agent auth store.

Cairn can reuse the same keys/tokens the user already logged into via `pi`
(``~/.pi/agent/auth.json``). For xAI this is usually an OAuth access token from
a Grok/X subscription; for Z.AI it is a static API key.

Secrets are never logged. Token refresh mutates the auth file in place (same
behaviour as pi itself) so subsequent runs and other tools keep working.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from cairn.core.logging import get_logger

_log = get_logger("cairn.pi_auth")

# Match pi-ai's xAI OAuth client (device-code / refresh flow).
_XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
_XAI_TOKEN_URL = "https://auth.x.ai/oauth2/token"
_REFRESH_SKEW_MS = 5 * 60 * 1000
_DEFAULT_TOKEN_LIFETIME_S = 3600


def pi_auth_path() -> Path:
    """Resolve ``~/.pi/agent/auth.json``, overridable via ``PI_AUTH_PATH``."""
    env = os.environ.get("PI_AUTH_PATH")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".pi" / "agent" / "auth.json"


def load_pi_auth(path: Path | None = None) -> dict[str, Any]:
    """Return the auth.json object, or ``{}`` if missing/unreadable."""
    p = path or pi_auth_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _log.warning("pi auth file is not valid JSON: %s", p)
        return {}
    return data if isinstance(data, dict) else {}


def _write_pi_auth(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or pi_auth_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def get_zai_api_key(path: Path | None = None) -> str | None:
    """Return the Z.AI / GLM API key from pi auth, if present."""
    entry = load_pi_auth(path).get("zai")
    if not isinstance(entry, dict):
        return None
    key = entry.get("key")
    return key if isinstance(key, str) and key.strip() else None


def get_xai_api_key(
    path: Path | None = None,
    *,
    refresh: bool = True,
    client: httpx.Client | None = None,
) -> str | None:
    """Return a usable xAI bearer token (API key or refreshed OAuth access).

    Preference order inside the ``xai`` auth entry:
    1. static ``key`` (api_key login)
    2. OAuth ``access`` token, refreshed when near expiry
    """
    auth_path = path or pi_auth_path()
    data = load_pi_auth(auth_path)
    entry = data.get("xai")
    if not isinstance(entry, dict):
        return None

    static = entry.get("key")
    if isinstance(static, str) and static.strip():
        return static.strip()

    access = entry.get("access")
    if not isinstance(access, str) or not access.strip():
        return None

    if not refresh or not _xai_needs_refresh(entry):
        return access.strip()

    refresh_token = entry.get("refresh")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        _log.warning("xAI OAuth token expired and no refresh token is stored")
        return access.strip()

    try:
        updated = _refresh_xai_oauth(refresh_token.strip(), client=client)
    except Exception as exc:
        _log.warning("xAI OAuth refresh failed: %s", exc)
        return access.strip()

    # Preserve any extra fields pi may store alongside the oauth blob.
    merged = {**entry, **updated}
    data["xai"] = merged
    try:
        _write_pi_auth(data, auth_path)
    except OSError as exc:
        _log.warning("could not persist refreshed xAI token: %s", exc)
    return str(merged["access"])


def _xai_needs_refresh(entry: dict[str, Any]) -> bool:
    expires = entry.get("expires")
    if not isinstance(expires, (int, float)):
        return False
    # pi stores expires already skewed by REFRESH_SKEW_MS.
    return time.time() * 1000 >= float(expires)


def _refresh_xai_oauth(
    refresh_token: str,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Exchange a refresh token for a new access token (pi-compatible shape)."""
    owns = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        resp = http.post(
            _XAI_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": _XAI_CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    finally:
        if owns:
            http.close()

    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    body = resp.json()
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise RuntimeError("xAI refresh response missing access_token")

    new_refresh = body.get("refresh_token")
    if not isinstance(new_refresh, str) or not new_refresh:
        new_refresh = refresh_token

    expires_in = body.get("expires_in", _DEFAULT_TOKEN_LIFETIME_S)
    try:
        lifetime_s = float(expires_in)
    except (TypeError, ValueError):
        lifetime_s = float(_DEFAULT_TOKEN_LIFETIME_S)
    if lifetime_s <= 0:
        lifetime_s = float(_DEFAULT_TOKEN_LIFETIME_S)

    return {
        "type": "oauth",
        "access": access,
        "refresh": new_refresh,
        "expires": int(time.time() * 1000 + lifetime_s * 1000 - _REFRESH_SKEW_MS),
    }
