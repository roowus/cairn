# Backburner & Planned Ideas

> A **parking lot** for ideas not yet on the committed [roadmap](roadmap.md).
> Items graduate **backburner → here → roadmap.md** as they're picked up and
> ordered by leverage. Each entry carries its status and any decision blocking
> it. The standing constraints from [discoveries.md](discoveries.md) apply
> throughout: **free-first, hard-stop execution, avoid paid platforms, don't
> burn Cairn's own search credits on large-scale research (ask first).**

---

## Strategic differentiation — beyond "Claude Code + OSINT MCPs" (the moat)

> **Priority: HIGH — this is the thesis that decides whether Cairn is a product
> or a thin wrapper.** Captured 2026-07-28 from a strategic review. Likely
> graduates to `roadmap.md` (or its own design doc) once picked up; recorded here
> per request. The four pillars below are *where the moat has to live*: not in
> the tool inventory (tools are substitutable — any OSINT MCP can serve the same
> lookups), but in the **investigation substrate** the agent runs on.

### The problem (why this matters now)

At the architecture level Cairn is "agentic LLM loop + tool plugins + skills" —
structurally identical to *Claude Code + a set of OSINT MCP servers + skills*. As
OSINT MCPs proliferate, that substrate becomes a **commodity, not a moat**: anyone
can point a coding agent at Shodan / crtsh / whois MCP tools and get "a chat that
can do OSINT." So the question isn't *"what tools does Cairn have"* but ***"what
does Cairn do that a coding agent + MCPs structurally cannot?"***

What's somewhat unique *today* (real, but not enough):

1. **The anti-injection hard-stop as the defining property.** Cairn ingests
   attacker-controlled text for a living (scraped pages, breach dumps, doc
   metadata, challenge files, pastes). Every tool result is wrapped in
   `<untrusted_external_data>`, subprocesses use array args (no `shell=True`),
   secrets are scrubbed before exec. A coding agent's threat model is "mostly the
   user's own repo" — it doesn't need this. **Real, but it's a *safety feature*,
   not an OSINT capability.**
2. **The entity/pivot mental model (partial).** Cairn mines typed entities
   (handle / email / domain / IP / IOC) from outputs, keeps a NetworkX graph +
   SQLite `audit_log`, and the system prompt drives a pivot loop
   (handle → email → breach → domain). The unit of work is an *entity and a
   pivot*, not a file or function. **But pivoting is currently LLM-governed and
   loose, not a real engine** (roadmap #3, unbuilt).
3. **Free-first as a design axis + a small playbook library.** Values + a
   head-start, not a defensible mechanism.

So today: a sharper security model and the *germ* of an investigation model. The
four pillars turn the germ into the product.

### Pillar 1 — Provenance-backed entity-graph pivot engine (THE #1 priority)

**What.** The deterministic BFS pivot engine (roadmap #3), built *on* a
provenance-bearing entity graph. A graph where each tool output spawns typed
entities, pivots are edges, and breadth + cost are bounded (`max_depth`,
`max-entities-per-step`, `max-tool-calls`). The LLM keeps strategic control
(which pivots are worth it); breadth and cost become deterministic + reproducible.

**Why it's a moat.** Claude Code has no concept of *"an investigation"* as a
first-class object: resumable, reproducible, cost-bounded, replayable. A coding
agent's "context" is a flat transcript; Cairn's would be a **queryable graph of
evidence**. This is the single thing that turns Cairn from "a chat that can do
OSINT" into "a tool that *thinks in investigations*."

**Design.**
- `orchestration/pivot.py` — the BFS engine: a worklist of `(entity, pivot_kind)`
  frontier, expanded one step at a time; each expansion = one bounded tool call
  that yields new entities → new edges. Budgets enforced **here, not in the
  prompt.**
- The entity graph (NetworkX in `orchestration/`) is promoted from a side-effect
  of mining into the **canonical state object** of a turn/case.
- The brain (`reasoning/system_prompt.py`) stays in charge of *strategy* (pivot
  selection, when to stop); the engine enforces *breadth + cost*. Flag-gated
  (`Settings.pivot_engine`), so the loose LLM-governed mode stays available.

**Build steps.** (1) `Pivot` / `Frontier` / budget types; (2) wire the engine into
`session.iter_turn()` behind a flag; (3) make mined entities feed the frontier,
not just the graph; (4) tests for depth/cost bounds + replay determinism.

**Status:** design (roadmap #3). **Promote to active once the challenge-mode smoke
lands.** Seed: the existing entity graph + `audit_log`.

### Pillar 2 — Provenance / chain-of-custody as a first-class data model

**What.** In OSINT, *where a fact came from and when* matters as much as the fact
(credibility, admissibility, reproducibility). Every entity/claim carries
immutable provenance: source URL, capture timestamp, raw-bytes hash, producing
tool, and an archive (Wayback / archive.today) snapshot ref. Think **evidence
locker**, not chat history.

**Why it's a moat.** A coding agent treats tool outputs as ephemeral context. An
investigator treats them as **evidence** — citable, hashable, frozen in time,
reconstructible into "here's exactly how we reached this conclusion, with
snapshots." Claude Code + MCP has no reason to build this; for OSINT it's the
difference between a lead and a finding.

**Design.**
- Extend the entity model: each `Entity`/claim gains a `Provenance` record
  (`source_url`, `captured_at`, `raw_sha256`, `tool`, `archive_ref`, `prior_ids`
  on edit). Immutable; append-only on change.
- Promote the `audit_log` (already per-call: `elapsed_ms` + `usage_json`) from an
  accountant log into a **provenance graph**: the audit row is the *event*, the
  entity is the *claim*, the edge is *derived-from*.
- Auto-snapshot: when an entity is mined from a URL, fire a Wayback/archive.today
  save-call (free, keyless) and store the ref — so a since-deleted tweet is still
  citable.
- Export: `to_provenance_report()` renders the chain-of-custody for any
  conclusion (pairs with roadmap #8 reporting).

**Build steps.** (1) `Provenance` dataclass + migration on `Entity`; (2) hash raw
bytes at capture (cheap — `download_url` already stores sha256); (3) Wayback
save-call hook on URL-sourced entities; (4) provenance-report renderer.

**Status:** the `audit_log` + sha256-on-download are the seed; this promotes them
to the core data model. Links: roadmap #8, Pillar 1's graph.

### Pillar 3 — OPSEC / fingerprint-aware execution

**What.** An OSINT agent that fires requests **leaks the investigator's identity
and fingerprint to the target** — the opposite of what investigators want. A
truly specialized agent separates *passive* (third-party indexes, CT logs,
archives — the target never sees you) from *active* (you touch the target) modes,
gates/flags active contact, rotates user-agents, can route through Tor/proxies,
rate-limits to look human, and avoids cross-pivot correlation.

**Why it's a moat.** Claude Code has **zero concept of "don't let the target know
you're looking."** Its entire posture is "act openly on the user's behalf." OPSEC
is deeply OSINT-native and hard to retrofit onto a coding agent — it has to be
baked into the execution layer, the tool registry, and the prompt's stance. This
is the most OSINT-native pillar and the hardest for a generic agent to copy.

**Design.**
- Today's `investigate` vs `challenge` `Settings.mode` is the **seed**; extend it
  to an explicit **passive/active** axis per tool (a plugin declares
  `touches_target: bool`). The brain must justify an active touch; the gate can
  require confirmation (reuses the `PermissionUI` v2 seam from agentic Phase 4).
- Execution-layer OPSEC: a configurable HTTP profile (rotating UA pool,
  conservative concurrency, human-ish rate-limiting) in the shared `http` client;
  optional Tor/proxy routing behind a flag (`CAIRN_PROXY`).
- Correlation hygiene: avoid reusing the same UA/session/IP across pivots on one
  target; surface a "you've touched this target N times" indicator.

**Build steps.** (1) add `touches_target` to `BasePlugin` / `CliToolSpec` and tag
the existing tools; (2) passive/active gate in the closure; (3) UA-rotation +
rate-limit in the http client; (4) proxy/Tor flag + docs.

**Status:** `investigate` / `challenge` mode + `scrub_env` are the seed. The
hardest pillar to get right, and the most clearly differentiating. Links:
`security.md`, the agentic two-layer model.

### Pillar 4 — Temporal/decay + confidence reasoning

**What.** OSINT data is point-in-time and **rots** — a since-deleted tweet, a cert
valid-then-expired-now, a re-dated breach dump. The model should reason about
*when* something was true, snapshot aggressively (ties to P2), flag staleness,
weigh source reliability, and express **calibrated confidence** instead of
asserting flat facts.

**Why it's a moat.** A coding agent's facts are "the code, now." OSINT's facts are
"this was true at T, captured by tool X, source reliability R, freshness F."
Reasoning over that tuple — and refusing to assert past staleness — is an
investigator's core discipline, absent from generic agents.

**Design.**
- `Provenance.captured_at` + a `source_reliability` enum (from P2) feed a
  **freshness/confidence** score per entity.
- The system prompt is taught to **hedge by default** ("as of <date>, per
  <source>, confidence: medium") and to refuse high-confidence claims on stale or
  single-source evidence — the anti-injection stance's epistemic twin.
- Decay policy: entities older than a per-type threshold (a cert vs a handle rot
  differently) get a staleness flag the brain must address before relying on them.

**Build steps.** (1) reliability enum + freshness scoring on `Provenance`;
(2) prompt changes for calibrated hedging; (3) per-type decay thresholds; (4)
tests that stale evidence produces hedged output.

**Status:** unbuilt; depends on P2's `Provenance`. Links: Pillars 1, 2, system
prompt.

### Ranking, dependencies & build order

| Pillar | Leverage | Depends on (exists?) | Moat strength |
|---|---|---|---|
| 1 — Pivot engine | **Highest** (chat → investigation) | entity graph ✅ | very high |
| 2 — Provenance | High (evidence locker) | `audit_log` ✅ | high |
| 3 — OPSEC | High (OSINT-native, hard to copy) | mode ✅ | very high |
| 4 — Temporal/confidence | Medium-high (epistemic rigor) | P2 | medium |

Build order: **1 → 2 → 4** (4 needs 2's provenance); **3** runs in parallel (the
passive/active tool-tagging is independent of the others). **Pillar 1 is the
single highest-leverage piece** and the first thing to promote off this backburner
onto the active roadmap after the challenge-mode smoke lands.

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
