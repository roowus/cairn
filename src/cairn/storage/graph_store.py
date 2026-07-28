"""NetworkX-backed :class:`GraphStore`.

Entities become nodes keyed by ``"type:value"``; relationships become labeled
directed edges. The graph lives in memory and can be (de)serialized to JSON for
persistence between sessions — a stand-in until Kùzu is added behind the same
:class:`~cairn.storage.protocols.GraphStore` interface.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import networkx as nx

from cairn.execution.base import Entity
from cairn.storage.protocols import GraphStore


def _node_id(entity: Entity) -> str:
    return f"{entity.type}:{entity.value}"


class NetworkXGraphStore(GraphStore):
    def __init__(self) -> None:
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()
        # Re-entrant guard around mutation. The methods stay synchronous, so an
        # asyncio.Lock would force them async (and clash with the tool closure);
        # an RLock is transparent on the single-session hot path and makes a
        # graph shared across sessions (or mutated from a thread executor) safe.
        self._lock = threading.RLock()

    @property
    def graph(self) -> nx.MultiDiGraph:
        return self._g

    def add_entity(self, entity: Entity, *, source: str | None = None) -> None:
        with self._lock:
            nid = _node_id(entity)
            if nid in self._g:
                # merge attrs; keep first-seen position
                self._g.nodes[nid].update(
                    {k: v for k, v in entity.attrs.items() if k not in self._g.nodes[nid]}
                )
                if source and source not in self._g.nodes[nid].get("sources", []):
                    self._g.nodes[nid].setdefault("sources", []).append(source)
            else:
                self._g.add_node(
                    nid,
                    type=entity.type,
                    value=entity.value,
                    attrs=dict(entity.attrs),
                    sources=[source] if source else [],
                )

    def add_relationship(self, a: Entity, rel: str, b: Entity) -> None:
        with self._lock:
            # add_entity re-acquires the RLock (re-entrant) — safe, no deadlock.
            self.add_entity(a)
            self.add_entity(b)
            self._g.add_edge(_node_id(a), _node_id(b), rel=rel)

    def merge(self, other: NetworkXGraphStore) -> None:
        """Fold ``other``'s entities/relationships into this store in place.

        Cross-session entity identity is the existing ``"type:value"`` node key,
        so an entity mined by two pooled sessions collapses to one node — its
        ``sources`` list accumulates both, mirroring :meth:`add_entity`'s
        first-seen merge. Callers should ensure ``other`` is quiescent (e.g. its
        session has drained) before merging.
        """
        og = other.graph  # read-only view of the donor store
        with self._lock:
            for nid, data in og.nodes(data=True):
                if nid in self._g:
                    node = self._g.nodes[nid]
                    for k, v in (data.get("attrs") or {}).items():
                        node.setdefault("attrs", {}).setdefault(k, v)
                    for s in data.get("sources") or []:
                        if s not in node.setdefault("sources", []):
                            node["sources"].append(s)
                else:
                    self._g.add_node(nid, **dict(data))
            for u, v, edata in og.edges(data=True):
                self._g.add_edge(u, v, **dict(edata))

    def entities(self) -> list[Entity]:
        out: list[Entity] = []
        for nid, data in self._g.nodes(data=True):
            out.append(
                Entity(
                    type=data.get("type", "?"),
                    value=data.get("value", nid),
                    attrs=data.get("attrs", {}),
                )
            )
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = nx.node_link_data(self._g)
        path.write_text(json.dumps(data), encoding="utf-8")

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._g = nx.node_link_graph(data)

    def summary(self) -> str:
        return f"{self._g.number_of_nodes()} entities, {self._g.number_of_edges()} relationships"

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": list(self._g.nodes(data=True)), "edges": list(self._g.edges(data=True))}
