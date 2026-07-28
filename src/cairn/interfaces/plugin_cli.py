"""Dynamic per-plugin CLI subcommands.

Every discovered plugin becomes a ``cairn plugin <name>`` subcommand, runnable
without the LLM. The command signature mirrors the plugin's ``PluginInput``
fields.
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer

from cairn.core.logging import setup_logging
from cairn.execution.registry import discover
from cairn.execution.runner import build_context, close_context
from cairn.orchestration.tool_adapter import _apply_signature


def build_plugin_cli() -> typer.Typer:
    """Build the `cairn plugin ...` command group from discovered plugins."""
    app = typer.Typer(
        name="plugin",
        help="Run an OSINT plugin directly (no LLM), or list them.",
        no_args_is_help=True,
        add_completion=False,
    )
    registry = discover()
    app.command(name="list")(_make_list_cmd(registry))
    for plugin in registry.all():
        app.command(name=plugin.name.replace("_", "-"))(_make_cmd(plugin))
    return app


def _make_list_cmd(registry: Any) -> Any:
    def _list() -> None:
        from rich.console import Console
        from rich.table import Table

        from cairn.execution.base import cost_label, plugin_status, plugin_tier

        setup_logging()
        ctx = build_context()
        try:
            console = Console()
            table = Table(title=f"{len(registry)} plugin(s)", show_header=True, header_style="bold")
            table.add_column("name", style="cyan")
            table.add_column("category", style="green")
            table.add_column("tier", style="yellow")
            table.add_column("cost", style="magenta")
            table.add_column("status")
            for p in sorted(registry.all(), key=lambda x: x.name):
                table.add_row(
                    p.name.replace("_", "-"),
                    p.category,
                    plugin_tier(p),
                    cost_label(p),
                    plugin_status(p, ctx),
                )
            console.print(table)
        finally:
            asyncio.run(close_context(ctx))

    return _list


def _make_cmd(plugin: Any) -> Any:
    input_model = plugin.input_model

    async def _run(**kwargs: Any) -> None:
        ctx = build_context()
        try:
            out = await plugin.run(input_model.model_validate(kwargs), ctx)
            typer.echo(out.summary_markdown)
        except Exception as exc:
            typer.secho(f"Error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from None
        finally:
            await close_context(ctx)

    def _entry(**kwargs: Any) -> None:
        setup_logging()
        asyncio.run(_run(**kwargs))

    _apply_signature(_entry, input_model, plugin.name.replace("_", "-"), plugin.describe())
    return _entry
