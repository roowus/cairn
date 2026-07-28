# UI Overhaul — Phases 4–6 Implementation Plan

> **⚠ Superseded (2026-07-28):** the active UI overhaul is now U1–U6 (zoned
> chrome ✅, prompt_toolkit input ✅, U3–U6 next — see `roadmap.md`).
> `backburner.md` is removed (moat → `strategy.md`, backlog → [GitHub issues](https://github.com/roowus/cairn/issues)).
> This doc is kept for historical design detail.

> **Status:** Plan **verified against code** (2026-07-28) — all four
> load-bearing claims check out, including the latent dead-code bug
> (`progress._status` in sherlock/holehe; no subclass sets it — Phase 5.4
> deletes it). **B1 shipped:** `src/cairn/interfaces/tui/theme.py` +
> `tests/unit/test_theme.py` (187 tests, ruff clean). Otherwise PLANNING ONLY —
> no further source modified. Derived from the verbatim
> Phase 4–6 spec (originally in `backburner.md`, since removed) § "Deferred — UI overhaul
> Phases 4–6", re-grounded against the **current** tree (re-read July 2026;
> **187 tests**, `ruff` clean). Phases 1–3 (stream + tool cards + statusline) and
> the Phase-4-agentic subset (`/workspace` command + `RichPermissionUI` seam)
> are **shipped** and explicitly excluded here.
>
> A parallel contributor may be editing concurrently; the build order in §6 is
> sequenced to keep each phase off the files another phase (or the in-progress
> agentic smoke) is touching.

---

## 0. Guiding invariants (load-bearing — every phase preserves these)

1. **Never run Rich `Live` and prompt_toolkit input concurrently.** Already
   documented as a structural invariant at
   [`src/cairn/interfaces/tui/__init__.py:8-19`](../src/cairn/interfaces/tui/__init__.py).
   The shipped design already respects it: `run_turn` opens/closes its
   `Live(transient=False)` region *inside* the turn
   ([`live_turn.py:183-196`](../src/cairn/interfaces/tui/live_turn.py)); input
   is read in a separate phase. Phase 4's prompt_toolkit swap must preserve
   this two-phase discipline.
2. **The hard-stop / anti-injection layer is untouched.** `wrap_untrusted` is
   called from exactly one site —
   [`tool_adapter.py:124`](../src/cairn/orchestration/tool_adapter.py) — and
   every agentic plugin rides the same audited `_tool` closure because they
   are `BasePlugin` subclasses. None of the work below adds a new wrap site or
   a parallel tool-registration path.
3. **Observer-only Progress hooks.** Today's hooks
   ([`progress.py:31-54`](../src/cairn/orchestration/progress.py)) cannot alter
   tool args, suppress calls, or change the answer. The new
   `on_tool_progress` hook (Phase 5) inherits that contract: default no-op,
   never influences execution.
4. **`tool_call_id` stays observer-only** — never written to `audit_log` or
   `usage`. Confirmed today; the Phase 5 stdout hook must not leak it either.

---

## 1. Shared-file collision matrix (phase × file)

Files most likely to be touched by >one phase or by the in-progress agentic
smoke (`docs/architecture/agentic-file-control.md` Phase 5 smoke = **partial** —
`read_file` verified on grok-4.5; `run_command`/`scrub_env`/Esc-cancel pending).

| File | Phase 4 | Phase 5 | Phase 6 | Agentic smoke (concurrent) |
|---|---|---|---|---|
| `src/cairn/interfaces/repl.py` | **HEAVY** (input loop, `--basic` flag, dispatch) | medium (`!`/`!!`, `@file` inline parse) | medium (`/compact`, `/resume`, `/fork`, banner theme refs) | none (smoke runs `cairn search`, headless) |
| `src/cairn/interfaces/tui/live_turn.py` | none | **HEAVY** (Thinking* events, `on_tool_progress` → card) | light (theme tokens in frame) | none |
| `src/cairn/interfaces/tui/cards.py` | none | medium (collapsible excerpt + stdout tail) | light (style tokens) | none |
| `src/cairn/interfaces/tui/markdown_stream.py` | none | medium (sibling `ThinkingStream`) | none | none |
| `src/cairn/interfaces/tui/statusline.py` | none | none | light (consume theme tokens) | none |
| `src/cairn/interfaces/tui/theme.py` *(new)* | none | none | **NEW + central** | none |
| `src/cairn/interfaces/tui/input.py` *(new)* | **NEW + central** | light (`@file` inline hooks back here) | none | none |
| `src/cairn/interfaces/tui/sessions.py` *(new)* | none | none | **NEW + central** | none |
| `src/cairn/interfaces/interrupt.py` | **HEAVY** (delete cbreak watcher or gate it behind `--basic`) | none | none | none |
| `src/cairn/orchestration/tool_adapter.py` | none | **HEAVY** (bind `tool_call_id` into per-call progress) | none | **shared** — smoke validates this closure |
| `src/cairn/orchestration/progress.py` | none | **HEAVY** (`on_tool_progress` hook) | none | **shared** — every plugin rides Progress |
| `src/cairn/orchestration/session.py` | none | none | **HEAVY** (history serialize, save-on-turn, resume load) | none |
| `src/cairn/plugins/identity/sherlock.py` | none | medium (push stdout through hook; remove dead `_status` ref) | none | **shared** |
| `src/cairn/plugins/identity/holehe.py` | none | medium (same) | none | **shared** |
| `src/cairn/execution/cli_tools.py` | none | medium (`run_cli_tool` line-stream `on_line`) | none | **shared** |
| `src/cairn/execution/subprocess_util.py` | none | medium (line-streaming `_exec` variant) | none | **shared** |
| `pyproject.toml` | **NONE** (prompt_toolkit already pinned, line 28) | NONE | NONE | NONE |

**Key correction to the backburner spec:** it lists
"`pyproject.toml` (+`prompt_toolkit>=3.0`)" under Phase 4. That work is
**already done** — [`pyproject.toml:28`](../pyproject.toml) has
`"prompt_toolkit>=3.0"` as a core dep (not an extra). No Phase-4 pyproject
edit is required.

---

## 2. Phase 4 — prompt_toolkit input

### 2.1 Scope (from `backburner.md`)

New `interfaces/tui/input.py`; simplify `interfaces/interrupt.py`;
`pyproject.toml` (+`prompt_toolkit>=3.0` — **already present**, see §1).
`PromptSession`: command **history**; **multiline** (Esc+Enter submit);
`CombinedCompleter` for slash commands + skill names + **`@file`**;
**Esc → `task.cancel()`** (delete the cbreak watcher thread; keep it as a
`--basic` / `CAIRN_BASIC_INPUT=1` fallback). **Invariant:** never run `Live`
and prompt_toolkit input concurrently — read input with `Live` stopped.

### 2.2 Current state (exists)

- **Input loop:** `repl()` at [`repl.py:249-300`](../src/cairn/interfaces/repl.py)
  — `while True: line = console.input("[bold cyan]cairn>[/bold cyan] ")`
  (line 251). Slash dispatch is a flat `if/elif` chain (lines 257-298); bare
  lines fall through to `_run_turn` (line 300).
- **Esc/Ctrl-C during a turn:** `run_cancellable` at
  [`interrupt.py:23-66`](../src/cairn/interfaces/interrupt.py) creates the
  asyncio task and, **if `sys.stdin.isatty()`** (line 37), starts the cbreak
  `_KeyWatcher` daemon thread ([`interrupt.py:74-111`](../src/cairn/interfaces/interrupt.py)).
  Detection is `ch in ("\x1b", "\x03")` at [`interrupt.py:97-99`](../src/cairn/interfaces/interrupt.py).
  `TurnCancelled` is raised at lines 54/58.
- **Fallback already exists de facto:** on a non-TTY stdin the watcher is
  never started (`if sys.stdin.isatty()` guard, line 37) and Ctrl-C still
  works through `KeyboardInterrupt` (line 47). The `--basic`/`CAIRN_BASIC_INPUT`
  flag formalizes the same path on a TTY.
- **`RichPermissionUI`** at
  [`permission_panel.py:44-62`](../src/cairn/interfaces/tui/permission_panel.py)
  is the v2 accept/deny seam, exercised in isolation by
  [`tests/unit/test_workspace_ui.py`](../tests/unit/test_workspace_ui.py). Its
  docstring (lines 8-13) states it is **not wired into the live turn yet**
  because prompting inside a streaming `Live` region must wait for this phase.
- **Skill discovery:** `discover_skills() -> dict[str, Skill]` at
  [`loader.py:97-103`](../src/cairn/skills/loader.py). Keys are the slash names
  (e.g. `investigate-person`).
- **Workspace file enumeration for `@file`:** `list_workspace_tree` at
  [`workspace.py:197-247`](../src/cairn/execution/workspace.py) (depth-limited,
  skips unreadable entries). Roots via `workspace_roots(ctx)` at
  [`workspace.py:33-44`](../src/cairn/execution/workspace.py) = `[cwd, scratch]`.
- **Structural invariant doc:** [`interfaces/tui/__init__.py:8-19`](../src/cairn/interfaces/tui/__init__.py).

### 2.3 Changes (new + edits, sequenced to minimize collision)

**Step 4.1 — NEW `src/cairn/interfaces/tui/input.py`** (no collision — new file).

- A thin wrapper around `prompt_toolkit.PromptSession` exposing
  `async def read_prompt(console, *, skills, ctx) -> str | None`.
- `PromptSession` configured with:
  - `history=FileHistory(paths.history_dir() / "repl.txt")` — `history_dir()`
    exists at [`paths.py:34-35`](../src/cairn/core/paths.py); `ensure_dirs()`
    (line 46) already mkdirs it.
  - `multiline=True` + a `prompt_toolkit.key_binding.KeyBindings` that binds
    **Esc+Enter** (and the existing **Enter** when the buffer is a single
    line) to `buffer.validate_and_handle()`. Plain **Enter** on a complete
    slash command also submits (keeps current UX).
  - **Esc in single-line mode with an empty buffer** → returns a sentinel
    that the REPL interprets as "cancel current turn" (only meaningful while a
    turn is running; otherwise no-op, matching today's behavior). The actual
    `task.cancel()` still goes through `run_cancellable`; see Step 4.3.
  - `Completer` = `CombinedCompleter(WordCompleter(slash_cmds),
    WordCompleter(skills), PathCompleter(filter_dirs=workspace_roots(ctx)))`.
    Slash-command list is derived from the `if/elif` branches so it can't
    drift (Step 4.4 makes the dispatch table the source of truth).
  - The prompt's bottom toolbar mirrors today's `[bold cyan]cairn>[/bold cyan]`
    via an HTML/formatted string (preserves the shipped look; Phase 6
    centralizes the color).
- Provide a `BasicInput` shim with the same `read_prompt` signature that just
  calls `console.input(...)` — the existing path, selected when
  `--basic` is passed or `CAIRN_BASIC_INPUT=1` is set.

**Step 4.2 — NEW `src/cairn/interfaces/tui/commands.py`** (no collision).

- Extract the slash-command dispatch currently inline in
  [`repl.py:257-300`](../src/cairn/interfaces/repl.py) into a
  `CommandRegistry` (`name → callable(console, session, arg) -> bool`).
  Each command becomes a small registered function (`/help`, `/model`,
  `/plugins`, `/workspace`/`/files`, `/skills`, `/graph`, `/audit`, `/usage`,
  `/reset`, `/quit`, and the skill dispatcher at lines 290-298).
- This is **preparation for Phase 6** (`/compact`, `/resume`, `/fork`) and
  lets `input.py` derive the `WordCompleter` list from the registry itself
  (no drift). It is a pure refactor — behavior byte-identical — landing
  before any prompt_toolkit swap so the swap is the only behavior delta.

**Step 4.3 — EDIT `src/cairn/interfaces/interrupt.py`** (collision-free;
nothing else in scope touches it).

- Add a prompt_toolkit-native cancel path. With prompt_toolkit owning the
  terminal, the cbreak watcher is both wrong (fights prompt_toolkit for the
  TTY) and unnecessary (prompt_toolkit key bindings can fire a callback
  directly). Two options:
  - **(A) Preferred:** the turn runs with input *closed* (Live owns the
    terminal); Esc cancellation during a turn is delivered by a tiny
    prompt_toolkit `Application` (alt not used — just a key binding) that we
    spawn for the duration of the turn, or by keeping the cbreak watcher
    **only while Live is active** (Live renders frames; the watcher reads
    stdin; they don't fight because prompt_toolkit is stopped).
  - **(B) Keep `run_cancellable` + `_KeyWatcher` exactly as-is** for the
    turn-cancel path, and use prompt_toolkit **only** for the input phase
    (where it replaces `console.input`). This is the smallest change and
    preserves the [`test_interrupt.py`](../tests/unit/test_interrupt.py)
    coverage unchanged. **Recommended for v1** — the watcher and
    prompt_toolkit never touch the TTY at the same time, satisfying the
    invariant without rewriting cancel.
- Either way: gate the watcher behind `not basic_input` so `--basic` /
  `CAIRN_BASIC_INPUT=1` is the documented escape hatch. The existing
  `sys.stdin.isatty()` guard stays.

**Step 4.4 — EDIT `src/cairn/interfaces/repl.py`** (only file shared with
Phase 5/6 — sequence LAST among Phase-4 steps; see §6).

- Replace `console.input(...)` at line 251 with `await input_ui.read_prompt(...)`.
  Because `repl()` is currently synchronous (`loop.run_until_complete`),
  either (a) make `repl()` drive an inner `async def _arepl()` via
  `loop.run_until_complete` (minimal asyncio surface, matches the existing
  `loop` setup at lines 244-247), or (b) use prompt_toolkit's sync entry.
  Recommendation: (a) — keeps the cancel path (`run_cancellable`) identical.
- Add the `--basic` Typer option on `repl_cmd` / `_main` in
  [`cli.py:41-61`](../src/cairn/cli.py) and read `CAIRN_BASIC_INPUT` env in
  `repl()`. The flag selects `BasicInput` vs the prompt_toolkit impl.
- Dispatch via the `CommandRegistry` from Step 4.2.

**Step 4.5 — Opportunistic, NOT required by spec:** wire `RichPermissionUI`
into the live turn. Phase 4 unblocks it (input is now prompt_toolkit-native
and `Live` is stopped during input, so an accept/deny panel can render
cleanly). Wire by setting `ctx.permission = RichPermissionUI(console)` in
`iter_turn` (or on the session) — the protocol at
[`workspace.py:108-111`](../src/cairn/execution/workspace.py) is already
`async def request`. This is a **separate decision** from the input work;
flag it to the user rather than bundling silently. The smoke note in
`permission_panel.py:8-13` calls this out explicitly.

### 2.4 Tests

- **NEW** `tests/unit/test_input.py` — completer composition (slash + skill +
  `@file` path list derived from a tmp workspace), Esc+Enter submit vs
  plain-Enter on a complete slash command, history file is created under
  `paths.history_dir()`, `BasicInput` returns exactly what `console.input`
  would. Drive prompt_toolkit with `prompt_input()` / a `DummyInput` to stay
  deterministic (no real TTY).
- **Extend** `tests/unit/test_interrupt.py` — assert `run_cancellable` still
  raises `TurnCancelled` under the chosen cancel path; add a `basic_input`
  case if the watcher gating changes.
- **Regression:** the `test_run_cancellable_*` tests
  ([`test_interrupt.py:12-46`](../tests/unit/test_interrupt.py)) must stay
  green unchanged under option (B).
- **Smoke:** manual `cairn repl` — type a slash prefix (completion visible),
  up-arrow history, Esc+Enter multiline submit, Esc mid-turn cancels.

### 2.5 Risks

- **prompt_toolkit + Rich `Live` terminal ownership.** Mitigated by the
  two-phase invariant (input only while `Live` is stopped) and option (B)
  above. If we ever adopt option (A) we must prove no frame is rendered while
  prompt_toolkit holds the TTY.
- **Async-ifying the REPL loop** (Step 4.4 option (a)) touches a load-bearing
  synchronous entry point. Mitigated by keeping `run_cancellable` semantics
  identical and reusing the existing `loop`.
- **Completion drift** between the completer and the real command set.
  Mitigated by Step 4.2 (single registry is the source of truth).

---

## 3. Phase 5 — collapse / shell / CLI stdout

### 3.1 Scope (from `backburner.md`)

`orchestration/progress.py` (+`on_tool_progress(tool_call_id, line)`);
`tool_adapter.py` (carry `tool_call_id`; push sherlock/holehe stdout through
it). Four sub-items: collapsible **thinking** + **tool-result** blocks;
**`!` / `!!`** shell passthrough; **`@file`** inlining; live CLI stdout into
ToolCards. `pyte` ANSI rendering is **out of scope** — plain `on_tool_progress`
suffices.

### 3.2 Current state (exists)

- **`ThinkingPart` events are already normalized** — `normalize()` maps
  `PartStartEvent(ThinkingPart)` → `ThinkingStart` at
  [`events.py:184-185`](../src/cairn/orchestration/events.py) and
  `ThinkingPartDelta` → `ThinkingDelta` at
  [`events.py:194-195`](../src/cairn/orchestration/events.py) (handles the
  `content_delta is None` case, line 195). `ThinkingEnd` mapped at lines
  205-207. **But `_apply_event` does not render them** — see the explicit
  "thinking (``Thinking*``) is deferred to later phases" comment at
  [`live_turn.py:203`](../src/cairn/interfaces/tui/live_turn.py). Same for
  `ToolArgsDelta` (the model composing JSON args live).
- **Progress hook surface** — `Progress` at
  [`progress.py:31-54`](../src/cairn/orchestration/progress.py) has
  `on_turn_start`, `on_tool_start(tool_call_id)`, `on_tool_end(tool_call_id)`,
  `on_turn_end`. `NullProgress` is the safe default (line 57). All hooks are
  synchronous (docstring lines 22-24).
- **`tool_call_id` is already captured** in the closure at
  [`tool_adapter.py:72`](../src/cairn/orchestration/tool_adapter.py)
  (`rctx.tool_call_id or ""`) and passed to `on_tool_start`/`on_tool_end`
  (lines 80, 123). The closure holds both `progress` and `tool_call_id` in
  scope around `plugin.run(...)` (line 83) — the natural place to bind them
  for the new hook.
- **Sherlock/holehe already try to report sub-progress — via dead code.**
  Both reach into a private attribute:
  `status = getattr(progress, "_status", None)` then `status.update(...)`
  at [`sherlock.py:91-97`](../src/cairn/plugins/identity/sherlock.py) and
  [`holehe.py:58-64`](../src/cairn/plugins/identity/holehe.py). **No
  `Progress` subclass sets `_status`** (grep-confirmed across
  `orchestration/` and `interfaces/`) — the field is a leftover from the
  removed `RichProgress`/`HeadlessProgress` classes (Phase 1 cleanup). Today
  these calls are silently skipped behind `if status is not None`. This is
  the precise thing `on_tool_progress` replaces.
- **Subprocess output is buffered, not streamed.** `_exec` at
  [`subprocess_util.py:42-76`](../src/cairn/execution/subprocess_util.py)
  uses `await asyncio.wait_for(proc.communicate(), timeout=timeout)` (line
  66), which returns the full stdout/stderr only on completion. There is no
  per-line tap today.
- **`run_cli_tool` already threads `progress`** down to install/run
  ([`cli_tools.py:391-429`](../src/cairn/execution/cli_tools.py)) via the
  `_progress_start`/`_progress_end` helpers (lines 267-288), which use a
  synthetic `tool_call_id="install_cli"` (line 274). The same plumbing can
  carry an `on_line` callback.
- **Cards today are one-line status lines.** `ToolCard.render` at
  [`cards.py:86-108`](../src/cairn/interfaces/tui/cards.py) renders
  pending/running/done states with a single excerpt line. No body region
  exists yet for streamed stdout or a collapsible result.
- **`!`/`!!`/`@file` do not exist.** Input dispatch
  ([`repl.py:257-300`](../src/cairn/interfaces/repl.py)) has no shell or
  inline handling. The `@file` *completer* is Phase 4; the *inlining* (path →
  contents into the prompt) is Phase 5.
- **Workspace boundary primitives exist** and are the right gate for `@file`
  inlining and `!`/`!!` cwd: `workspace_roots(ctx)`, `resolve_in_workspace`,
  `authorize` at [`workspace.py:33-144`](../src/cairn/execution/workspace.py);
  `scrub_env` at [`workspace.py:173-191`](../src/cairn/execution/workspace.py).

### 3.3 Changes (new + edits, sequenced to minimize collision)

**Step 5.1 — EDIT `src/cairn/orchestration/progress.py`** (shared with
agentic smoke — land FIRST and additive-only; see §6).

- Add the hook to the base class:
  ```python
  def on_tool_progress(self, tool_call_id: str, line: str) -> None:
      """One stdout/stderr line from a running tool. Default no-op."""
  ```
  Pure addition; `NullProgress` inherits the no-op. `on_tool_progress` is
  **observer-only** (documented in the same prose style as the existing
  hooks). No existing caller breaks.

**Step 5.2 — EDIT `src/cairn/orchestration/tool_adapter.py`** (shared with
agentic smoke — additive, smoke-safe).

The plugin (sherlock/holehe) sees `ctx.progress`, **not** the closure's
`tool_call_id`. PydanticAI runs tools **concurrently** as separate asyncio
tasks ([`session.py:144-157`](../src/cairn/orchestration/session.py)), so
mutating a shared `ctx` attribute per-call is a race. Two viable designs:

- **(A) Preferred — `contextvars.ContextVar`.** Add
  `current_tool_call_id: ContextVar[str | None]` in `tool_adapter`. The
  closure sets it around `plugin.run(...)`:
  ```python
  token = current_tool_call_id.set(tool_call_id)
  try:
      out = await plugin.run(...)
  finally:
      current_tool_call_id.reset(token)
  ```
  Provide a helper `progress_for(ctx) -> Progress` (or a small
  `_BoundProgress`) that wraps `ctx.progress` and binds
  `current_tool_call_id.get()` into each `on_tool_progress(line)` call.
  Plugins that want to stream call `progress_for(ctx).on_tool_progress(line)`
  with no id argument. asyncio tasks inherit the contextvar copy at creation
  → safe under parallel execution.
- **(B) Pass an `on_line` callable into `plugin.run` via `ctx`.** More
  invasive (signature/contract churn); rejected.

  Under (A), the `on_tool_start`/`on_tool_end` calls at
  [`tool_adapter.py:80,123`](../src/cairn/orchestration/tool_adapter.py)
  stay exactly as they are — only the contextvar set/reset is new around
  line 83.

**Step 5.3 — EDIT `src/cairn/execution/subprocess_util.py` + `cli_tools.py`**
(shared with smoke — additive).

- Add a line-streaming variant to `subprocess_util`:
  ```python
  async def _exec_stream(args, *, timeout, env, cwd, on_line) -> tuple[bytes, bytes, int | None]:
  ```
  Reads `proc.stdout` line-by-line (`async for line in proc.stdout:`),
  calls `on_line(line)` per line, and accumulates the bytes so the existing
  `CommandResult`/`(stdout, stderr)` contracts are unchanged. `run_shell`
  and `run_subprocess` get an optional `on_line=None`; when `None` they use
  the existing `communicate()` path (zero behavior change for every caller
  that doesn't opt in). Timeout/kill discipline stays in one place.
- In `cli_tools.run_cli_tool`
  ([`cli_tools.py:391-429`](../src/cairn/execution/cli_tools.py)) accept an
  optional `on_line` and forward it to `run_subprocess`.

**Step 5.4 — EDIT `src/cairn/plugins/identity/sherlock.py` + `holehe.py`**
(shared with smoke — additive; also deletes dead code).

- Replace the dead `getattr(progress, "_status", None)` block
  ([`sherlock.py:91-97`](../src/cairn/plugins/identity/sherlock.py),
  [`holehe.py:58-64`](../src/cairn/plugins/identity/holehe.py)) with a call
  to the new hook via the Phase-5.2 helper:
  ```python
  from cairn.orchestration.tool_adapter import progress_for
  p = progress_for(ctx)
  await run_cli_tool("sherlock", [...], on_line=lambda ln: p.on_tool_progress(ln))
  ```
  Delete the `_status.update(...)` branches entirely.
- Note: the existing `overall_timeout` / `--print-found` flags stay; only the
  status-reporting path changes.

**Step 5.5 — EDIT `src/cairn/interfaces/tui/live_turn.py` + `cards.py` +
new `markdown_stream.py` sibling** (TUI-only; no shared-file overlap with
smoke).

- **Thinking rendering.** Extend `_apply_event` at
  [`live_turn.py:199-212`](../src/cairn/interfaces/tui/live_turn.py) to
  handle `ThinkingStart`/`ThinkingDelta`/`ThinkingEnd` by feeding a new
  `ThinkingStream` (mirror of `MarkdownStream`
  [`markdown_stream.py:57-125`](../src/cairn/interfaces/tui/markdown_stream.py))
  rendered **collapsed** by default (a `Panel` titled `thinking ▸` with a
  click/expand affordance — pure Rich, no Textual). Drop the "deferred"
  comment at line 203.
- **`on_tool_progress` → card.** Extend `_ToolRecorder` at
  [`live_turn.py:134-157`](../src/cairn/interfaces/tui/live_turn.py) with:
  ```python
  def on_tool_progress(self, tool_call_id, line):
      self._composer.tool_progress(tool_call_id, line)
      self._live.update(self._composer.render())
  ```
  and add `_Composer.tool_progress(...)` which appends the line to the
  matching `ToolCard`'s body region.
- **Collapsible tool-result blocks.** Add a `body` region to `ToolCard`
  ([`cards.py:39-108`](../src/cairn/interfaces/tui/cards.py)) that, when the
  card is `done`, shows the excerpt (today's behavior) and an optional
  expandable tail of captured stdout lines. Phase 5 ships collapsed-by-
  default with a key to expand (or a `--verbose` repl flag); full
  expand-on-key waits for Phase 4's key bindings.

**Step 5.6 — EDIT `src/cairn/interfaces/repl.py`** (shared with Phase 4 and
Phase 6 — sequence after Phase 4; see §6).

- **`!`/`!!` shell passthrough.** In the dispatch chain (after Phase 4's
  `CommandRegistry` extraction), detect lines starting with `!` (capture and
  print) vs `!!` (capture and **inject the output into the next prompt as
  context**). Run via `run_shell` ([`subprocess_util.py:102-121`](../src/cairn/execution/subprocess_util.py))
  with `cwd = workspace_roots(ctx)[0]` and `env = scrub_env(os.environ)`
  (same hygiene as `run_command`). The output is the **user's own command
  result** — show it directly to the terminal (not wrapped as
  `<untrusted_external_data>`); if `!!` injects it into the prompt, it
  becomes user-authored input (same trust level as if the user pasted it).
- **`@file` inlining.** Before dispatching a prompt to `_run_turn`, scan for
  `@<path>` tokens; for each, resolve via `resolve_in_workspace(path,
  workspace_roots(ctx))` ([`workspace.py:47-66`](../src/cairn/execution/workspace.py))
  and inline the file's text at that position, capped (reuse
  `read_file`'s `_MAX_BYTES = 200_000` constant at
  [`read_file.py:30`](../src/cairn/plugins/agentic/read_file.py)). Tokens
  that resolve **outside** the workspace are left literal and flagged to the
  user (the workspace boundary is the trust surface). See §5 agentic-
  interaction notes.

### 3.4 Tests

- **NEW** `tests/unit/test_progress.py` addition — a `_Recorder` subclass
  captures `on_tool_progress(tool_call_id, line)`; assert the default
  `NullProgress` accepts it without error (mirror of
  `test_null_progress_is_safe_to_call` at
  [`test_progress.py:100-106`](../tests/unit/test_progress.py)).
- **NEW** `tests/unit/test_tool_adapter_contextvar.py` — drive two plugins
  concurrently via `TestModel(call_tools=[a, b])`; assert each plugin's
  `on_tool_progress` lines land on the **correct** `tool_call_id` even when
  the tools interleave (extends the parallel-correlation property proven by
  `test_tool_call_id_matches_between_stream_and_closure` at
  [`test_tui_events.py:304-343`](../tests/unit/test_tui_events.py)).
- **NEW** `tests/unit/test_subprocess_stream.py` — `_exec_stream` calls
  `on_line` per line, still returns the full `(stdout, stderr, rc)`, and
  respects timeout (kill path).
- **Extend** `tests/plugins/test_agentic.py` — assert `run_command`/CLI-tool
  output is unchanged when `on_line=None` (regression guard for the
  buffered path every existing test relies on).
- **NEW** `tests/unit/test_repl_shell_inline.py` — `!echo hi` prints to the
  terminal; `!!echo hi` injects `hi` into the next prompt; `@<file>` inlines
  in-workspace files and leaves out-of-workspace tokens literal.
- **Extend** `tests/unit/test_tui_events.py` — feed a synthetic
  `ThinkingDelta` stream and assert the collapsed panel renders and the
  sealed frame contains the thinking text.

### 3.5 Risks

- **`tool_call_id` correctness under parallel execution.** The whole point
  of the contextvar design (Step 5.2 (A)) is to preserve the property
  `test_tool_call_id_matches_between_stream_and_closure` already proves for
  start/end. The new test (§3.4) is the regression guard.
- **`on_tool_progress` spam.** sherlock/holehe can emit hundreds of lines.
  Cap the per-card retained tail (mirror `MarkdownStream.MAX_STREAM_CHARS`
  at [`markdown_stream.py:36`](../src/cairn/interfaces/tui/markdown_stream.py))
  so the Live frame stays bounded.
- **`!`/`!!` is a USER op, not a model op.** Its output is not wrapped. We
  must keep it distinct from the model's `run_command` (which IS wrapped by
  the closure). Doc both clearly; the `!`/`!!` path never enters
  `tool_adapter`'s closure.
- **Smoke overlap.** sherlock/holehe/run_command are exactly what the
  agentic smoke exercises. The Phase-5 edits to those files are additive
  (new `on_line` plumbing, dead-code removal) and must re-run the smoke
  after landing.

---

## 4. Phase 6 — themes / sessions

### 4.1 Scope (from `backburner.md`)

New `interfaces/tui/theme.py` (~12 Rich `Style` tokens centralizing today's
scattered `[cyan]` / `[dim]` literals); **`/compact`** command; **session
resume/fork** as JSONL under `~/.cairn/sessions/` (linear v1, no branching
graph). Textual `--tui` alt-screen mode is **out of scope**.

### 4.2 Current state (exists)

- **Scattered style literals** — confirmed across:
  - [`repl.py:45-52`](../src/cairn/interfaces/repl.py) (banner: `bold cyan`,
    `dim`, `cyan` border)
  - [`repl.py:251`](../src/cairn/interfaces/repl.py) (prompt: `bold cyan`)
  - [`cards.py:90-107`](../src/cairn/interfaces/tui/cards.py) (`cyan`, `dim`,
    `green`/`red` marks, `bold cyan`)
  - [`statusline.py:52-76`](../src/cairn/interfaces/tui/statusline.py)
    (`bold cyan`, `dim`, `magenta`, `cyan`)
  - [`permission_panel.py:32-41`](../src/cairn/interfaces/tui/permission_panel.py)
    (`bold yellow`, `yellow`, `cyan`, `dim`)
  - [`live_turn.py:121`](../src/cairn/interfaces/tui/live_turn.py) (`dim` for
    "thinking…")
- **History is an in-memory `list[Any]`.** `session.history` at
  [`session.py:79`](../src/cairn/orchestration/session.py), assigned from
  `run_result.all_messages()` at [`session.py:177`](../src/cairn/orchestration/session.py).
  PydanticAI messages are pydantic models → serializable via the
  `ModelMessagesTypeAdapter` (PydanticAI 2.18 standard) or `.model_dump()`.
  No JSONL exists today.
- **Session lifecycle.** `Session.__init__` at
  [`session.py:39-83`](../src/cairn/orchestration/session.py) builds agent +
  registers tools; `aclose` at line 200. `iter_turn` is the only mutator of
  `history` (line 177) and `last_output` (line 178).
- **Config/data dir.** `paths.config_dir()` at
  [`paths.py:17-22`](../src/cairn/core/paths.py) = `~/.cairn` (or
  `CAIRN_CONFIG_DIR`). Sessions subdir = `config_dir() / "sessions"` (none
  of the existing `paths.py` helpers cover it — add one).
- **`/reset` already clears history** ([`repl.py:286-289`](../src/cairn/interfaces/repl.py))
  — the closest existing command. `/compact` is its semantic opposite
  (preserve-but-condense).

### 4.3 Changes (new + edits, sequenced to minimize collision)

**Step 6.1 — NEW `src/cairn/interfaces/tui/theme.py`** (no collision).

- A frozen `Theme` dataclass with ~12 `rich.style.Style` tokens covering the
  literals enumerated in §4.2:
  `accent` (cyan), `muted` (dim), `ok` (green), `err` (red), `warn` (yellow),
  `paid` (magenta), `bold_accent` (bold cyan), `border`, `prompt`,
  `thinking`, `tool_name`, `tool_target`.
- A module-level `theme` singleton + a `set_theme(name)` for a future
  light/dark toggle (out of scope to ship more than one). Provide small
  helpers that return Rich `Text`/`str` so callers don't construct `Style`
  inline.

**Step 6.2 — EDIT the five style-literal sites** (mechanical, low risk;
no logic change).

- Replace each `[cyan]`/`[dim]`/etc. literal with the corresponding token
  from `theme`. Sequenced so each file is touched once:
  [`cards.py`](../src/cairn/interfaces/tui/cards.py),
  [`statusline.py`](../src/cairn/interfaces/tui/statusline.py),
  [`permission_panel.py`](../src/cairn/interfaces/tui/permission_panel.py),
  [`live_turn.py`](../src/cairn/interfaces/tui/live_turn.py), then
  [`repl.py`](../src/cairn/interfaces/repl.py) banner/prompt (the repl.py
  edit is the only Phase-6 overlap with Phase 4/5; see §6).

**Step 6.3 — NEW `src/cairn/interfaces/tui/sessions.py`** (no collision).

- JSONL session store under `paths.config_dir() / "sessions"` (add a
  `paths.sessions_dir()` helper next to
  [`paths.py:34-35`](../src/cairn/core/paths.py)).
- One file per session: `<session_id>.jsonl` where each line is a serialized
  message. Use PydanticAI's `ModelMessagesTypeAdapter` (2.18) for
  dump/load — the standard, bump-safe path. Linear v1: a session has exactly
  one parent (or none); no graph.
- API: `save_turn(session_id, messages)`, `load(session_id) -> list[ModelMessage]`,
  `list_sessions() -> Iterable[SessionMeta]`, `fork(session_id) -> new_id`
  (copies the file to a new id).

**Step 6.4 — EDIT `src/cairn/orchestration/session.py`** (TUI/orchestration-
only; not shared with smoke).

- Add `session_id: str` (uuid4 hex, or a timestamp slug) on `Session`.
- After each successful `iter_turn` (around
  [`session.py:176-179`](../src/cairn/orchestration/session.py)), append the
  new messages to `<session_id>.jsonl`. Wrap in a try/except so a disk error
  never crashes the turn (the on-disk log is a convenience, not a guarantee).
- Add `Session.resume(session_id)` / `Session.fork(session_id)` classmethods
  (or module helpers in `sessions.py`) that construct a `Session` and preload
  `history` from the JSONL. Model/tool/agent construction is unchanged.

**Step 6.5 — EDIT `src/cairn/interfaces/repl.py`** (shared with Phase 4/5 —
sequence LAST).

- Register `/compact`, `/resume <id>`, `/fork`, `/sessions` on the
  `CommandRegistry` from Phase-4 Step 4.2.
  - `/compact` — invoke a single model call to summarize
    `session.history` into a compacted running context, then replace
    `history` with `[system, summary]`. v1 fallback if the model is
    unreachable: keep the last N messages (configurable).
  - `/resume <id>` — `session.resume(id)`; print a one-line confirmation.
  - `/fork` — `session.fork(session.session_id)`; subsequent turns write to
    the new id.
  - `/sessions` — list on-disk sessions (`sessions.list_sessions()`).

### 4.4 Tests

- **NEW** `tests/unit/test_theme.py` — every token resolves to a valid Rich
  `Style`; snapshot the token set (12ish) so drift is caught.
- **NEW** `tests/unit/test_sessions.py` — round-trip a fake `history`
  (`TextPart`/`ToolReturnPart`) through JSONL and assert the reloaded
  messages are equal; `fork` produces a new id with byte-identical content;
  `list_sessions` ordering; malformed-line tolerance (skip + warn).
- **Extend** `tests/unit/test_tui_events.py` — assert render output is
  unchanged after the theme-token swap (snapshot the sealed frame for the
  existing `test_run_turn_streams_tools_and_seals_markdown` at
  [`test_tui_events.py:267-286`](../tests/unit/test_tui_events.py)).
- **NEW** `tests/unit/test_compact.py` — `/compact` with a `TestModel`
  produces a summary and trims `session.history`.

### 4.5 Risks

- **PydanticAI message serialization across versions.** Mitigated by using
  `ModelMessagesTypeAdapter` (PydanticAI's own bump-safe API) rather than
  hand-rolled dicts. Add a version field to the JSONL header so a future
  schema change can migrate.
- **`/compact` hallucination risk.** A model-generated summary can drop
  evidence. Mitigation: keep the full pre-compact history on disk (the
  JSONL is append-only) and surface a "compacted from N turns" marker; the
  user can `/resume` the pre-compact session id.
- **Theme token drift** between code and docs. Mitigated by the snapshot
  test (§4.4).

---

## 5. Interactions with the in-progress agentic file-control work

The agentic track (`docs/architecture/agentic-file-control.md`) has Phases
1–4 shipped and Phase 5 smoke **partial** (`read_file` verified on grok-4.5;
`run_command`/`scrub_env`/Esc-cancel pending). The interactions to flag:

1. **`!`/`!!` vs `run_command` (Layer distinction).** `run_command`
   ([`run_command.py`](../src/cairn/plugins/agentic/run_command.py)) is a
   **model** tool — its result is wrapped in `<untrusted_external_data>` by
   the closure at [`tool_adapter.py:124`](../src/cairn/orchestration/tool_adapter.py).
   `!`/`!!` is a **user** REPL affordance — its output goes straight to the
   terminal (or into the next prompt as user input). They share **cwd
   hygiene** (both run in `workspace_roots(ctx)[0]`) and **env scrubbing**
   (`scrub_env`), but the `!` path **must not** enter `tool_adapter`'s
   closure (it would otherwise gain spurious wrapping and audit rows).
   Implementation: keep `!`/`!!` dispatch in `repl.py` above the
   `_run_turn` call, never routing through the agent.
2. **`@file` vs `read_file` (trust boundary).** `read_file`
   ([`read_file.py`](../src/cairn/plugins/agentic/read_file.py)) is the
   model's tool — its output is wrapped (anti-injection). `@file` is the
   **user** inlining a file into their own prompt — that text is trusted
   (same trust level as typing it). The workspace boundary still applies as
   a convenience guard: in-workspace paths inline silently; out-of-workspace
   `@file` tokens are left literal with a warning (the user can always paste
   the contents explicitly). Do **not** wrap `@file` contents — wrapping
   user input would break the model's interpretation of the user's message.
3. **`download_url` / `run_command` boundary unchanged.** Neither Phase 4–6
   changes the `authorize()` gate ([`workspace.py:123-144`](../src/cairn/execution/workspace.py))
   or the two-layer model. Phase 4's opportunistic wiring of
   `RichPermissionUI` (Step 4.5) is the one place Layer A changes behavior
   (out-of-workspace ops become *promptable* instead of auto-denied) —
   surface it explicitly to the user; default v1 stays `NullPermissionUI`
   unless they opt in.
4. **Phase 5 stdout hook rides the agentic closure.** `on_tool_progress`
   threads through the same `_tool` closure the agentic smoke is validating.
   Landing it before the smoke is **safe** (additive, default no-op) but the
   real-model confirmation of per-card stdout streaming should happen on
   the same challenge-mode smoke that validates the closure.

---

## 6. Build order (collision-minimized, smoke-aware)

Three streams; the only hard ordering is "Phase 4 before Phase 5's `!`/`@file`
REPL pieces" (both edit the REPL input path) and "sequence repl.py edits
strictly."

```
Stream A (independent of the agentic smoke — can start now):
  A1. Phase 4 Step 4.2  — extract CommandRegistry (pure refactor)
  A2. Phase 4 Step 4.1  — new input.py + BasicInput
  A3. Phase 4 Step 4.3  — interrupt.py cancel path + --basic gate
  A4. Phase 4 Step 4.4  — repl.py swap (input + dispatch via registry)
       └─ after A4, RichPermissionUI wiring (Step 4.5) is unblocked (decide separately)

Stream B (independent of the smoke — pure TUI/orchestration additive):
  B1. Phase 6 Step 6.1  — new theme.py
  B2. Phase 6 Step 6.2  — swap style literals (cards/statusline/permission_panel/live_turn first;
                          repl.py banner LAST — after A4 to avoid dual edits)
  B3. Phase 6 Step 6.3  — new sessions.py + paths.sessions_dir()
  B4. Phase 6 Step 6.4  — session.py history serialize/save-on-turn
  B5. Phase 6 Step 6.5  — repl.py /compact /resume /fork /sessions (after A4)

Stream C (best after the agentic smoke confirms the closure; additive if before):
  C1. Phase 5 Step 5.1  — progress.py on_tool_progress hook (default no-op; smoke-safe)
  C2. Phase 5 Step 5.2  — tool_adapter contextvar binding (smoke-safe; additive)
  C3. Phase 5 Step 5.3  — subprocess_util._exec_stream + cli_tools on_line
  C4. Phase 5 Step 5.4  — sherlock/holehe push stdout + delete dead _status code
  C5. Phase 5 Step 5.5  — live_turn Thinking* + on_tool_progress → card (TUI-only)
  C6. Phase 5 Step 5.6  — repl.py ! / !! / @file inline (after A4)
```

**Independence from the agentic smoke:**

- **Fully independent (start now):** Streams A and B. The smoke runs
  `cairn search` (headless) against the agentic plugins; it does not touch
  the REPL input loop, theme, sessions, or thinking rendering.
- **Additive but on shared files (coordinate with smoke):** Stream C
  touches `progress.py`, `tool_adapter.py`, `cli_tools.py`,
  `subprocess_util.py`, `sherlock.py`, `holehe.py` — exactly the closure
  and CLI-tool path the smoke validates. C1 and C2 are pure additions
  (default no-op hook; observer-only contextvar) and can land before the
  smoke without changing any smoked behavior. C3–C5 change behavior and
  should re-run the smoke after landing.
- **Hard sequencing:** Phase 5.6 (`!`/`@file` in `repl.py`) and Phase 6.5
  (`/compact` etc. in `repl.py`) both depend on Phase 4's `CommandRegistry`
  (Step 4.2) and on the prompt_toolkit input (Step 4.4) being in place.
  Land Phase 4 first.

**Recommended first PR:** Stream A (A1–A4) — the input foundation. It
unblocks Phase 5.6 and Phase 6.5, is fully independent of the agentic smoke,
and ships user-visible value (history, completion, multiline) immediately.

---

## 7. Out-of-scope reminders (per `backburner.md`)

- `pyte` ANSI rendering — plain `on_tool_progress` suffices for Phase 5.
- Textual `--tui` alt-screen mode — explicitly deferred; the default REPL
  stays inline Rich `Live` + prompt_toolkit to preserve scrollback.
- Session branching graph — Phase 6 ships linear resume/fork only.
