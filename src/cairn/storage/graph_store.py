"""NetworkX-backed :class:`GraphStore`.

Entities become nodes keyed by ``"type:value"``; relationships become labeled
directed edges. The graph lives in memory and can be (de)serialized to JSON for
persistence between sessions — a stand-in until Kùzu is added behind the same
:class:`~cairn.storage.protocols.GraphStore` interface.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx

from cairn.core.provenance import Confidence, Provenance, utc_now
from cairn.execution.base import Entity
from cairn.storage.protocols import GraphStore


def _node_id(entity: Entity) -> str:
    return f"{entity.type}:{entity.value}"


# --- evidence-metadata (de)serialization to JSON-safe node data -------------
# networkx ``node_link_data`` is dumped with ``json.dumps`` (no custom encoder),
# so a ``Provenance`` model / ``datetime`` can't live in node data raw. We store
# them as JSON-safe shapes and reconstruct typed objects on read — full round-trip.
def _dump_provenance(p: Provenance) -> dict[str, Any]:
    return p.model_dump(mode="json")


def _load_provenance(d: dict[str, Any] | None) -> Provenance | None:
    return Provenance(**d) if d else None


def _dump_dt(dt: datetime) -> str:
    return dt.isoformat()


def _load_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


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
                node = self._g.nodes[nid]
                # merge attrs; keep first-seen position
                node.update(
                    {k: v for k, v in entity.attrs.items() if k not in node}
                )
                if source and source not in node.get("sources", []):
                    node.setdefault("sources", []).append(source)
                # Rule-of-three seed: ≥2 independent sources promote confidence to
                # at least FIRM; an explicit CONFIRMED (a read-only validator) is
                # sticky. Promotion only — never downgrades an untracked (None) node.
                self._bump_confidence(node, entity.confidence)
                # provenance: keep the first record that has one; prefer one with a
                # source_url if this one is richer (cheap best-effort, not a merge).
                if entity.provenance and (
                    not node.get("provenance")
                    or (entity.provenance.source_url and not node["provenance"].get("source_url"))
                ):
                    node["provenance"] = _dump_provenance(entity.provenance)
            else:
                self._g.add_node(
                    nid,
                    type=entity.type,
                    value=entity.value,
                    attrs=dict(entity.attrs),
                    sources=[source] if source else [],
                    confidence=entity.confidence.value if entity.confidence else None,
                    provenance=_dump_provenance(entity.provenance) if entity.provenance else None,
                    first_seen=_dump_dt(entity.first_seen or utc_now()),
                )

    @staticmethod
    def _bump_confidence(node: dict[str, Any], incoming_conf: Confidence | None) -> None:
        """Promote confidence on a node given an incoming confidence (or None).

        Shared by :meth:`add_entity` and :meth:`merge` so corroboration follows one
        rule on both the single-session and cross-session paths. ``confirmed`` is
        sticky; >=2 independent sources promote to ``firm``; never downgrades an
        untracked (None) node to a tag, and never lowers an existing tag.
        """
        existing = node.get("confidence")
        incoming = incoming_conf.value if incoming_conf else None
        if existing == "confirmed" or incoming == "confirmed":
            node["confidence"] = "confirmed"
            return
        n_sources = len(node.get("sources", []))
        tagged = [v for v in (existing, incoming) if v]
        if "firm" in tagged or n_sources >= 2:
            node["confidence"] = "firm"
        elif tagged:
            # at least one side was evidence-tagged but not corroborated
            node["confidence"] = "tentative"
        # else both None → leave None (untracked; backward-compat with legacy nodes)

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
                    # Reconcile evidence metadata the same way add_entity does, so
                    # cross-session corroboration promotes confidence here too (the
                    # whole point of the evidence model on the parallel-sessions
                    # path): ≥2 sources -> firm, a donor's CONFIRMED is sticky.
                    donor_conf = Confidence(data["confidence"]) if data.get("confidence") else None
                    self._bump_confidence(node, donor_conf)
                    donor_prov = data.get("provenance")
                    if donor_prov and (
                        not node.get("provenance")
                        or (
                            donor_prov.get("source_url")
                            and not (node.get("provenance") or {}).get("source_url")
                        )
                    ):
                        node["provenance"] = donor_prov
                else:
                    self._g.add_node(nid, **dict(data))
            for u, v, edata in og.edges(data=True):
                self._g.add_edge(u, v, **dict(edata))

    def entities(self) -> list[Entity]:
        out: list[Entity] = []
        for nid, data in self._g.nodes(data=True):
            conf_raw = data.get("confidence")
            out.append(
                Entity(
                    type=data.get("type", "?"),
                    value=data.get("value", nid),
                    attrs=data.get("attrs", {}),
                    confidence=Confidence(conf_raw) if conf_raw else None,
                    provenance=_load_provenance(data.get("provenance")),
                    first_seen=_load_dt(data.get("first_seen")),
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
