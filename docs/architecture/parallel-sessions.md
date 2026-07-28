# Parallel sessions (issue #2)

> **Status:** backend foundation landed — a `SessionPool` runs N concurrent
> sessions on one asyncio loop with a shared audit log, per-session budgets,
> cancel-by-id, and on-demand graph merge. The **UI** layer (`/spawn`, laned
> view, `/sessions`) is **deferred until U6** (session store/ids) lands, because
> every one of those touches the REPL/TUI files another contributor is editing.
> This doc is the contract the deferred UI must implement against.
>
> **Issue:** [#2 — Multi-agent / parallel sessions](https://github.com/roowus/cairn/issues/2).
> The hard-stop is unchanged: concurrency here is throughput/orchestration only.

## What landed (v1)

- **`orchestration/session_pool.py`** — `SessionPool`: a `Semaphore`-gated pool
  of `Session`s with a FIFO spawn order, per-session `SessionBudget`
  (max-calls / max-spend), programmatic `cancel(session_id)` / `cancel_all()`,
  `merge_graphs()`, and `aclose()`.
- **Shared audit log.** Every pooled session opens its **own** sqlite3
  connection to the same `cairn.db` file; WAL + `PRAGMA busy_timeout=5000`
  (`storage/db.py`) serialize writes. Each audit row carries a `session_id`
  column (new migration `0003`, back-filled by `Database._ensure_columns`), set
  by the pool via `session.audit.session_id`.
- **`storage/graph_store.py`** — `NetworkXGraphStore.merge()` folds one session's
  graph into another, de-duping by the existing `"type:value"` node key (so an
  entity mined by two sessions collapses to one node, sources accumulated). A
  re-entrant guard makes mutation safe if a graph is ever shared at runtime.
- **`interfaces/interrupt.py`** — `cancel_async_task` / `cancel_tasks`: the
  programmatic cancel primitive (issue #2: "`tool_call_id` keying →
  `session_id`"), alongside the unchanged stdin-watcher `run_cancellable`.
- **`core/config.py`** — `max_concurrent_sessions` (default 4) and optional
  `session_max_spend` / `session_max_calls`.

## v1 design decisions (from the issue's open questions)

| Question | Decision | Why |
|---|---|---|
| Process vs asyncio | **asyncio, one loop** | Cheap; shared audit/registry; the issue says "v1 likely the former." No subprocess isolation in v1. |
| Resource ceiling | `Semaphore(max_concurrent)` + per-session `SessionBudget` | Reuses `UsageTracker` for the numbers; the **pool** enforces (tracker stays observer-only). |
| Shared state | **Shared audit *file*, per-session graphs merged on demand** | Separate connections avoid the "shared connection closed by one session" bug; per-session graphs have zero write contention; merge dedups. |
| Cancellation | `cancel_async_task` by session id | The REPL's stdin watcher stays for the foreground session; pooled/background sessions cancel by id. |
| UI | **Deferred** | `/spawn`, laned view, `/sessions` all route through `repl.py` + `tui/*` — another contributor's active zone (U3/U4/U6). |

### Why the pool enforces budgets (not the tracker)
`UsageTracker` is documented *observer-only — never influences execution*. A
hard spend/call ceiling *does* influence execution, so the ceiling lives in the
pool: `SessionPool._check_budget` reads a session's tracker *between turns* and
raises `BudgetExceeded` before the next turn runs. An in-flight turn always
completes. This preserves the accountant/hook invariants exactly.

## Build order (issue #2), with status

1. ✅ Cheaply instantiable N sessions + `SessionPool` with a concurrency cap.
   (Cheapness win: `discover()` runs **once** and the registry is shared across
   sessions via `Session(registry=shared)`.)
2. ⏳ `/spawn <task>` + `/sessions` — **deferred** (REPL, U6 zone).
3. ⏳ Laned UI (one ToolCard region per live session) — **deferred** (TUI, U3 zone).
4. ✅ Shared-graph merge + cross-session entity de-dup (`merge_graphs()`).

## The U6 seam (what the deferred UI must provide)

The pool deliberately tracks `session_id ↔ Session` **externally** (no edit to
`Session`), so it doesn't collide with U6's in-progress `session_id` +
session-store work. When U6 lands:

- `Session` will gain a `session_id`. The pool can then read it instead of
  assigning its own; until then `session.audit.session_id` is the tagging hook.
- The REPL `CommandRegistry` (extracted by U4) is where `/spawn` should
  register. **Naming coordination:** U6 already plans a `/sessions` command for
  listing on-disk JSONL sessions. To avoid a name clash, the parallel-session
  surface should use a different name when it lands — recommended `/pool` or
  `/agents` — leaving `/sessions` to the resume/fork list.

## What's explicitly deferred
- **`/spawn`, laned UI, `/sessions`** — wait for U6.
- **aiosqlite + a write queue** — `busy_timeout` + WAL handle v1 concurrency
  correctly; queue aiosqlite only if real contention is measured.
- **Subprocess-isolated workers** — v1 is one-process; isolation is a later
  trade-off (perf vs blast-radius of a misbehaving plugin).
