"""The typed-asset taxonomy — the substrate a future pivot engine runs on.

Claude-OSINT's load-bearing discipline (methodology §8): *every discovery is a
typed asset in a graph, not a free-floating string.* An investigator reasons over
typed assets and typed edges (``api.example.com RESOLVES_TO 1.2.3.4``,
``that IP EXPOSES a kubelet``) — not bare text. That typed graph is what makes an
investigation **queryable, reproducible, and cost-bounded** (moat Pillar 1).

This module is the *data shape* of that substrate — it does NOT contain a BFS
engine (that's a separate, later epic). It provides:

- :data:`ASSET_CATEGORIES` — the 9-category taxonomy (methodology §8.1), with
  Cairn's existing entity types slotted in and the missing OSINT-native types
  added (``subdomain``, ``netblock``, ``secret``, ``credential``, ``repo``,
  ``webapp``, ``bucket``, ``certificate``, …).
- :func:`asset_key` — the typed dedup key (``subdomain:api.example.com``). It is
  **deliberately identical in form to the existing graph node id**
  (``storage/graph_store._node_id`` = ``f"{type}:{value}"``), so adopting it breaks
  zero existing nodes or persisted graphs — the taxonomy adds *categories and new
  types*, never renames an existing one.
- :data:`EDGES` — the canonical relationship vocabulary (``resolves_to``,
  ``exposes``, ``contains_secret``, ``employed_by``, …) for typed edges.

Pure stdlib; ``core`` layer (no upward imports).
"""

from __future__ import annotations

# --- Cairn's existing entity types (the 13 literals in use + extract types) ---
# These MUST stay first-class members of the taxonomy; nothing here renames them.
_EXISTING_TYPES = frozenset(
    {
        # from core/entities.py extract_entities()
        "email", "url", "ip", "domain", "crypto_btc", "crypto_eth", "phone",
        # plugin-emitted literals (execution/base.Entity.type)
        "username", "person", "person_name", "hostname", "asn", "prefix",
        "github_login", "github_repo", "image_url",
    }
)

# --- OSINT-native types added by the Claude-OSINT taxonomy (methodology §8.1) ---
_NEW_TYPES = frozenset(
    {
        "subdomain", "netblock", "port", "service", "certificate",
        "credential", "secret", "repo", "bucket", "firebase_project",
        "webapp", "api_endpoint", "api_spec", "graphql_schema",
        "mobile_app", "deep_link",
        "typosquat_domain",
    }
)

#: Every known asset type (existing + new). Unknown types are tolerated — they
#: just slot into ``"misc"`` — so plugins can emit experimental types freely.
ASSET_TYPES: frozenset[str] = _EXISTING_TYPES | _NEW_TYPES

#: The 9-category taxonomy (methodology §8.1). Cairn's existing types are mapped
#: onto it; the new types fill the gaps. Used for grouping in reports/UI and as
#: the pivot engine's per-category budget knobs later.
ASSET_CATEGORIES: dict[str, frozenset[str]] = {
    "dns_network": frozenset({"domain", "subdomain", "ip", "netblock", "asn", "prefix"}),
    "service": frozenset({"port", "service", "certificate"}),
    "identity": frozenset({"email", "person", "person_name", "username", "credential"}),
    "code_config": frozenset({"repo", "github_repo", "secret"}),
    "cloud_storage": frozenset({"bucket", "firebase_project"}),
    "web": frozenset({"webapp", "api_endpoint", "api_spec", "graphql_schema", "url", "hostname"}),
    "mobile": frozenset({"mobile_app", "deep_link"}),
    "phishing": frozenset({"typosquat_domain"}),
    "crypto": frozenset({"crypto_btc", "crypto_eth"}),
    # contact + provenance of a profile pic / asset
    "contact": frozenset({"phone"}),
    "media": frozenset({"image_url"}),
    "code_identity": frozenset({"github_login"}),
    "misc": frozenset(),  # fallback bucket for unmapped/experimental types
}

#: Reverse lookup: type → category (``misc`` if unmapped).
CATEGORY_OF: dict[str, str] = {
    t: cat for cat, types in ASSET_CATEGORIES.items() for t in types
}


def category_of(asset_type: str) -> str:
    """The taxonomy category for an asset type (``"misc"`` if unmapped)."""
    return CATEGORY_OF.get(asset_type, "misc")


def is_known_type(asset_type: str) -> bool:
    return asset_type in ASSET_TYPES


def asset_key(asset_type: str, value: str) -> str:
    """The typed dedup key for an asset: ``f"{type}:{value}"``.

    Identical in form to ``storage/graph_store._node_id`` so the graph store and
    the finding schema share one key space — no divergence, no break to existing
    nodes. The *value* of the taxonomy is the distinct type prefixes (a
    ``subdomain`` key is distinguishable from a ``domain`` key) plus the category
    mapping, not a fancy normalization. Case-folding / canonical-type remapping
    is intentionally deferred to the pivot engine (it would re-key existing
    graphs); v1 keeps keys exact and lossless.
    """
    return f"{asset_type}:{value.strip()}"


#: Canonical typed-edge vocabulary (methodology §8 asset graph). ``add_relationship``
#: already takes a free-form ``rel`` label; this set names the agreed relationships
#: so the graph is queryable by edge type (the pivot engine's traversal rules).
EDGES: frozenset[str] = frozenset(
    {
        "resolves_to",      # subdomain/ip → ip
        "in_netblock",      # ip → netblock/asn
        "hosted_on",        # subdomain → asn (hosting)
        "exposes",          # ip/subdomain → port/service/webapp
        "documented_by",    # webapp → api_spec
        "contains_secret",  # repo/webapp → secret
        "contains",         # breach → email; repo → code
        "breached_from",    # secret → breach
        "employed_by",      # email → person/org
        "alias_of",         # username/handle → person (identity merge)
        "owns",             # person → repo/domain
        "links_to",         # webapp/url → url (discovered hyperlinks)
        "cert_for",         # certificate → domain/subdomain
    }
)
