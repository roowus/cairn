"""Budget / history helpers."""

from __future__ import annotations

from cairn.orchestration.budget import estimate_tokens, trim_history


def test_estimate_tokens_positive():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 40) == 10


def test_trim_history_keeps_tail():
    msgs = [{"i": i} for i in range(100)]
    out = trim_history(msgs, max_messages=10)
    assert len(out) == 10
    assert out[-1] == {"i": 99}


def test_trim_history_noop_when_small():
    msgs = [{"i": 1}, {"i": 2}]
    assert trim_history(msgs, max_messages=10) is msgs
