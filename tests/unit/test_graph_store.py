"""NetworkXGraphStore: node-key dedup, merge across stores, mutation guard,
evidence-metadata (provenance/confidence/first_seen) round-trip + promotion."""

from __future__ import annotations

import threading

from cairn.core.provenance import Confidence, Provenance
from cairn.execution.base import Entity
from cairn.storage.graph_store import NetworkXGraphStore


def test_add_entity_dedups_by_node_key():
    store = NetworkXGraphStore()
    store.add_entity(Entity(type="ip", value="1.2.3.4"), source="a")
    store.add_entity(Entity(type="ip", value="1.2.3.4"), source="b")
    ips = [n for n, d in store.graph.nodes(data=True) if d.get("type") == "ip"]
    assert len(ips) == 1
    # both sources accumulated on the single node
    assert set(store.graph.nodes["ip:1.2.3.4"]["sources"]) == {"a", "b"}


def test_merge_dedups_across_stores():
    a = NetworkXGraphStore()
    b = NetworkXGraphStore()
    a.add_entity(Entity(type="ip", value="203.0.113.9"), source="sess-a")
    b.add_entity(Entity(type="ip", value="203.0.113.9"), source="sess-b")

    a.merge(b)

    ips = [n for n, d in a.graph.nodes(data=True) if d.get("type") == "ip"]
    assert len(ips) == 1  # cross-session dedup via the type:value key
    assert set(a.graph.nodes["ip:203.0.113.9"]["sources"]) == {"sess-a", "sess-b"}


def test_merge_carries_relationships():
    a = NetworkXGraphStore()
    b = NetworkXGraphStore()
    b.add_relationship(
        Entity(type="email", value="x@y.z"), "belongs_to", Entity(type="domain", value="y.z")
    )

    a.merge(b)

    assert a.graph.number_of_edges() == 1
    assert ("email:x@y.z", "domain:y.z") in a.graph.edges()


def test_merge_disjoint_stores_union():
    a = NetworkXGraphStore()
    b = NetworkXGraphStore()
    a.add_entity(Entity(type="ip", value="1.1.1.1"))
    b.add_entity(Entity(type="ip", value="2.2.2.2"))
    a.merge(b)
    ips = {n for n, d in a.graph.nodes(data=True) if d.get("type") == "ip"}
    assert ips == {"ip:1.1.1.1", "ip:2.2.2.2"}


def test_concurrent_adds_are_safe():
    """The RLock must let many threads add distinct entities without losing nodes."""
    store = NetworkXGraphStore()

    def add_range(lo: int) -> None:
        for i in range(lo, lo + 50):
            store.add_entity(Entity(type="ip", value=f"10.0.0.{i}"))

    threads = [threading.Thread(target=add_range, args=(i * 50,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ips = [n for n, d in store.graph.nodes(data=True) if d.get("type") == "ip"]
    assert len(ips) == 200  # no lost updates under contention


# --- evidence metadata: provenance / confidence / first_seen ----------------


def _ip(value: str, **kw) -> Entity:
    return Entity(type="ip", value=value, **kw)


def test_provenance_round_trips_through_entities():
    store = NetworkXGraphStore()
    store.add_entity(
        _ip(
            "1.2.3.4",
            confidence=Confidence.TENTATIVE,
            provenance=Provenance(tool="shodan_internetdb", source_url="https://internetdb.shodan.io/1.2.3.4"),
        ),
        source="shodan_internetdb",
    )
    [entity] = [e for e in store.entities() if e.value == "1.2.3.4"]
    assert entity.confidence is Confidence.TENTATIVE
    assert entity.provenance is not None
    assert entity.provenance.tool == "shodan_internetdb"
    assert entity.provenance.source_url == "https://internetdb.shodan.io/1.2.3.4"
    assert entity.first_seen is not None  # auto-stamped on first add


def test_confidence_promotes_to_firm_on_second_independent_source():
    store = NetworkXGraphStore()
    store.add_entity(_ip("5.6.7.8", confidence=Confidence.TENTATIVE), source="crtsh")
    store.add_entity(_ip("5.6.7.8", confidence=Confidence.TENTATIVE), source="dns_lookup")
    [entity] = [e for e in store.entities() if e.value == "5.6.7.8"]
    assert entity.confidence is Confidence.FIRM  # ≥2 independent sources


def test_confidence_confirmed_is_sticky():
    store = NetworkXGraphStore()
    store.add_entity(_ip("9.9.9.9", confidence=Confidence.CONFIRMED), source="a")
    store.add_entity(_ip("9.9.9.9", confidence=Confidence.TENTATIVE), source="b")
    [entity] = [e for e in store.entities() if e.value == "9.9.9.9"]
    assert entity.confidence is Confidence.CONFIRMED  # never downgraded


def test_single_untagged_entity_stays_none():
    # backward-compat: a legacy entity built without confidence (1 source) stays
    # untracked. (Two+ sources IS corroboration → FIRM, tested below.)
    store = NetworkXGraphStore()
    store.add_entity(Entity(type="ip", value="10.0.0.1"), source="a")
    [entity] = [e for e in store.entities() if e.value == "10.0.0.1"]
    assert entity.confidence is None


def test_corroboration_promotes_even_when_neither_source_tagged():
    # rule-of-three: ≥2 independent sources corroborate → FIRM, with or without
    # explicit per-source tagging.
    store = NetworkXGraphStore()
    store.add_entity(Entity(type="ip", value="10.0.0.2"), source="crtsh")
    store.add_entity(Entity(type="ip", value="10.0.0.2"), source="dns_lookup")
    [entity] = [e for e in store.entities() if e.value == "10.0.0.2"]
    assert entity.confidence is Confidence.FIRM


def test_save_load_preserves_provenance_and_confidence(tmp_path):
    store = NetworkXGraphStore()
    store.add_entity(
        _ip(
            "203.0.113.5",
            confidence=Confidence.FIRM,
            provenance=Provenance(tool="urlscan", source_url="https://urlscan.io/x"),
        ),
        source="urlscan",
    )
    path = tmp_path / "g.json"
    store.save(path)  # must not raise despite datetime/Provenance in node data

    reloaded = NetworkXGraphStore()
    reloaded.load(path)
    [entity] = [e for e in reloaded.entities() if e.value == "203.0.113.5"]
    assert entity.confidence is Confidence.FIRM
    assert entity.provenance is not None
    assert entity.provenance.tool == "urlscan"
    assert entity.first_seen is not None  # ISO-string round-tripped back to datetime


# --- merge path: corroboration must promote confidence cross-session --------


def test_merge_promotes_confidence_via_corroboration():
    # two pooled sessions, same entity from independent sources -> merged FIRM
    a = NetworkXGraphStore()
    b = NetworkXGraphStore()
    a.add_entity(Entity(type="ip", value="1.1.1.1"), source="crtsh")
    b.add_entity(Entity(type="ip", value="1.1.1.1"), source="dns_lookup")
    a.merge(b)
    [entity] = [e for e in a.entities() if e.value == "1.1.1.1"]
    assert entity.confidence is Confidence.FIRM


def test_merge_keeps_donor_confirmed_sticky():
    a = NetworkXGraphStore()
    b = NetworkXGraphStore()
    a.add_entity(Entity(type="ip", value="2.2.2.2", confidence=Confidence.TENTATIVE), source="x")
    b.add_entity(Entity(type="ip", value="2.2.2.2", confidence=Confidence.CONFIRMED), source="y")
    a.merge(b)
    [entity] = [e for e in a.entities() if e.value == "2.2.2.2"]
    assert entity.confidence is Confidence.CONFIRMED
