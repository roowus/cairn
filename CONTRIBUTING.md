# Contributing to Cairn

## Setup

```bash
git clone <repo> cairn && cd cairn
uv sync --extra dev
cp .env.example .env   # configure an LLM provider, or reuse pi auth (xAI/Z.AI)
make install-global    # puts `cairn` on PATH + seeds ~/.cairn/.env
```

Full operator guide: [docs/configuration.md](docs/configuration.md)
(global install, Grok/pi OAuth, `/model`, Esc-to-stop, allowlisted CLI install).

## Day-to-day

```bash
make test        # unit tests, no network
make lint format typecheck
cairn            # REPL from anywhere (after install-global)
# or: uv run cairn
```

## Adding an OSINT plugin

See [docs/plugin-authoring.md](docs/plugin-authoring.md). Short version:

```bash
uv run scripts/new_plugin.py identity my_lookup
```

Then implement `run()`, add a `respx`-mocked test, and you're done — plugins are
auto-discovered.

## Rules that must not regress

1. **No upward imports.** `reasoning` must not import from `orchestration`,
   `execution`, `subprocess`, or `socket`. `tests/unit/test_layering.py`
   enforces this.
2. **Hard-stop execution.** Tools always return sanitized Markdown summaries,
   never raw payloads, to the model.
3. **No shell strings.** All subprocesses use `create_subprocess_exec` with list
   args via `cairn.execution.subprocess_util`.
4. **Untrusted data is wrapped.** External content reaching the model goes
   through `<untrusted_external_data>` (handled centrally in `tool_adapter`).
5. **Secrets never enter model context.** Keys live in `PluginContext.keys`
   (and LLM creds in settings / pi auth — never in prompts).
6. **No arbitrary install/shell for the model.** External CLIs may only be
   installed via the allowlist in `execution/cli_tools.py`
   (`uv tool install <fixed package>`). Do not add a general `run_shell` tool.

## Committing

Keep commits focused. The `uv.lock` is committed for reproducibility.
