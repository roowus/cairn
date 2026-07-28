# Cairn strategy — the moat

> **This is the thesis that decides whether Cairn is a product or a thin wrapper.**
> The actionable work for each pillar is tracked in
> [issue #3 (moat epic)](https://github.com/roowus/cairn/issues/3); this doc is
> the durable north-star. The four pillars below are *where the moat has to live*:
> not in the tool inventory (tools are substitutable — any OSINT MCP can serve the
> same lookups), but in the **investigation substrate** the agent runs on.

## The problem (why this matters now)

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

## Pillar 1 — Provenance-backed entity-graph pivot engine (THE #1 priority)

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

**Status:** design (roadmap #3). Seed: the existing entity graph + `audit_log`.

## Pillar 2 — Provenance / chain-of-custody as a first-class data model

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

## Pillar 3 — OPSEC / fingerprint-aware execution

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

## Pillar 4 — Temporal/decay + confidence reasoning

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

## Ranking, dependencies & build order

| Pillar | Leverage | Depends on (exists?) | Moat strength |
|---|---|---|---|
| 1 — Pivot engine | **Highest** (chat → investigation) | entity graph ✅ | very high |
| 2 — Provenance | High (evidence locker) | `audit_log` ✅ | high |
| 3 — OPSEC | High (OSINT-native, hard to copy) | mode ✅ | very high |
| 4 — Temporal/confidence | Medium-high (epistemic rigor) | P2 | medium |

Build order: **1 → 2 → 4** (4 needs 2's provenance); **3** runs in parallel (the
passive/active tool-tagging is independent of the others). **Pillar 1 is the
single highest-leverage piece** and the first thing to promote onto the active
roadmap.
