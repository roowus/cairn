# The Investigator Loop

> How the brain actually investigates: **search → scrape → extract → pivot →
> (image)**, recursively, until the budget runs out or the question is answered.

This is the operationalisation of the "LLM-driven investigator" reframe (see
[The "Like Claude Code" Model](claude-code-model.md)). The plugins are
primitive operations; *the loop is the intelligence*. The brain runs the loop;
the tools feed it.

## The loop, in one diagram

```
         ┌─────────────────────────────────────────────────────┐
         │  user goal: "find out who @jane_doe across the web"  │
         └───────────────────────┬─────────────────────────────┘
                                 ▼
   ┌─────────────────── SEARCH ───────────────────┐
   │ generate_dorks("jane_doe") → dork recipes     │
   │ web_search(site:instagram.com "jane_doe")     │   ◀── primitives
   └───────────────────────┬───────────────────────┘
                           ▼
   ┌─────────────────── SCRAPE ───────────────────┐
   │ scrape_url(result URL) → text/links/images    │
   └───────────────────────┬───────────────────────┘
                           ▼
   ┌─────────── EXTRACT (automatic, in-tool) ──────┐
   │ core/entities.py mines: emails, URLs, IPs,    │
   │ domains, BTC/ETH addrs, phones, usernames     │
   └───────────────────────┬───────────────────────┘
                           ▼
   ┌─────────────────── PIVOT ─────────────────────┐
   │ each new entity becomes a new target:          │
   │  email → breach check / holehe                 │
   │  domain → whois_rdap / crtsh / dns_lookup      │
   │  ip → shodan_internetdb / urlscan / hackertarget│
   │  username → username_check → github → sherlock │
   │             (majors first-party)  (emails/YT)  │
   └───────────────────────┬───────────────────────┘
                           ▼
   ┌──────────────── IMAGE (deferred) ─────────────┐
   │ profile picture → reverse image / face match   │
   └───────────────────────┬───────────────────────┘
                           ▼
                  loop until answered / budget hit
                           ▼
                  synthesise grounded findings
```

## Worked example: from an Instagram handle to a wider identity

This is the canonical "layered thinking" the project was re-scoped to enable.
With the brain driving, a single prompt like *"investigate the Instagram user
`@jane_doe`"* unfolds as:

1. **Confirm the handle on majors.** `username_check("jane_doe")` hits
   **first-party** Instagram/GitHub/… (not Sherlock mirrors). See
   [social-probing.md](../social-probing.md).
2. **Search.** `generate_dorks` + `web_search` (`site:instagram.com "…"`, etc.).
3. **Scrape.** `scrape_url` → text/links/images (`og:image` profile pic).
4. **Extract.** Automatic entity mining (emails, URLs, usernames, …) into the graph.
5. **Pivot.** Each mined entity seeds the next move:
   - `email` → `holehe`, `hibp` (if keyed).
   - `github` URL/login → `github` → repos, **commit-mined emails**, blog,
     avatar, YouTube embeds (profile `email` is often null).
   - `domain` → `whois_rdap`, `crtsh`, `dns_lookup`, `wayback_cdx`.
   - `ip` → `shodan_internetdb`, `urlscan`, `hackertarget`.
   - `username` → `username_check` → `github` → optional `sherlock` long-tail.
6. **Image / video (planned).** Reverse-image on avatars; YT **URLs** may already
   come from `github` embed mining. Full video analysis still deferred —
   [Roadmap](../roadmap.md).
7. **Synthesise.** One-line conclusion, bulleted evidence per source, next steps.
   Nothing stated that a tool did not return.

The crucial property: at no point does a human hand-chain these tools, and at no
point does the model invent a data point. The brain plans; the tools ground.

## Why entity extraction is *inside* the tools, not a separate tool

`core/entities.py` is a pure-stdlib regex extractor (`email`, `url`, `ip`,
`crypto_btc`, `crypto_eth`, `phone`, `domain`). It runs *inside* `scrape_url`
and `web_search` before their output is returned, so every page a tool returns
already carries a `entities: list[Entity]` field. The `tool_adapter` pushes
those entities into the NetworkX graph automatically.

Consequence for the brain: it doesn't have to "ask" to extract entities (which
would waste a turn). Entities are ambient — the brain sees them in the wrapped
summary and decides whether to pivot on them. This keeps the loop tight and the
token budget low.

## Budgets and termination

The loop is not unbounded. The brain is steered (via the system prompt and the
per-session token budget in `orchestration/budget.py`) to:

- run independent lookups **in parallel**,
- **stop** when the question is answered or the budget is exhausted,
- prefer **free/no-key** tools first and only *note* when a keyed source would
  help (never fail silently).

An OpenOSINT-style explicit BFS pivot engine (depth/tool-call/entity budgets)
is a planned hardening — see [Roadmap](../roadmap.md). Today the brain governs
termination; the engine will make it deterministic.

## What's wired vs. what's next

| Loop step | Today | Next |
|---|---|---|
| Search | ✅ `web_search` (DDG/Brave), `generate_dorks` | keyed Exa; structured pivot engine |
| Scrape | ✅ `scrape_url` (httpx+BS4 / crawl4ai) | Jina Reader backend; cookie-authed social channels |
| Extract | ✅ `core/entities.py` (in-tool) | NER / username-across-platforms heuristic |
| Pivot | 🟡 brain-driven | deterministic BFS engine + entity graph queries |
| Image | ⏸ not built | reverse-image + face-match plugin (free-first) |
| Social channels | ⏸ not built | Twitter/Reddit/Bilibili/YouTube via cookies (see [agent-reach analysis](../research/agent-reach-analysis.md)) |
