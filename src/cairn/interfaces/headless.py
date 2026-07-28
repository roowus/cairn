"""One-shot agentic query: ``cairn search "..."``."""

from __future__ import annotations

import asyncio

from rich.console import Console

from cairn.core.logging import setup_logging


async def run_query(query: str, *, console: Console | None = None) -> str:
    """Run a single natural-language query through a fresh session. Returns the answer.

    Streams the answer and tool progress through the same ``Live`` region the REPL
    uses (see :mod:`cairn.interfaces.tui.live_turn`); on a non-TTY pipe Rich writes
    a clean final frame instead of a differential repaint, so output stays
    pipe-friendly.
    """
    from cairn.interfaces.tui.live_turn import run_turn
    from cairn.orchestration.session import Session

    console = console or Console()
    setup_logging()
    session = Session()
    try:
        # show_status=False + chrome=False: headless has its own usage section
        # below, and on a non-TTY pipe Rich `Live` writes the final frame with no
        # trailing newline (so a statusline would run into the usage line and
        # duplicate its counts). chrome=False keeps the pre-U1 flat, pipe-friendly
        # output — no header/panels/footer.
        answer = await run_turn(
            session, query, console=console, show_status=False, chrome=False
        )
        # Usage/cost summary: metered/paid sources get a table; everyone gets a totals line.
        from cairn.interfaces.usage_view import render_usage

        render_usage(console, session.usage.sources(), title="Usage")
        return answer
    finally:
        await session.aclose()


def search(query: str) -> None:
    """Typer entry point."""
    asyncio.run(run_query(query))
