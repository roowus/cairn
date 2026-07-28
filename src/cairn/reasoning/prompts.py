"""Small prompt helpers."""

from __future__ import annotations


def frame_investigation(query: str) -> str:
    """Optionally wrap a raw user query with light investigation framing."""
    return query.strip()
