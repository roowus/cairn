# Backburner & Planned Ideas

> A **parking lot** for ideas not yet on the committed [roadmap](roadmap.md).
> Items graduate **backburner → here → roadmap.md** as they're picked up and
> ordered by leverage. Each entry carries its status and any decision blocking
> it. The standing constraints from [discoveries.md](discoveries.md) apply
> throughout: **free-first, hard-stop execution, avoid paid platforms, don't
> burn Cairn's own search credits on large-scale research (ask first).**

---

## Backburner (explicitly deferred — focus is elsewhere right now)

### 1. Native LLM web search — let the connected model search itself

**What.** If the configured provider can search the web natively, let the brain
use that instead of forcing every live lookup through the `web_search` plugin.

**Why it matters.** This kills the repo's biggest search pain point — *"web
search needs a Brave key to be reliable"* — because **GLM-5.2 and Grok, the two
providers actually in use, both search natively for free.** Provider-agnostic and
free-first.

**Provider matrix (from knowledge — verify pricing/TOS before building):**

| Provider | Native search? | Mechanism | Auditable in Cairn? |
|---|---|---|---|
| xAI Grok | ✅ "Live Search" | `search_parameters` (`mode`, `sources`, `return_citations`) | tool-form → yes; `mode:auto` → opaque |
| Z.AI GLM-5.2 | ✅ (standard endpoint) | `web_search` tool / `enable_search` | tool → yes; **verify on the coding endpoint** Cairn uses |
| OpenAI | ✅ | `web_search` tool (Responses) / `*-search-preview` | yes (annotations) |
| Anthropic | ✅ | `web_search_20250305` server tool | yes (content blocks) |
| Ollama / local | ❌ | — | n/a |

**Mechanism in Cairn.** PydanticAI 2.18 lets `model_settings` be a **callable**
invoked before each model request — the clean injection point for a per-request
`extra_body` (e.g. xAI `search_parameters`). Add a `native_search` flag to the
`reasoning/catalog.py` `ModelProfile`, and tell the brain in
`reasoning/system_prompt.py` that it has live search built in.

**⛔ Decision needed (touches the hard-stop / anti-hallucination property):**

- **Tool-form search** (Grok's `search` tool, Anthropic/OpenAI web-search tools)
  returns results *as tool messages* → PydanticAI surfaces them → we wrap in
  `<untrusted_external_data>` and audit them like any plugin. **Hard-stop
  preserved. → PREFERRED.**
- **xAI `mode:auto`** is *opaque* — the model reads content we never see, so a
  fabricated-between-source-and-summary finding is possible again. Citations are
  still returned (structured, auditable), but the *retrieved content* isn't. →
  only as an **explicit opt-in** with a visible *"model-searched — not
  independently audited"* marker on those turns.
- **"Just ask the model to cite sources in the prompt"** is good UX, but
  model-*written* citations are self-reported (hallucination risk). The
  trustworthy handle is the API's **structured `citations` field**
  (`return_citations: true`), which we can log independently of the prose.

**Status:** WAITING on the audit-policy decision (tool-form-only vs allow
auto-search with a marker) before building.

---

### 2. Free people / database sources (Whitepages-style lookups)

**What.** People / phone / address / public-records lookups to broaden the
identity pivot.

**Reality.** **There is no free, reliable Whitepages-equivalent API.**
Whitepages Pro, BeenVerified, Spokeo, PeopleDataLabs, etc. are all paid →
**excluded** by the avoid-paid-platforms directive. The free path is *composable*
open / freemium sources, not one database:

| Need | Free option | Notes |
|---|---|---|
| Phone | **libphonenumber** (offline, zero-dep) + Twilio Lookup free tier | libphonenumber: carrier/region/line-type, deterministic, **no network**. Twilio free: line type/carrier; caller-name is paid. |
| People ↔ companies | **OpenCorporates** (free API tier w/ key) | officers/directors linkage |
| Structured knowledge | **Wikidata** SPARQL (free, **no key**) | structured people/orgs/identifiers — strong pivot fuel |
| Email → identity | Hunter.io (free 25/mo w/ key), EmailRep (free) | freemium |
| Property / address (US) | county assessor sites; **OpenAddresses** (open bulk points) | per-county, no unified API; OpenAddresses has points, not owner names |
| Breaches | HIBP (already integrated) | DeHashed/LeakCheck are paid → excluded |
| Aggregator people-search | TruePeopleSearch, FastPeopleSearch, That'sThem, WebMii | free but anti-bot + ToS-gray → scraping fragile/ethically questionable; **not a default** |

**Strong candidates (on-policy, free-first):** `libphonenumber` (zero-dep
offline), `OpenCorporates` (free-tier-with-key), `Wikidata` (free, no key).

**Status:** WAITING on which directions to pursue. Verify free availability /
TOS with Grok's own search before building — **don't burn Cairn's search credits
on this research.**

---

## Planned / in-progress

### UI overhaul — "function like `pi`"  *(ACTIVE)*

The CLI UI is currently a scroll-and-print `input()` loop (answer appears all at
once in a `Panel`; `interfaces/tui/` is an empty stub despite Textual being a
declared dep). Goal: a live, `pi`-style terminal app — streaming assistant text,
in-place tool cards, persistent layout (messages + editor + statusline),
collapsible blocks, themes.

The defining engineering insight (verified against PydanticAI 2.18 and the
current code): switching `session.ask` from non-streaming `agent.run()` to
`agent.iter()` is **additive and safe** — tool execution still flows through the
existing audited `_tool` closure in `tool_adapter.py`, so the hard-stop, audit,
and usage accounting are untouched; the new stream only adds live text deltas
and tool-call intent.

**Architecture decision (approved):** Rich `Live(transient=False)` differential
repaint + `prompt_toolkit` input — **not** a Textual app (its alt-screen destroys
scrollback, contradicting the "feel like pi" requirement) and **not** a port of
pi-tui's custom renderer (~2000 lines for marginal gain). `textual` moved to an
optional `[tui]` extra; `prompt_toolkit>=3.0` added; `pydantic-ai` tightened to
`>=2.18,<3`. Full plan in the session plan file.

**Progress (Phase 1 — stream the answer):**
- ✅ `pyproject.toml` — pin `pydantic-ai>=2.18,<3`, add `prompt_toolkit`, move
  `textual` to `[tui]`.
- ✅ `orchestration/events.py` — the PydanticAI-isolation seam: `TurnEvent` union
  + `normalize()`. **Lives in orchestration, not `interfaces/tui`** (correction to
  the original plan): `session.iter_turn()` *produces* these events and the UI
  *consumes* them downward; an `interfaces` location would force an upward import.
  Verified: `normalize()` maps all 9 PydanticAI 2.18 event kinds correctly against
  real constructed events.
- ✅ `orchestration/session.py` — `iter_turn()` async generator drives `agent.iter()`
  → `node.stream()` → `normalize()`; `ask()` is now a thin wrapper that drains it and
  returns `last_output`. Verified end-to-end with `TestModel` (9 events: args → exec →
  text deltas → final; history + output correct). Hard-stop, audit, usage untouched.
- ✅ `interfaces/tui/markdown_stream.py` — throttled (≈30fps) streaming-Markdown
  accumulator: coalesces `TextDelta`, trims lone trailing fences (anti-flicker),
  caps the streaming tail, full-renders on `seal()`. Verified fence/throttle/dedupe/cap.
- ✅ `interfaces/tui/live_turn.py` — per-turn `Live(transient=False)` region: streams
  the Markdown + shows tool calls inline (target/excerpt from the audited closure),
  seals the final frame into scrollback. Non-TTY pipes get a clean single frame.
- ✅ Wiring — REPL `_run_turn` and `cairn search` (`headless.run_query`) both stream
  through `run_turn`; the old `console.status` + dump-`Panel` path and the
  `RichProgress`/`HeadlessProgress` classes are gone.
- ✅ `tests/unit/test_tui_events.py` — 11 tests: `normalize()` event mapping (the
  PydanticAI-churn canary), `markdown_stream` (throttle/fence/dedupe/cap/seal), and
  the wired `iter_turn`+`run_turn` path end-to-end via `TestModel`. Repo: 129 tests
  green, `ruff` clean.

**Phase 1 status: ✅ shipped — verified on a real model.** `cairn search "enrich
8.8.8.8"` streamed the answer live, showed 5 parallel tool calls animating, and
sealed into scrollback. (The smoke also surfaced that PydanticAI runs tools
**concurrently** by default — see Phase 2.)

**Progress (Phase 2 — tool cards keyed by `tool_call_id`): ✅ complete.**

The Phase-1 smoke revealed all 5 tool `▸` hooks firing before any `✓` — PydanticAI
executes tool calls **in parallel** (results land in completion order, not emission
order; a tool name can recur). The plan's "correlate by name + arrival order" is
unsafe under that, so the robust fix: thread the real per-call `tool_call_id` into
the audited closure and key cards on it. Confirmed safe (taking a `RunContext` first
param does **not** change return-value wrapping — `_tool_execution.py:564-585`).

- ✅ `tool_adapter.py` — `agent.tool_plain` → `agent.tool`; `_tool` takes
  `RunContext[None]`, reads `rctx.tool_call_id`, threads it into the Progress hooks.
  `_apply_signature` prepends an `rctx: RunContext[None]` param (PydanticAI excludes
  index-0 → **LLM JSON schema byte-identical**, empirically confirmed).
- ✅ `progress.py` — `on_tool_start`/`on_tool_end` gained a trailing `tool_call_id`.
- ✅ `cli_tools.py` — the duck-typed install-progress caller passes a synthetic id
  (else its `contextlib.suppress` silently drops the notification).
- ✅ `cards.py` (new) — `ToolCard` keyed by `tool_call_id`, fed from BOTH the stream
  (`ToolArgsStart`/`ToolExecStart`/`ToolExecEnd`) and the closure hooks
  (`on_tool_start` target, `on_tool_end` status+excerpt). Morphs `▸ pending →
  spinner running → ✓/✗ done`; transitions idempotent & order-insensitive.
- ✅ `live_turn.py` — composer holds an insertion-ordered `{tool_call_id: ToolCard}`;
  renders `Group(*cards, markdown)`. Retired the two-line `▸`/`✓` text.
- ✅ Tests — closure id == stream id (parallel-safe), interleaved card correlation,
  idempotent transitions, LLM-schema-excludes-`rctx` regression. Repo: 133 tests,
  `ruff` clean.

**Phase 2 review:** adversarially verified by a 4-agent workflow — hard-stop
invariant, closure/schema correctness, Progress-caller completeness, and general
regressions — **all PASS against the targets it was given**. Probes confirmed
`tool_call_id` is observer-only (audit_log columns inspected, no leak), the **LLM
JSON schema** is `rctx`-free, and the card state machine is monotonic. *Caveat
below — the review's target set had a gap the smoke then exposed.*

**Phase 2 hotfix (post-smoke — the review's blind spot):** the first real-model
smoke after the `agent.tool` switch **crashed `cairn` at startup**:
`RuntimeError: Type not yet supported: pydantic_ai._run_context.RunContext[NoneType]`.
Root cause: `_apply_signature` is shared between the agent-tool wrapper
(`tool_adapter._make_tool`) **and** the Typer plugin command
(`plugin_cli._make_cmd`); Phase 2 had it prepend `rctx: RunContext[None]`
unconditionally, so every `cairn plugin <name>` command gained an `rctx` first
param that Typer/Click can't build a parameter for. The review verified the
**LLM-facing** schema was `rctx`-free (correct) but never built the **Typer→Click
command tree**, so the CLI-side leak went unseen. **Lesson logged:** "schema
clean" must be checked for **both** consumers (model-facing tool schema *and*
Click command params), not just the model-facing one — the two share one helper.

- ✅ Fix — separated the concerns: `_apply_signature` mirrors **only** the
  input-model fields (shared, restored to pre-Phase-2 behavior); a new
  `_prepend_runctx` injects the `RunContext` param on the **agent-tool wrapper
  only**. `plugin_cli` is untouched (its call site already used the shared helper).
- ✅ Regression guard — `test_plugin_cli_builds_click_command_group` builds the
  real Click command tree via `typer.main.get_command` (the precise crash path);
  `test_apply_signature_does_not_leak_runcontext` asserts the shared helper stays
  `rctx`-free. Repo: **135 tests**, `ruff` clean.
- ✅ Re-smoked — `cairn search "enrich 8.8.8.8"` now starts, streams, and renders
  **three distinct tool cards** (`shodan_internetdb` / `ripestat` / `urlscan`),
  confirming the provider (Grok) populates `tool_call_id` and per-id card
  correlation holds on a real model — the property the unit tests could only
  assert against `TestModel`.

**Progress (Phase 3 — persistent statusline): ✅ complete.**

A compact one-line statusline rides as the last row of the ``Live`` frame and is
sealed with it (so it persists in scrollback like ``pi``'s bottom bar): live
**model**, cumulative **LLM tokens** (↑in ↓out), cumulative **tool calls**, and
**paid-source spend** — plus the REPL-only ``/help · Esc stop`` hints.

The genuinely new capability is **LLM token accounting**: Cairn never surfaced
model token cost before. ``session.iter_turn`` now merges each run's ``RunUsage``
(PydanticAI ``run.usage``) into ``session.llm_usage`` — an **observer-only**
accumulator (never written to audit/usage, never influences execution; left
untouched on cancel, consistent with history).

- ✅ `tui/statusline.py` (new) — `render_statusline(session, *, hints=False)`,
  pure-presentation `Text`. Compact number formatting (``1.2k`` / ``1.5M``);
  hides the token segment until a turn completes (no misleading ``↑0 ↓0``).
- ✅ `session.py` — `self.llm_usage = RunUsage()`; merged per turn inside
  `iter_turn` after the run completes, before the context closes.
- ✅ `live_turn.py` — the composer holds the session and renders the statusline
  as the last row of both the live and sealed frames;
  `run_turn(..., show_status=True, status_hints=False)`.
- ✅ Wiring — the REPL passes `show_status=True, status_hints=True`, and the
  sealed statusline **replaces** the old per-turn plugin-cost delta line (cards
  show per-call status; `/usage` shows detail). Headless passes `show_status=False`
  (it keeps `render_usage`; on a non-TTY pipe Rich `Live` writes the final frame
  with no trailing newline, so a statusline would run into the usage line and
  duplicate its counts — confirmed via a `force_terminal` probe; on a real TTY
  the cursor lands on a fresh line, so the REPL prompt stays clean).
- ✅ Tests — `test_statusline.py` (8): number formatting incl. the ``999_999 →
  1.0M`` boundary (the ``k`` band promotes before it would round to ``1000.0k``),
  model + hints, headless hint-suppression, token show/hide, tool count + paid
  spend, pluralization; plus an end-to-end merge test in `test_tui_events.py`
  (a real turn folds ``RunUsage`` into `llm_usage`; a second turn accumulates).
  Repo: **143 tests**, `ruff` clean.
- ✅ Smoked — `cairn repl` (piped) renders
  `grok-4.5 · ↑11.6k ↓579 tok · 7 tools · /help · Esc stop`, confirming Grok
  reports token usage and the accumulator works end-to-end on a real model.

**Phase 3 review:** adversarially verified by a 4-agent workflow — the
observer/hard-stop invariant for `llm_usage` (8 probes, all `clean`: it never
reaches `tool_adapter`, the `audit_log`, or `wrap_untrusted`; the statusline
carries no payload), LLM-usage accumulation correctness (no double-count,
cancel-safe), integration/caller completeness, and renderer robustness — **all
PASS, zero blocker/major findings**. Minor nits it surfaced and we fixed:
`_compact(999_999)` overflow, explicit `show_status` in the REPL, a guardrail
doc-note that `llm_usage` is raw-token-only (never derive `$/cost` —
`RunUsage.__add__` is not pricing-safe) and that a cancelled turn under-counts,
and the end-to-end token-merge test. (One unfixed nit, accepted: the paid-spend
unit label uses the busiest paid source's unit when several paid sources have
*different* units — rare under the free-first policy, numeric total correct.)

**Status:** Phases 1–3 shipped & verified on a real model. **Phases 4–6 are
parked** (see *Deferred — UI overhaul Phases 4–6* below) — the active track
pivoted to [agentic file & tool control](architecture/agentic-file-control.md)
(solving OSINT challenges). The UI phases resume when that lands.

### Deferred — UI overhaul Phases 4–6

Phases 1–3 of the streaming-UI overhaul shipped (stream the answer, tool cards
keyed by `tool_call_id`, persistent statusline — see above). The remainder is
parked while agentic file/tool control takes priority. Captured here verbatim so
nothing is lost:

- **Phase 4 — prompt_toolkit input.** New `interfaces/tui/input.py`; simplify
  `interfaces/interrupt.py`; `pyproject.toml` (+`prompt_toolkit>=3.0`).
  `prompt_toolkit.PromptSession`: command **history**; **multiline** (Esc+Enter
  submit); `CombinedCompleter` for slash commands + skill names + **`@file`**;
  **Esc → `task.cancel()`** (delete the cbreak watcher thread; keep it as a
  `--basic` / `CAIRN_BASIC_INPUT=1` fallback). **Invariant:** never run `Live`
  and prompt_toolkit input concurrently — read input with `Live` stopped.
- **Phase 5 — collapse / shell / CLI stdout.** `orchestration/progress.py`
  (+`on_tool_progress(tool_call_id, line)`); `tool_adapter.py` (carry
  `tool_call_id`; push sherlock/holehe stdout through it). Four sub-items:
  collapsible **thinking** + **tool-result** blocks; **`!` / `!!`** shell
  passthrough; **`@file`** inlining; live CLI stdout into ToolCards. `pyte`
  ANSI rendering is **out of scope** — plain `on_tool_progress` suffices.
- **Phase 6 — themes / sessions.** New `interfaces/tui/theme.py` (~12 Rich
  `Style` tokens centralizing today's scattered `[cyan]` / `[dim]` literals);
  **`/compact`** command; **session resume/fork** as JSONL under
  `~/.cairn/sessions/` (linear v1, no branching graph). Textual `--tui`
  alt-screen mode is **out of scope**.

---

> **Committed, leverage-ordered work lives in [roadmap.md](roadmap.md).** This
> file is the staging area below it.
