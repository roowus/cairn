# Roadmap

What's next for Cairn, ordered by leverage. Each item maps onto the
["like Claude Code" model](architecture/claude-code-model.md) — extending the
brain, its tools, or the know-how layered on top — while keeping the free-first,
hard-stop invariants intact.

## 0. Agentic file & tool control (OSINT challenges) — ✅ ACTIVE

The brain now has **Claude Code parity over files**: read, write, list,
download, arbitrary shell, and tool install — so Cairn can solve OSINT
challenges (file forensics, pcap, document extraction, stego), "whatever means
necessary." Added **without weakening the hard-stop**: a *relaxed execution
layer* (auto-allow inside the workspace) is kept orthogonal to the *preserved
anti-injection layer* (every result still wrapped in
`<untrusted_external_data>`). See
[agentic file & tool control](architecture/agentic-file-control.md).

- ✅ Phase 1 — foundations: workspace boundary, permission gate, env-scrub,
  `run_shell` (`bash -c` via array args), `Settings.mode` / `workspace_dir`.
- ✅ Phase 2 — the five agentic plugins (`read_file`, `list_files`,
  `write_file`, `download_url`, `run_command`); boundary + scrub + wrap-back +
  exit-code-as-data tested (165 tests, ruff clean).
- ✅ Phase 3 — mode-gated `build_system_prompt`; two-tier analyzer allowlist
  (uv vs system); `security.md` section (174 tests).
- ✅ Phase 4 — `/workspace` (`/files`) REPL command; `RichPermissionUI` v2 seam
  (tested in isolation; not wired into the live turn) (181 tests).
- ✅ Phase 5 — adversarial review DONE (6-lens / 3-skeptic workflow; **5 defects
  fixed, 2 major** — incl. a Layer-B `wrap_untrusted` attribute-bypass closed
  via `_attr_escape`). Real-model `CAIRN_MODE=challenge` smoke **partial** —
  `read_file` verified end-to-end on grok-4.5 (2026-07-28);
  `run_command`/`scrub_env`/Esc-cancel prompts still pending. Repo
  total now **187 tests, ruff clean** (the Phase-6 theme foundation added 3 on
  top of the 184 at review).

## UI overhaul — the live "function like pi" REPL — ✅ DONE

The REPL is now a live terminal app: the answer streams in place, tool calls
animate as cards keyed by `tool_call_id`, a header/statusline persists, and each
turn seals into scrollback as a structured block (header + boxed tools + boxed
answer + footer) — no vanishing frames, no alt-screen. Built as U1–U6:

- ✅ **U1** zoned chrome · **U2** prompt_toolkit input (history + completion) ·
  **U3** collapsible thinking + live CLI stdout into cards (per-call `ContextVar`
  bridge, parallel-safe under concurrent tool execution) · **U4** `!`/`!!` shell
  + `@file` inline (user-trusted) · **U5** centralized theme tokens
  (render-identical) · **U6** JSONL sessions + `/sessions` `/resume` `/compact`
  `/fork`.

Invariant preserved: Rich `Live` and prompt_toolkit never run concurrently. The
multi-agent `/spawn` + laned view remain (tracked in #2, on the SessionPool
backend). See [UI overhaul](architecture/ui-overhaul.md). **276 tests, ruff clean.**

## Evidence model — provenance, confidence, OPSEC, typed assets — ✅ DONE

Lands the concrete implementations of the [strategy moats](strategy.md)
(Pillars 2–4 implemented; Pillar 1's data shape landed), models + tradecraft
adapted from [Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT) (MIT).
See [evidence model](architecture/evidence-model.md).

- ✅ **Provenance (P2)** — `Provenance`/`Confidence`/`Severity`/`Finding` models
  (`core/provenance.py`); `Entity` carries optional provenance/confidence/first_seen;
  graph store round-trips them and promotes confidence to firm on ≥2 sources.
- ✅ **OPSEC detectability (P3)** — `detectability` (low/medium/high) on every
  plugin + CLI tool; surfaced in listings; passive-by-default taught to the brain.
- ✅ **Confidence/severity/scope in the brain (P4)** — always-on discipline
  (tentative/firm/confirmed + rule-of-three + downgrade-by-default + scope-check).
- ✅ **Typed-asset taxonomy (P1 data shape)** — `core/assets.py` (9 categories +
  `asset_key` + edge vocab); `subdomain` mined additively. The BFS pivot engine
  itself (§3) is the next epic on this substrate.
- ✅ **Two plugins** — `secret_scan` (48-pattern secret scanner) + `h1_reference`
  (keyless HackerOne reference).
- ✅ **8 tradecraft skills** — `recon-methodology` + 7 chunked arsenals, Cairn-
  adapted (active gated, paid excluded, MIT attributed).

## 1. The investigative brain (system prompt rewrite) — ✅ DONE

`reasoning/system_prompt.py` is now the **investigator brain** that drives the
[loop](architecture/investigator-loop.md): it steers the model to generate
dorks, search, scrape, read the mined entities, pivot on each, run independent
calls in parallel, and stop when answered or budget-exhausted. The Phase-3 work
above (item 0) adds a `build_system_prompt(settings)` that selects the recon
stance by `Settings.mode` (investigate vs challenge) on top of this brain.

## 2. Skills system (Claude-Code "skills") — ✅ DONE

Reusable investigation workflows invoked by name — the OSINT analogue of Claude
Code skills and OpenOSINT's YAML playbooks. Shipped: a `skills/` package with a
loader (`discover_skills`) and four built-in playbooks, plus REPL dispatch
(`/skills` to list, `/<skill> <target>` to run). A skill is Markdown with tiny
frontmatter (`name`/`description`/`usage`); it injects the playbook as extra
context for the turn, orchestrating *existing* tools (no new capability). User
playbooks in `~/.cairn/skills/` override built-ins by name.

- `/investigate-person <handle>` — full identity pivot loop.
- `/breach-check <email>` — holehe + hibp + dork.
- `/domain-recon <domain>` — whois + crtsh + dns + wayback + urlscan.
- `/ip-enrich <ip>` — shodan_internetdb + urlscan + hackertarget + ripestat.

Next: a `cairn skills` headless command for parity, and more playbooks.

## 3. Deterministic BFS pivot engine

Today the brain governs pivoting and termination (flexible, but not bounded or
reproducible). Add an optional OpenOSINT-style engine: entity graph + breadth-
first pivot with explicit `max_depth`, max-entities-per-step, and max-tool-calls
budgets. Keeps the brain in charge of *strategy* while making breadth and cost
deterministic. Lives in `orchestration/`, behind a flag.

## 4. Social channels via cookies (agent-reach model)

**Already shipped (tier A — no cookies):** first-party `username_check`,
browser-like HTTP, Sherlock cross-check, GitHub commit emails / YT embeds.
See [social-probing.md](social-probing.md).

**Still to build (tier B/C):** `plugins/social/` behind login walls using the
local browser's cookies (`browser_cookie3`) and, where needed, Playwright.
Order: **YouTube metadata (`yt-dlp`) → X/Twitter cookies → Reddit cookies →
Instagram Playwright (posts/graph)**. Facebook/LinkedIn remain hard gaps.
Behind a `[social]` extra so cookie/browser deps stay out of core. See
[agent-reach analysis](research/agent-reach-analysis.md).

## 5. MCP — client + server

- **Client:** consume remote OSINT MCP servers (e.g. a Censys or Shodan MCP) as
  just another tool source — broadens the palette without writing plugins.
- **Server:** expose every Cairn plugin as MCP tools, so *other* AI agents
  (Claude Code included) can use Cairn's OSINT capabilities. `interfaces/mcp.py`
  stub already exists; flesh it out (~50-line adapter over the registry).

## 6. Image search / face match (the image pivot)

The last step of the loop. Given a profile picture (already captured via
`scrape_url`'s `og:image`, and GitHub `avatar_url` entities), reverse-image-
search it and optionally face-match to find the same person on other platforms.
**Free-first:** prefer open reverse-image endpoints; paid face-recognition
services (facecheck) are excluded by the
[avoid-paid-platforms directive](discoveries.md#avoid-paid-platforms-directive-user-feedback).
YouTube **embed URLs** are already mined from GitHub portfolio docs; full video
analysis (metadata via `yt-dlp`, optional ASR/frames) is adjacent work.

## 7. Scrape backends: Jina Reader + crawl4ai promotion

- Wire **Jina Reader** (`r.jina.ai/{url}` → clean markdown, still free no-key,
  JS-capable) as a `scrape_url` backend option — a no-dep alternative to
  crawl4ai. (Note: Jina *Search* `s.jina.ai` now requires a key and is **not** a
  free search option.)
- Promote crawl4ai as the default when installed for JS-heavy social pages.

## 8. Reporting & export

- **PDF reports** (`reportlab`) — the OpenOSINT-style deliverable.
- **STIX 2.1** export — additive `to_stix()` on `Entity`/`PluginOutput`
  (outputs are already structured Pydantic). Behind `[decisions/0004]`'s seam.

## 9. Subagents (specialised brains)

The deferred multi-agent coordinator: spawn focused investigator agents
(identity / infrastructure / web) composed by a future
`reasoning/coordinator.py`. No Layer-3 change — they share the same tool
registry. Lowest priority; only worth it once single-brain breadth becomes a
limit.

**Foundation landed for issue #2** (parallel sessions): a
[`SessionPool`](../src/cairn/orchestration/session_pool.py) runs N concurrent
sessions on one loop with a shared audit log, per-session budgets, cancel-by-id,
and on-demand graph merge — the throughput/orchestration substrate for both
this item and the parallel-sessions epic. The UI wiring (`/spawn`, laned view)
is deferred until U6 lands; see
[parallel sessions](architecture/parallel-sessions.md).

## 10. Usage & cost reporting — ✅ DONE

The brain can reach for daily-quota'd and credit-metered sources, so the CLI now
reports exactly what each investigation costs — credits used, time taken, and
rate/quota/service usage, focused on the metered and paid plugins. Each plugin
declares a `CostSpec` (unit, per-call cost, daily/monthly quota, paid flag);
live usage accumulates in a `UsageTracker` and is persisted per-call to the
`audit_log` (`elapsed_ms` + `usage_json`). Surfaces: `/usage` (REPL), a per-turn
summary line, a post-run block in `cairn search`, `cairn usage` (historical, from
the audit log), and a cost column in `cairn plugins`. See
[usage & cost](architecture/usage-and-cost.md).

---

### Priority summary

| # | Item | Layer touched | Effort |
|---|---|---|---|
| 0 | Agentic file & tool control ✅ ACTIVE | execution + reasoning | L |
| 1 | Investigative system prompt ✅ | reasoning | S |
| 2 | Skills system ✅ | interfaces + reasoning | M |
| 3 | BFS pivot engine | orchestration | M |
| 4 | Social channels (cookies) | execution (new `social/`) | L |
| 5 | MCP client + server | interfaces | M |
| 6 | Image search / face match | execution (new plugin) | M |
| 7 | Jina Reader + crawl4ai | execution (web) | S |
| 8 | PDF + STIX export | interfaces / core | M |
| 9 | Subagents | reasoning | L |
| 10 | Usage & cost reporting ✅ | orchestration + interfaces | M |
