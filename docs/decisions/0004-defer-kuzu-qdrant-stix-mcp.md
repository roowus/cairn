# ADR 0004 — Defer STIX, MCP, REST, multi-agent, Docker, OAuth

**Status:** Accepted

## Context
The research describes an enterprise target: STIX 2.1 output, an MCP server
(stdio + HTTP/SSE), a REST/OpenAPI service, a multi-agent coordinator, a
Bayesian decision engine, Docker sidecars, and OAuth 2.1. Building all of that
upfront delays a working tool and adds setup friction (native deps, containers).

## Decision
Phase 1 ships the **REPL + headless CLI** only. Everything else is deferred but
kept as clean seams:

| Capability | Seam | Upgrade cost |
|---|---|---|
| STIX 2.1 | additive `to_stix()` on `Entity`/`PluginOutput` (outputs are already structured Pydantic) | additive |
| MCP server | `interfaces/mcp.py` stub iterates the registry | ~50-line adapter |
| REST/OpenAPI | `interfaces/api.py` stub over FastAPI | ~similar |
| Kùzu graph DB | `GraphStore` ABC (`storage/protocols.py`) | drop-in impl |
| Qdrant vector DB | `VectorStore` ABC | drop-in impl |
| Multi-agent | extra PydanticAI `Agent`s in `reasoning/coordinator.py` | new module, no Layer-3 change |
| Docker sidecars | generalize `execution/subprocess_util` | additive |
| OAuth 2.1 | add to the MCP HTTP/SSE transport when built | additive |

## Rationale
Each deferred item depends only on the stable plugin registry / Pydantic-output
contract, not on internals that are still settling. Deferring keeps the MVP
small and shippable while preserving every target from the research.

## Consequences
- Phase 1 cannot yet emit STIX bundles or run as an MCP server. Both are
  explicitly planned and have reserved files.
