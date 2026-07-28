"""NetworkXGraphStore: node-key dedup, merge across stores, mutation guard."""

from __future__ import annotations

import threading

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
