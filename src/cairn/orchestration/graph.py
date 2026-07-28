"""Convenience helpers around the graph store."""

from __future__ import annotations

from cairn.execution.base import Entity
from cairn.storage.graph_store import NetworkXGraphStore


def capture_entities(store: NetworkXGraphStore, entities: list[Entity], *, source: str) -> None:
    for entity in entities:
        store.add_entity(entity, source=source)
