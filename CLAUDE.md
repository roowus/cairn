# CLAUDE.md

Cairn — terminal-native **agentic OSINT** CLI ("Claude Code for OSINT"). Local:
`~/projects/cairn`. Public: https://github.com/roowus/cairn. Python `>=3.12`
(local pin 3.14 via `.python-version`; CI currently runs 3.13) + uv, src-layout.
**Read [CONTRIBUTING.md](CONTRIBUTING.md) first** — full setup, day-to-day
commands, plugin-authoring, and the rules below in more detail.

## Never-break invariants (load-bearing — do not regress)

1. **Hard-stop / anti-injection.** Every tool result the model sees is wrapped in
   `<untrusted_external_data>` via `wrap_untrusted` (`core/security.py`), applied by
   the audited `_tool` closure in `orchestration/tool_adapter.py`. Subprocesses use
   `create_subprocess_exec` with **array args, never `shell=True`**
   (`execution/subprocess_util.py`). Scraped pages, breaches, challenge files are
   adversarial — never let them reach the model unwrapped.
2. **No upward imports.** `reasoning` imports nothing from `orchestration` /
   `execution` / `subprocess` / `socket`. `tests/unit/test_layering.py` enforces it.
3. **Secrets never enter model context.** API keys live in `PluginContext.keys`
   (`SecretStr`) and LLM creds in settings / `~/.pi/agent/auth.json` — never in
   prompts, tool summaries, or unscrubbed subprocess env (`scrub_env`).
4. **Free-first; no paid platforms.** Bright Data / SerpAPI / TinEye / facecheck are
   excluded. Free-tier-with-key APIs are OK as optional plugins. Don't burn web-search
   credits on large-scale research — **ask the user first**.
5. **Allowlisted installs only.** External CLIs install only via the fixed map in
   `execution/cli_tools.py` (`uv tool install <fixed package>`). No general
   `run_shell` install tool for the model.
6. **Honesty about containment.** "Auto-allow in workspace" is a *policy* boundary,
   not OS-enforced containment. Never claim airtight sandboxing.

## Working rules (apply on every change)

- **Never `ruff check --fix`** — find issues with `uv run ruff check .` and fix by
  hand. **Re-read any file before editing it** (parallel contributors edit this repo
  concurrently). Verify doc claims against the code before trusting them.
- **Keep it green:** `uv run pytest -q -m "not network"` and `uv run ruff check .`.
  Network tests (`-m network`) hit real free APIs — run locally only when a plugin
  changes; they're skipped in CI.

## Commit / push policy (multi-session safe)

Commit/push **when work is green AND the edit surface is disjoint from other
in-flight sessions** — re-read changed files, confirm no clash, never force-push
`main`, use Conventional Commits (`type(scope): summary`). Anything non-trivial
goes through a **branch + PR** using `.github/PULL_REQUEST_TEMPLATE.md` (tick the
regression-rules checklist). CI gates: `ruff check`, `pytest -m "not network"`,
`mypy` (non-blocking).

## Parallel-session file ownership

Multiple Claude/agent sessions edit this repo at once. To avoid merge collisions:
**rebase onto `main` before starting**; pick files **disjoint** from other in-flight
work; work on a branch + PR. The active UI overhaul (U1–U6) owns
`interfaces/repl.py`, `interfaces/tui/*`, `orchestration/session.py`; the
parallel-sessions backend owns `orchestration/session_pool.py` + the shared audit
log. The backlog lives in [GitHub issues](https://github.com/roowus/cairn/issues);
strategy in [docs/strategy.md](docs/strategy.md).
