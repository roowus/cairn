"""The streaming terminal UI — a Rich ``Live`` differential repaint + prompt_toolkit input.

This package renders Cairn's turns like ``pi`` / Claude Code: **inline, with
scrollback preserved** (no alt-screen). It consumes the stable
:data:`~cairn.orchestration.events.TurnEvent` stream produced by
:meth:`cairn.orchestration.session.Session.iter_turn` — never a PydanticAI type.

.. structural-invariant::

    Rich ``Live`` and the prompt_toolkit input loop **both own the terminal** and
    must never run concurrently, or output garbles and keystrokes drop. So every
    turn is strictly two phases, never overlapping:

    1. **input idle** — read the user's line (prompt_toolkit) with ``Live`` stopped,
    2. **input stopped** — run the turn under a per-turn ``Live(transient=False)``
       region that seals its final frame into scrollback on exit.

    No code path may hold a ``Live`` region open while prompting for input.
"""

from __future__ import annotations
