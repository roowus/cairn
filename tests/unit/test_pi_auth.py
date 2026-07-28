"""pi auth.json loading + xAI OAuth refresh."""

from __future__ import annotations

import json
import time

import httpx

from cairn.core.pi_auth import get_xai_api_key, get_zai_api_key, load_pi_auth


def test_load_missing(tmp_path):
    assert load_pi_auth(tmp_path / "nope.json") == {}


def test_get_zai_key(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"zai": {"type": "api_key", "key": "zai-secret"}}), encoding="utf-8")
    assert get_zai_api_key(p) == "zai-secret"


def test_get_xai_static_key(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"xai": {"type": "api_key", "key": "xai-static"}}), encoding="utf-8")
    assert get_xai_api_key(p, refresh=False) == "xai-static"


def test_get_xai_oauth_fresh(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text(
        json.dumps(
            {
                "xai": {
                    "type": "oauth",
                    "access": "access-fresh",
                    "refresh": "refresh-1",
                    "expires": int(time.time() * 1000) + 3_600_000,
                }
            }
        ),
        encoding="utf-8",
    )
    assert get_xai_api_key(p, refresh=True) == "access-fresh"


def test_get_xai_oauth_refresh(tmp_path, monkeypatch):
    p = tmp_path / "auth.json"
    p.write_text(
        json.dumps(
            {
                "xai": {
                    "type": "oauth",
                    "access": "access-old",
                    "refresh": "refresh-1",
                    "expires": int(time.time() * 1000) - 1_000,  # already expired
                }
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://auth.x.ai/oauth2/token"
        body = dict(x.split("=") for x in request.content.decode().split("&"))
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "refresh-1"
        return httpx.Response(
            200,
            json={
                "access_token": "access-new",
                "refresh_token": "refresh-2",
                "expires_in": 3600,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        tok = get_xai_api_key(p, refresh=True, client=client)
    finally:
        client.close()

    assert tok == "access-new"
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["xai"]["access"] == "access-new"
    assert saved["xai"]["refresh"] == "refresh-2"
    assert saved["xai"]["expires"] > time.time() * 1000


def test_get_xai_oauth_refresh_failure_falls_back(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text(
        json.dumps(
            {
                "xai": {
                    "type": "oauth",
                    "access": "access-stale",
                    "refresh": "refresh-bad",
                    "expires": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        tok = get_xai_api_key(p, refresh=True, client=client)
    finally:
        client.close()
    assert tok == "access-stale"
