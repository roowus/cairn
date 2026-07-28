"""REST/OpenAPI adapter — DEFERRED (Phase ≥2).

When built, this exposes the plugin registry over FastAPI/OpenAPI. Like the MCP
adapter, it reuses the registry and PluginContext contract. See
docs/decisions/0004-defer-kuzu-qdrant-stix-mcp.md.
"""

from __future__ import annotations


def build_api_server() -> None:  # pragma: no cover
    raise NotImplementedError(
        "The REST/OpenAPI server is deferred to a later phase. See docs/decisions/0004."
    )
