# UI overhaul — the "function like pi" terminal interface

Cairn's REPL is a live, pi/Claude-Code-style terminal app: the brain's answer
streams in place, tool calls animate as cards, and a statusline persists — all
sealed into scrollback (no vanishing frames). This doc records what the UI
overhaul (**U1–U6**) shipped, the load-bearing invariant it preserves, and the
per-unit design decisions. (The older `docs/ui-overhaul-plan.md` is the
pre-build plan, superseded by what's described here.)

## The structural invariant (load-bearing)

Rich `Live` and the prompt_toolkit input loop **both own the terminal** and must
never run concurrently, or output garbles and keystrokes drop. So every turn is
strictly two phases, never overlapping:

1. **input idle** — read the user's line (prompt_toolkit) with `Live` stopped;
2. **input stopped** — run the turn under a per-turn `Live(transient=False)`
   region that seals its final frame into scrollback on exit.

No alt-screen / fullscreen (that destroys scrollback, contradicting "feel like
pi"). The zoned "chrome" is therefore a **per-turn block** sealed into scrollback
(header + boxed tools + boxed answer + footer), **not** a screen-fixed bar.
Textual `--tui` alt-screen mode remains out of scope.

## What shipped (U1–U6)

### U1 — Zoned chrome
Each turn renders as a structured block: a **header** line
(`cairn · model · mode · ↑↓tok · N tools · paid`), a boxed **tools** panel (the
ToolCards), a boxed **answer** panel (the streamed Markdown), and a **footer**
(`/help · Esc stop`). `tui/header.py` reuses the statusline data. Headless
(`cairn search`) keeps the flat pipe-friendly output via
`run_turn(..., chrome=False)`.

### U2 — prompt_toolkit input
`tui/input.py` `PromptKitInput` — persistent history
(`~/.cairn/history/repl.txt`), tab completion (slash commands + `/<skill>`
names), emacs keys — on a TTY. `--basic` / `CAIRN_BASIC_INPUT=1` / non-TTY fall
back to Rich `console.input`. Esc-during-turn cancel is unchanged (the cbreak
`_KeyWatcher` in `interrupt.py`, active only under `Live`, never during input).

### U3 — Collapsible thinking + live CLI stdout
- **Thinking**: `ThinkingDelta` events render a collapsed `thinking ▸ (N lines)`
  indicator above the tools panel. No expand key in v1 (`Live` doesn't own stdin;
  a toggle needs the deferred fullscreen input ownership).
- **Live stdout**: `run_command` / `sherlock` / `holehe` stream stdout line-by-line
  into their card. The per-call `tool_call_id` is bridged from the tool closure to
  the deep `run_shell`/`run_subprocess` path by a **ContextVar**
  (`execution/tool_progress.py`): the closure binds it around `plugin.run()`, and
  `progress_for(ctx)` builds the `on_line` callback. asyncio copies a ContextVar
  per Task, and PydanticAI runs each tool as its own Task, so **concurrent tool
  calls don't clobber each other's id** — guarded by
  `test_contextvar_isolates_per_concurrent_task`. `on_line=None` keeps the buffered
  `communicate()` path for every other caller (and headless).

### U4 — `!`/`!!` shell + `@file` inline (user-trusted)
`!command` runs a shell command (scrubbed env) and prints output (exit code shown
on non-zero); `!!command` captures it into the next prompt; `@path` inlines an
in-workspace file (cap 200 KB; out-of-workspace left literal with a warning;
emails `a@b.com` are not expanded). These are **user-trusted** — they deliberately
bypass `<untrusted_external_data>` and the audit log (the user's own command/file,
not model-selected external data). The `!` env is still scrubbed so `!env` can't
dump an exported key.

### U5 — Theme tokens
`tui/theme.py` centralizes the Rich `Style` palette (frozen `Theme` + singleton).
The renderers (cards, statusline, live_turn panel borders, header,
thinking_stream) import tokens instead of scattered `[cyan]`/`[dim]` literals, so
a future light/dark theme or a11y tweak changes one place. Verified
**render-identical** via a truecolor ANSI before/after diff (empty). REPL
command/banner markup keeps inline color names (disproportionate to convert from
markup to `Style` objects).

### U6 — JSONL sessions + `/compact` `/resume` `/fork`
On-disk snapshots at `~/.cairn/sessions/<id>.jsonl` — a header line
(`SessionMeta`) + one `{"msg": ...}` line per model message, serialized via
pydantic-ai's `ModelMessagesTypeAdapter` with **`mode="json"`** so datetimes
round-trip through `json.dumps`. Malformed lines are skipped+logged, never raised.
`Session` gains `session_id` (uuid hex) + `persist`; the REPL runs `persist=True`
(headless stays `False`). Commands: `/sessions` (list), `/resume <id>` (load
history into the live session), `/compact` (summarize via one model turn with
`persist=False`, then keep only the compaction turn — system prompt is re-injected
by the agent each run, so continuity survives), `/fork` (snapshot under a new id).

## Coordination with the parallel-sessions backend (#2)
#2's `SessionPool` (`orchestration/session_pool.py`) runs N concurrent sessions on
one loop with a shared audit log. It tracks session ids **externally** (sets
`session.audit.session_id`) and named its REPL surface `/pool` (not `/sessions`)
to avoid colliding with U6's resume-lister. U6's `Session.session_id` is the
**canonical** id; `audit.session_id` is a separate (parallel-session) tag. The
`/spawn` command + laned multi-session UI remain (tracked in #2).

## File map
- `interfaces/tui/header.py` — header/footer chrome lines.
- `interfaces/tui/live_turn.py` — the per-turn `Live` region + `_Composer` (zoned frame).
- `interfaces/tui/cards.py` — `ToolCard` (keyed by `tool_call_id`; streamed body).
- `interfaces/tui/thinking_stream.py` — collapsed thinking accumulator.
- `interfaces/tui/markdown_stream.py` — throttled streaming Markdown.
- `interfaces/tui/statusline.py` — the flat statusline (headless / legacy).
- `interfaces/tui/theme.py` — the `Style` palette singleton.
- `interfaces/tui/input.py` — prompt_toolkit `PromptKitInput` + `BasicInput`.
- `interfaces/tui/permission_panel.py` — `RichPermissionUI` v2 seam (not wired into the live turn).
- `interfaces/repl.py` — the REPL loop, `!`/`!!`/`@file`, slash commands.
- `execution/tool_progress.py` — the `tool_call_id` ContextVar bridge.
- `execution/subprocess_util.py` — `_exec_stream` (line-by-line) + `on_line`.
- `storage/sessions.py` — the JSONL session store.
- `orchestration/session.py` — `session_id` / `persist` / `load_history` / `compact` / `fork_snapshot`.
