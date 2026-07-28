"""Phase 6 theme tokens — valid Styles + palette stability."""

from __future__ import annotations

import dataclasses

import pytest
from rich.style import Style

from cairn.interfaces.tui.theme import theme


def test_every_token_is_a_valid_style():
    for name in theme.token_names():
        assert isinstance(getattr(theme, name), Style), name


def test_palette_token_set_is_stable():
    # Adding/renaming a token is intentional — update this set when the palette
    # deliberately changes (guards against silent drift in Step 6.2 consumers).
    assert set(theme.token_names()) == {
        "accent",
        "bold_accent",
        "muted",
        "ok",
        "err",
        "warn",
        "paid",
        "border",
        "prompt",
        "thinking",
        "tool_name",
        "tool_target",
    }


def test_theme_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        theme.accent = theme.err
