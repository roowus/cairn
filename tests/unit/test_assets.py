"""core/assets.py — typed-asset taxonomy + edge vocabulary (moat P1 substrate)."""

from __future__ import annotations

from cairn.core import assets


def test_existing_types_are_first_class_in_taxonomy():
    # The 13 literals in use + extract types must all be known, never renamed.
    existing = [
        "email", "url", "ip", "domain", "crypto_btc", "crypto_eth", "phone",
        "username", "person", "person_name", "hostname", "asn", "prefix",
        "github_login",
        "github_repo",
        "image_url",
    ]
    for t in existing:
        assert assets.is_known_type(t), t


def test_new_osint_types_added():
    new_types = [
        "subdomain", "netblock", "secret", "credential",
        "repo", "webapp", "bucket", "certificate",
    ]
    for t in new_types:
        assert assets.is_known_type(t), t


def test_unknown_type_tolerated_into_misc():
    assert assets.category_of("totally_experimental") == "misc"
    assert assets.is_known_type("totally_experimental") is False


def test_category_mapping_covers_existing_and_new():
    assert assets.category_of("ip") == "dns_network"
    assert assets.category_of("subdomain") == "dns_network"
    assert assets.category_of("email") == "identity"
    assert assets.category_of("secret") == "code_config"
    assert assets.category_of("webapp") == "web"
    assert assets.category_of("github_login") == "code_identity"


def test_asset_key_matches_node_id_form_and_is_lossless():
    # Must equal graph_store._node_id exactly so findings + graph share one keyspace.
    assert assets.asset_key("subdomain", "api.example.com") == "subdomain:api.example.com"
    assert assets.asset_key("ip", " 1.2.3.4 ") == "ip:1.2.3.4"  # value stripped
    # case is NOT folded in v1 (would re-key existing graphs) — exact + lossless
    assert assets.asset_key("domain", "Example.COM") == "domain:Example.COM"


def test_edge_vocabulary_is_canonical_and_nonempty():
    assert "resolves_to" in assets.EDGES
    assert "contains_secret" in assets.EDGES
    assert "employed_by" in assets.EDGES
    assert assets.EDGES  # nonempty
