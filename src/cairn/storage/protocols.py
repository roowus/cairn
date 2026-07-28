"""Storage protocol ABCs.

These define the seams a later phase fills: a Kùzu-backed ``GraphStore`` and a
Qdrant-backed ``VectorStore`` slot in behind the same interfaces. Phase 1 ships
an in-memory NetworkX :class:`~cairn.storage.graph_store.NetworkXGraphStore` and
no vector store (memory is in-process history + token trimming).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cairn.execution.base import Entity


class GraphStore(ABC):
    """Append-only store of entities and their relationships."""

    @abstractmethod
    def add_entity(self, entity: Entity, *, source: str | None = None) -> None: ...

    @abstractmethod
    def add_relationship(self, a: Entity, rel: str, b: Entity) -> None: ...

    @abstractmethod
    def entities(self) -> list[Entity]: ...


class VectorStore(ABC):
    """Semantic retrieval over stored notes (Phase ≥2)."""

    @abstractmethod
    def add(self, key: str, text: str, metadata: dict[str, Any] | None = None) -> None: ...

    @abstractmethod
    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]: ...
