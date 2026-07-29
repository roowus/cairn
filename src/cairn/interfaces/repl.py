"""Interactive REPL — the primary Cairn interface (Rich-powered)."""

from __future__ import annotations

import os
import re
import sys

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cairn import __version__
from cairn.core.logging import setup_logging
from cairn.interfaces.interrupt import TurnCancelled, run_cancellable
from cairn.interfaces.tui.input import BasicInput, PromptKitInput

HELP = """\
[bold]Cairn REPL[/bold] — describe what to investigate in plain English.

[bold]Commands:[/bold]
  /help           show this help
  /model          list LLM profiles (★ = current, ✓ = credentials found)
  /model NAME     switch model (e.g. /model grok, /model glm)
  /plugins        list available OSINT tools
  /workspace      show the workspace tree (cwd + scratch); alias /files
  /skills         list investigation playbooks
  /<skill> X      run a playbook on target X (e.g. /domain-recon example.com)
  /graph          show captured entities so far
  /audit [N]      show the last N audited tool calls
  /usage          show credits/time/quota used this session
  /reset          clear conversation history
  /quit           exit

[bold]Shell & files (user-trusted — not audited, not wrapped):[/bold]
  !command        run a shell command, print its output
  !!command       run a shell command; capture its output into your NEXT prompt
  @path           inline a workspace file's contents into your prompt

[bold]During a turn:[/bold] press [bold]Esc[/bold] or [bold]Ctrl-C[/bold] to stop the agent.

Anything else is sent to the analyst agent as an investigation request.
"""

_INLINE_MAX_BYTES = 200_000  # cap per @file inlined into a prompt
# @path tokens: `@` not preceded by a word char or `/` (so emails like a@b.com
# and slash paths stay literal), followed by non-space chars.
_ATFILE_RE = re.compile(r"(?<![\w/])@([^\s@]+)")


async def _run_user_shell(cmd: str):
    """Run a user ``!``/``!!`` shell command with a scrubbed env.

    User-trusted passthrough: the output is the user's own command result, so it is
    printed/injected raw — it never enters the audited tool closure and is never
    wrapped in ``<untrusted_external_data>``. The env is still scrubbed so ``!env``
    can't dump an exported LLM key to the terminal.
    """
    from cairn.execution.subprocess_util import run_shell
    from cairn.execution.workspace import scrub_env

    return await run_shell(cmd, env=scrub_env(os.environ))


def _expand_atfiles(console: Console, session: object, line: str) -> str:
    """Inline ``@path`` tokens with in-workspace file contents.

    User-trusted: inlined text is the user's own selection, so it enters the prompt
    directly (NOT wrapped). Out-of-workspace ``@path`` is left literal with a
    warning; each file is capped at ``_INLINE_MAX_BYTES``.
    """
    from cairn.execution.workspace import resolve_in_workspace, workspace_roots

    roots = workspace_roots(session.ctx)  # type: ignore[attr-defined]

    def _repl(m: re.Match[str]) -> str:
        token = m.group(1)
        resolved = resolve_in_workspace(token, roots)
        if resolved is None:
            console.print(f"[yellow]@{token} outside workspace — left literal.[/yellow]")
            return m.group(0)
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            console.print(f"[yellow]@{token} unreadable ({exc}) — left literal.[/yellow]")
            return m.group(0)
        if len(text) > _INLINE_MAX_BYTES:
            text = text[:_INLINE_MAX_BYTES] + "\n…(truncated)"
        return f"contents of @{token}:\n```\n{text}\n```"

    return _ATFILE_RE.sub(_repl, line)


def _banner(console: Console, tool_count: int, model: str | None, mode: str) -> None:
    mode_tag = (
        " [yellow](challenge mode — active artifact analysis)[/yellow]"
        if mode == "challenge"
        else ""
    )
    console.print(
        Panel.fit(
            f"[bold cyan]cairn[/bold cyan] v{__version__} — agentic OSINT{mode_tag}\n"
            f"[dim]{tool_count} tool(s) available · model: {model or 'unknown'} · "
            f"mode: {mode}[/dim]\n"
            f"[dim]Type /help for commands. Esc/Ctrl-C stops a turn. "
            f"Ctrl-D / /quit exits.[/dim]\n"
            f"[dim]External CLIs (sherlock, holehe) auto-install — no /install needed.[/dim]",
            border_style="cyan",
        )
    )


def _bootstrap_cli_tools(console: Console, loop: object) -> None:
    """Install any missing allowlisted CLIs at startup (silent if already present)."""
    from cairn.execution.cli_tools import (
        ensure_missing_cli_tools,
        list_cli_tools,
        tool_is_installed,
    )

    missing = [
        t.name
        for t in list_cli_tools()
        if t.bootstrap and t.manager == "uv" and not tool_is_installed(t)
    ]
    if not missing:
        return
    console.print(
        f"[dim]Installing missing tools:[/dim] {', '.join(missing)} "
        f"[dim](one-time, via uv)…[/dim]"
    )
    try:
        rows = loop.run_until_complete(ensure_missing_cli_tools(install=True))  # type: ignore[attr-defined]
    except Exception as exc:
        console.print(f"[yellow]Auto-install skipped:[/yellow] {exc}")
        return
    for name, ok, msg in rows:
        if msg == "already installed":
            continue
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"  {mark} [cyan]{name}[/cyan] [dim]{msg.splitlines()[0][:100]}[/dim]")


def _cmd_workspace(console: Console, session: object) -> None:
    """Render the workspace tree (cwd + scratch) — challenge files + downloads."""
    from cairn.execution.workspace import list_workspace_tree, workspace_roots

    roots = workspace_roots(session.ctx)  # type: ignore[attr-defined]
    body = list_workspace_tree(roots) or "(workspace is empty)"
    console.print(Panel(body, title="Workspace (cwd + scratch)", border_style="cyan"))


def _cmd_plugins(console: Console, session: object) -> None:
    from cairn.execution.base import plugin_status, plugin_tier

    table = Table(title="Plugins (tier · brain status)", show_header=True, header_style="bold")
    table.add_column("name", style="cyan")
    table.add_column("category", style="green")
    table.add_column("tier", style="yellow")
    table.add_column("status", style="magenta")
    for p in sorted(session.registry.all(), key=lambda x: x.name):  # type: ignore[attr-defined]
        table.add_row(
            p.name,
            p.category,
            plugin_tier(p),
            plugin_status(p, session.ctx),  # type: ignore[attr-defined]
        )
    console.print(table)


def _cmd_graph(console: Console, session: object) -> None:
    console.print(f"[bold]Graph:[/bold] {session.graph_summary()}")  # type: ignore[attr-defined]
    for e in session.graph.entities():  # type: ignore[attr-defined]
        console.print(f"  · [cyan]{e.type}[/cyan] {e.value}")


def _cmd_audit(console: Console, session: object, n: int) -> None:
    rows = session.db.execute(  # type: ignore[attr-defined]
        "SELECT ts, tool, target, status FROM audit_log ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    if not rows:
        console.print("[dim]No tool calls audited yet.[/dim]")
        return
    table = Table(title=f"Last {len(rows)} tool call(s)", show_header=True, header_style="bold")
    table.add_column("time", style="dim")
    table.add_column("tool", style="cyan")
    table.add_column("target", style="green")
    table.add_column("status", style="magenta")
    for r in rows:
        table.add_row(r["ts"][11:19], r["tool"], r["target"] or "", r["status"])
    console.print(table)


def _cmd_skills(console: Console, skills: dict[str, object]) -> None:
    table = Table(title="Skills (investigation playbooks)", show_header=True, header_style="bold")
    table.add_column("command", style="cyan")
    table.add_column("description")
    for s in sorted(skills.values(), key=lambda x: x.name):  # type: ignore[attr-defined]
        table.add_row(f"/{s.name}", s.description)  # type: ignore[attr-defined]
    console.print(table)


def _cmd_usage(console: Console, session: object) -> None:
    """Per-source credits/time/quota used so far this session."""
    from cairn.interfaces.usage_view import render_usage

    sources = session.usage.sources()  # type: ignore[attr-defined]
    if not sources:
        console.print("[dim]No tool calls yet this session.[/dim]")
        return
    render_usage(console, sources, title="Session usage")


def _cmd_model(console: Console, session: object, arg: str) -> None:
    """List or switch LLM profiles."""
    from cairn.core.errors import ConfigError
    from cairn.reasoning.catalog import current_profile_name, list_profiles

    arg = (arg or "").strip()
    if not arg or arg in {"list", "ls", "?"}:
        current = current_profile_name(session.settings)  # type: ignore[attr-defined]
        table = Table(
            title=f"Models (current: {session.model_name})",  # type: ignore[attr-defined]
            show_header=True,
            header_style="bold",
        )
        table.add_column("", width=1)
        table.add_column("name", style="cyan")
        table.add_column("model id", style="green")
        table.add_column("creds", style="magenta")
        table.add_column("description")
        for profile, available in list_profiles(session.settings):  # type: ignore[attr-defined]
            star = (
                "★"
                if profile.name == current or profile.model == getattr(session, "model_name", None)
                else ""
            )
            table.add_row(
                star,
                profile.name,
                profile.model,
                "✓" if available else "—",
                profile.description,
            )
        console.print(table)
        console.print("[dim]Switch with[/dim] /model <name>  [dim]e.g.[/dim] /model grok")
        return

    try:
        new_name = session.switch_model(arg)  # type: ignore[attr-defined]
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    except Exception as exc:
        console.print(f"[red]Failed to switch model:[/red] {exc}")
        return
    console.print(f"[green]Model →[/green] [bold]{new_name}[/bold]")


def _run_turn(console: Console, loop: object, session: object, prompt: str) -> None:
    """Stream one agent turn: live answer + tool cards + statusline, sealed into
    scrollback. The sealed statusline (model · cumulative LLM tokens · tool calls
    · paid spend · hints) is the persistent cost indicator, replacing the old
    per-turn delta line. Esc or Ctrl-C cancels the in-flight turn without exiting
    the REPL.
    """
    from cairn.interfaces.tui.live_turn import run_turn

    try:
        run_cancellable(
            loop,  # type: ignore[arg-type]
            run_turn(  # type: ignore[arg-type]
                session, prompt, console=console, show_status=True, status_hints=True
            ),
        )
    except TurnCancelled as exc:
        console.print(f"[yellow]Stopped.[/yellow] [dim]{exc}[/dim]")
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")


def repl(*, basic: bool = False) -> None:
    """Launch the interactive REPL (synchronous entry point).

    ``basic`` (or ``CAIRN_BASIC_INPUT=1``, or a non-TTY stdin) selects the
    pre-U2 Rich ``console.input`` backend instead of prompt_toolkit.
    """
    import asyncio

    setup_logging()
    console = Console()
    from cairn.orchestration.session import Session
    from cairn.skills import discover_skills, render_turn

    try:
        session = Session()
    except Exception as exc:
        console.print(f"[red]Failed to start session:[/red] {exc}")
        raise typer.Exit(1) from None

    model = session.model_name
    skills = discover_skills()
    # Input backend: prompt_toolkit on a TTY (history + completion + emacs keys);
    # else Rich console.input (pre-U2 behavior, also used for --basic / non-TTY).
    use_basic = basic or os.environ.get("CAIRN_BASIC_INPUT", "").strip() in (
        "1",
        "true",
        "yes",
    )
    input_ui = (
        BasicInput()
        if (use_basic or not sys.stdin.isatty())
        else PromptKitInput(skills=skills)
    )
    _banner(console, session.tool_count, model, getattr(session.settings, "mode", "investigate"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # Provision sherlock/holehe/etc. so the user never has to /install.
    _bootstrap_cli_tools(console, loop)
    pending_injection: str | None = None  # captured `!!` output → prepended to next prompt
    try:
        while True:
            try:
                line = input_ui.read_prompt(console).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]bye.[/dim]")
                break
            # A captured `!!` shell output is prepended to the next non-command prompt.
            if pending_injection is not None:
                inj = pending_injection
                pending_injection = None
                if line and not line.startswith(("!", "/")):
                    line = f"{inj}\n\n{line}"
            if not line:
                continue
            # `!`/`!!` shell passthrough — USER-trusted: printed/injected raw,
            # never wrapped in <untrusted_external_data> and never audited.
            if line.startswith("!"):
                capture = line.startswith("!!")
                cmd = (line[2:] if capture else line[1:]).strip()
                if cmd:
                    result = loop.run_until_complete(_run_user_shell(cmd))
                    out = result.stdout.decode(errors="replace")
                    if capture:
                        pending_injection = out
                        console.print(
                            f"[dim]! captured {len(out)} chars → prepended to next prompt.[/dim]"
                        )
                    else:
                        console.print(out, end="" if out.endswith("\n") else "\n")
                        if result.returncode:
                            console.print(f"[dim](exit {result.returncode})[/dim]")
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line == "/help":
                console.print(Panel(HELP, border_style="dim"))
                continue
            if line in ("/workspace", "/files"):
                _cmd_workspace(console, session)
                continue
            if line == "/plugins":
                _cmd_plugins(console, session)
                continue
            if line == "/skills":
                _cmd_skills(console, skills)
                continue
            if line == "/model" or line.startswith("/model "):
                arg = line[len("/model") :].strip()
                _cmd_model(console, session, arg)
                continue
            if line == "/graph":
                _cmd_graph(console, session)
                continue
            if line.startswith("/audit"):
                parts = line.split(maxsplit=1)
                n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
                _cmd_audit(console, session, n)
                continue
            if line == "/usage":
                _cmd_usage(console, session)
                continue
            if line == "/reset":
                session.history.clear()
                console.print("[dim]Conversation history cleared.[/dim]")
                continue
            if line.startswith("/"):
                head, _, rest = line.partition(" ")
                name = head[1:]
                if name in skills:
                    prompt = render_turn(skills[name], rest or "(no target given)")
                    _run_turn(console, loop, session, prompt)
                    continue
                console.print(f"[yellow]Unknown command:[/yellow] {line}  (try /help)")
                continue

            _run_turn(console, loop, session, _expand_atfiles(console, session, line))
    finally:
        loop.run_until_complete(session.aclose())
        loop.close()
