"""MCP server adapter — DEFERRED (Phase ≥2).

When built, this will iterate the plugin registry and expose each plugin as an
MCP tool over stdio and HTTP/SSE. Because plugins already take a PluginContext
and return Pydantic models, the adapter is a thin layer over the registry — no
plugin changes required. See docs/decisions/0004-defer-kuzu-qdrant-stix-mcp.md.
"""

from __future__ import annotations


def build_mcp_server() -> None:  # pragma: no cover
    raise NotImplementedError(
        "The MCP server is deferred to a later phase. The plugin registry already "
        "exposes everything it needs; see docs/decisions/0004."
    )
