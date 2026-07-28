"""Cairn command-line entry point.

Commands:
  cairn                    launch the interactive REPL (default)
  cairn repl               same as above
  cairn search <query>     one-shot agentic query
  cairn plugin <name> …    run an OSINT plugin directly (no LLM)
  cairn plugins            list discovered plugins (tier + cost)
  cairn usage              show credits/time/quota used (from the audit log)
  cairn --version
"""

from __future__ import annotations

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from cairn import __version__
from cairn.interfaces.headless import search as _search
from cairn.interfaces.plugin_cli import build_plugin_cli
from cairn.interfaces.repl import repl as _repl

app = typer.Typer(
    name="cairn",
    help="Terminal-native agentic OSINT assistant.",
    add_completion=False,
    no_args_is_help=False,
)
app.add_typer(build_plugin_cli(), name="plugin")
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"cairn {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Cairn — agentic OSINT in your terminal."""
    if ctx.invoked_subcommand is None:
        _repl()


@app.command("repl")
def repl_cmd() -> None:
    """Launch the interactive REPL."""
    _repl()


@app.command("search")
def search_cmd(
    query: list[str] = typer.Argument(  # noqa: B008
        None, help="A natural-language investigation request."
    ),
) -> None:
    """Run a one-shot agentic query, e.g. `cairn search look up 8.8.8.8`."""
    if not query:
        console.print("[red]Provide a query:[/red] cairn search <your question>")
        raise typer.Exit(code=1)
    _search(" ".join(query))


@app.command("plugins")
def list_plugins(
    all: bool = typer.Option(
        False, "--all", help="(no-op) all plugins are always shown now."
    ),
) -> None:
    """List discovered OSINT plugins (tier, cost, and whether the brain will use them)."""
    from cairn.execution.base import cost_label, plugin_status, plugin_tier
    from cairn.execution.registry import discover
    from cairn.execution.runner import build_context

    _ = all  # kept for backward compatibility; listing is always complete
    ctx = build_context()
    registry = discover()
    table = Table(title="Cairn plugins", box=box.ROUNDED)
    table.add_column("name", style="cyan")
    table.add_column("category", style="green")
    table.add_column("tier", style="yellow")
    table.add_column("cost", style="magenta")
    table.add_column("status")
    for p in sorted(registry.all(), key=lambda x: x.name):
        table.add_row(p.name, p.category, plugin_tier(p), cost_label(p), plugin_status(p, ctx))
    console.print(table)


@app.command("usage")
def usage_cmd() -> None:
    """Show credits/time/quota used across all past runs (from the audit log)."""
    from cairn.core.config import load_settings
    from cairn.interfaces.usage_view import build_usage_table, usage_line
    from cairn.orchestration.usage import aggregate_history
    from cairn.storage.db import Database

    settings = load_settings()
    db = Database(settings.data_dir / "cairn.db")
    db.init()
    try:
        sources = aggregate_history(db)
    finally:
        db.close()
    if not sources:
        console.print("[dim]No tool calls recorded yet (audit log is empty).[/dim]")
        return
    console.print(build_usage_table(sources, title="Usage — all runs (audit log)"))
    console.print(f"[dim]{usage_line(sources)}[/dim]")


def main() -> None:
    """Entry point for the `cairn` console script."""
    app()


if __name__ == "__main__":
    main()
