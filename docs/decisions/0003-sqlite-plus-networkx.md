# ADR 0003 — SQLite + NetworkX storage now; Kùzu/Qdrant later

**Status:** Accepted

## Context
The research specifies Kùzu (embedded graph DB) + Qdrant (vector DB) + SQLite +
NetworkX. Kùzu requires native compilation (setup friction). For a Phase-1 MVP
we want low friction without sacrificing the path to the full stack.

## Decision
Phase 1 uses **SQLite** (relational, audit, case state) + **NetworkX**
(in-memory graph, persisted to SQLite as JSON). Storage is accessed through
small ABCs (`GraphStore`, `VectorStore`) in `storage/protocols.py`. Kùzu and
Qdrant are deferred to a later phase and slot in behind those protocols.

## Rationale
- No native build step — installs cleanly on the user's Python 3.14.
- SQLite is zero-config and already suitable for the audit log and case state.
- NetworkX gives real graph algorithms (centrality, paths) over the captured
  entities for Phase-1 needs.
- The ABC seam means promoting to Kùzu/Qdrant later touches only
  `storage/graph_store.py` (and a new `KuzuGraphStore`), not the orchestration
  layer that consumes it.

## Consequences
- Phase-1 memory is in-process history + token trimming; semantic retrieval
  over stored notes waits for the vector store.
- Multi-hop graph queries over very large investigations will be slower than
  Kùzu — acceptable for MVP; the upgrade path is a drop-in.
