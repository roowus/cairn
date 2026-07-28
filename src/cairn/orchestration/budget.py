"""Token-budget helpers.

PydanticAI enforces per-run limits via ``usage_limits``; here we provide simple
conversation-history trimming so a long session doesn't blow the context window.
A later phase swaps in a real summarizer or vector-store-backed retrieval.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_ROUGH_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _ROUGH_CHARS_PER_TOKEN)


def messages_token_estimate(messages: Sequence[Any]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(str(getattr(m, "content", "")) or repr(m))
    return total


def trim_history(messages: list[Any], *, max_messages: int = 60) -> list[Any]:
    """Keep the most recent ``max_messages`` (preserves any leading system message)."""
    if len(messages) <= max_messages:
        return messages
    return messages[-max_messages:]
