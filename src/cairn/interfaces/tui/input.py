"""prompt_toolkit input for the REPL (UI overhaul U2).

Owns the INPUT phase only — read one line while ``Live`` is stopped, between
turns. The structural invariant (:mod:`cairn.interfaces.tui`) holds: Rich ``Live``
and prompt_toolkit never run concurrently.

Two backends:

* :class:`PromptKitInput` — a prompt_toolkit ``PromptSession`` with persistent
  history (``~/.cairn/history/repl.txt``), tab completion for slash commands +
  ``/<skill>`` names, and emacs/vi key bindings. Default on a TTY.
* :class:`BasicInput` — delegates to Rich ``console.input`` (the pre-U2
  behavior). Used for ``--basic`` / ``CAIRN_BASIC_INPUT=1`` / non-TTY.

Esc / Ctrl-C during a *turn* is unchanged: the cbreak ``_KeyWatcher``
(:mod:`cairn.interfaces.interrupt`) cancels the asyncio task, and it runs only
under ``Live`` (never during input), so there is no terminal-ownership conflict.

v1 is single-line (Enter submits); multiline (Esc+Enter submit) is a follow-on.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console

from cairn.core.paths import ensure_dirs, history_dir

__all__ = ["COMMAND_NAMES", "BasicInput", "InputUI", "PromptKitInput", "build_completer"]

# Slash commands the REPL dispatches. Kept in sync with interfaces/repl.py; the
# snapshot test in test_input.py catches drift.
COMMAND_NAMES = (
    "/help",
    "/model",
    "/plugins",
    "/workspace",
    "/files",
    "/skills",
    "/graph",
    "/audit",
    "/usage",
    "/reset",
    "/quit",
    "/exit",
    "/q",
)

# Word boundary that keeps "/" and "-" (skill names like "domain-recon") in the
# token being completed, so "/he" -> "/help" and "/dom" -> "/domain-recon".
_WORD_PATTERN = re.compile(r"[\w/.-]+")

_PROMPT_TEXT = FormattedText([("class:cairn-prompt", "cairn> ")])
_PROMPT_STYLE = Style.from_dict({"cairn-prompt": "bold cyan"})


class InputUI(Protocol):
    """Read one input line from the user (between turns, ``Live`` stopped)."""

    def read_prompt(self, console: Console) -> str: ...


def build_completer(skills: Mapping[str, Any]) -> WordCompleter:
    """Tab completions for slash commands + ``/<skill>`` names.

    File-path completion for ``@file`` is deferred — it needs a workspace-scoped
    completer; slash + skill coverage is the v1 core.
    """
    words: list[str] = list(COMMAND_NAMES) + [f"/{s.name}" for s in skills.values()]
    return WordCompleter(words, ignore_case=True, pattern=_WORD_PATTERN)


class BasicInput:
    """Pre-U2 behavior: Rich ``console.input``."""

    def read_prompt(self, console: Console) -> str:
        return console.input("[bold cyan]cairn>[/bold cyan] ")


class PromptKitInput:
    """prompt_toolkit input: persistent history + completion + emacs/vi keys.

    Owns the terminal only while reading a line (``Live`` stopped between turns).
    ``EOFError`` (Ctrl-D) and ``KeyboardInterrupt`` (Ctrl-C) propagate to the REPL
    loop exactly as ``console.input`` does, so the existing exit handling is
    unchanged.
    """

    def __init__(self, *, skills: Mapping[str, Any]) -> None:
        ensure_dirs()
        self._session: PromptSession = PromptSession(
            history=FileHistory(str(history_dir() / "repl.txt")),
            completer=build_completer(skills),
            complete_while_typing=True,
            style=_PROMPT_STYLE,
        )

    def read_prompt(self, console: Console) -> str:
        return self._session.prompt(_PROMPT_TEXT)
