"""Headless parallel-session runner: N investigations at once via SessionPool.

This is the clash-free end-to-end surface for issue #2's backend foundation. It
drives :meth:`Session.ask <cairn.orchestration.session.Session.ask>` directly
(plain text, no Rich ``Live`` / TUI), so it never touches the REPL or
``interfaces/tui/*`` files another contributor is editing. The laned UI and a
``/spawn`` REPL command land later, behind U6 — see
``docs/architecture/parallel-sessions.md``.

Usage: ``cairn parallel "<q1>" "<q2>" ...`` — each argument is one independent
investigation run as its own pooled session, capped at
``max_concurrent_sessions``. Outputs are printed per session, then the merged
entity graph summary.
"""

from __future__ import annotations

import asyncio

from rich.console import Console

from cairn.core.logging import setup_logging
from cairn.orchestration.session_pool import SessionPool


async def run_parallel(
    queries: list[str],
    *,
    console: Console | None = None,
    max_concurrent: int | None = None,
) -> dict[str, str]:
    """Run each query as its own pooled session concurrently; return ``{id: answer}``.

    Each session shares the plugin registry and the audit *file* (rows tagged
    with the session id) but keeps its own history/graph. Prints a per-session
    readout and a merged-graph summary. The hard-stop is unchanged — every
    session rides the audited tool closure.
    """
    console = console or Console()
    setup_logging()
    if not queries:
        console.print("[red]Provide at least one query.[/red]")
        return {}

    pool = SessionPool(max_concurrent=max_concurrent)
    try:
        for q in queries:
            pool.spawn(q)
        console.print(
            f"[bold cyan]parallel[/bold cyan] running {len(queries)} session(s), "
            f"cap={pool.capacity}"
        )
        results = await pool.run_all()
        for ps in pool.list_live():
            if ps.error is not None:
                console.print(f"[cyan]{ps.session_id}[/cyan] [red]error:[/red] {ps.error}")
            else:
                console.print(f"[cyan]{ps.session_id}[/cyan] [green]ok[/green]")
                if ps.answer:
                    console.print(ps.answer)
        merged = pool.merge_graphs()
        console.print(
            f"[dim]merged graph: {merged.summary()} · "
            f"pool calls={pool.total_calls()}[/dim]"
        )
        return results
    finally:
        await pool.aclose()


def parallel(queries: list[str]) -> None:
    """Sync entry point for the ``cairn parallel`` command."""
    asyncio.run(run_parallel(queries))
