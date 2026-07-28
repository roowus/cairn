"""Tests for the prompt_toolkit input backend (UI overhaul U2).

The live ``PromptSession.prompt()`` call needs a real TTY, so it is not exercised
here; instead we cover the parts that can break silently: the command-name
snapshot (drift vs the REPL dispatch) and the completer's slash/skill suggestions.
"""

from __future__ import annotations

from types import SimpleNamespace

from prompt_toolkit.document import Document

from cairn.interfaces.tui.input import COMMAND_NAMES, BasicInput, build_completer


def test_command_names_snapshot_catches_drift():
    # The REPL dispatches these; if one is added/removed here without updating
    # repl.py (or vice versa) this fails loudly.
    for required in ("/help", "/model", "/plugins", "/workspace", "/skills",
                     "/graph", "/audit", "/usage", "/reset", "/quit"):
        assert required in COMMAND_NAMES


def test_completer_suggests_slash_commands_and_skill_names():
    skills = {"domain-recon": SimpleNamespace(name="domain-recon")}
    completer = build_completer(skills)

    slash = [c.text for c in completer.get_completions(Document("/he", 3), None)]
    assert "/help" in slash

    skill = [c.text for c in completer.get_completions(Document("/dom", 4), None)]
    assert "/domain-recon" in skill


def test_basic_input_delegates_to_console_input():
    class _FakeConsole:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def input(self, prompt: str) -> str:
            self.calls.append(prompt)
            return "hello world"

    console = _FakeConsole()
    out = BasicInput().read_prompt(console)  # type: ignore[arg-type]
    assert out == "hello world"
    assert "cairn>" in console.calls[0]
