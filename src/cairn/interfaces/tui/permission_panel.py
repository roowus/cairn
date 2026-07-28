"""Interactive accept/deny panel for out-of-workspace agentic ops (v2 seam).

v1 ships :class:`~cairn.execution.workspace.NullPermissionUI`, so out-of-workspace
ops deny without prompting. This module is the **v2 component**: a Rich-rendered
accept/deny prompt implementing the
:class:`~cairn.execution.workspace.PermissionUI` protocol.

It is **not wired into the live turn yet.** Prompting during a streaming Rich
``Live`` region must wait for the prompt_toolkit input work (parked — see
``docs/backburner.md`` "Deferred — UI overhaul Phases 4-6") so we never run
``Live`` and interactive input concurrently. Until then it is exercised in
isolation by ``tests/unit/test_workspace_ui.py``; v1's auto-allow-in-workspace /
deny-outside policy needs no UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel

if TYPE_CHECKING:
    from cairn.execution.workspace import PermissionRequest


def parse_confirm(answer: str) -> bool:
    """True iff the user answered affirmatively (y / yes, case-insensitive)."""
    return answer.strip().lower() in {"y", "yes"}


def render_permission_request(decl: PermissionRequest) -> Panel:
    """A Rich Panel describing the out-of-workspace op awaiting a decision."""
    return Panel(
        f"[bold yellow]{decl.op}[/bold yellow] outside the workspace:\n"
        f"  [cyan]{decl.target}[/cyan]\n\n"
        f"[dim]{decl.reason}[/dim]\n\n"
        f"Allow this once? [bold]y/N[/bold]",
        title="[yellow]permission request[/yellow]",
        border_style="yellow",
    )


class RichPermissionUI:
    """:class:`PermissionUI` impl: render a panel and read a y/N confirm.

    ``request`` is async to satisfy the protocol and stay cancel-safe (a future
    prompt_toolkit-backed impl awaits a cancellable event). The blocking
    ``console.input`` here is acceptable only because v1 never wires this into
    the live turn.
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    async def request(self, decl: PermissionRequest) -> bool:
        self.console.print(render_permission_request(decl))
        try:
            answer = self.console.input("[bold]allow? (y/N):[/bold] ")
        except (EOFError, KeyboardInterrupt):
            return False
        return parse_confirm(answer)
