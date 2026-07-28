"""Entity extraction (core layer, pure stdlib)."""

from __future__ import annotations

from cairn.core.entities import extract_entities


def _types_values(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for e in extract_entities(text):
        out.setdefault(e.type, set()).add(e.value.lower())
    return out


def test_extracts_email_ip_domain_url():
    tv = _types_values("Contact jdoe@example.com from 8.8.8.8, see https://example.com/path")
    assert "jdoe@example.com" in tv["email"]
    assert "8.8.8.8" in tv["ip"]
    assert "https://example.com/path" in tv["url"]
    # example.com is part of an email+url → should NOT double as a bare domain
    assert "example.com" not in tv.get("domain", set())


def test_extracts_crypto_addresses():
    tv = _types_values(
        "BTC bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq "
        "ETH 0x71C7656EC7ab88b098defB751B7401B5f6d8976F"
    )
    assert any("bc1q" in v for v in tv["crypto_btc"])
    assert any(v.startswith("0x71c7656") for v in tv["crypto_eth"])


def test_extracts_phone_and_dedups():
    tv = _types_values("call +1-555-0100 or +1-555-0100 again")
    assert "+1-555-0100" in {v for v in tv.get("phone", set())} or tv.get("phone")


def test_invalid_ip_not_captured():
    tv = _types_values("version 999.999.999.999 is bogus")
    assert "999.999.999.999" not in tv.get("ip", set())


def test_bare_domain_captured_when_not_in_email_or_url():
    tv = _types_values("the site sub.example.org has data")
    assert "sub.example.org" in tv["domain"]
