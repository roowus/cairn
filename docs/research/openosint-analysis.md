# Research: OpenOSINT (`OpenOSINT/OpenOSINT`)

> Deep-read of a comparable Anthropic-SDK OSINT agent, to match its capabilities
> while staying free-first and provider-agnostic.

## What OpenOSINT is

A terminal OSINT agent built on the **Anthropic SDK's native tool-use loop**
(not a framework). You give it a target + an objective; it plans a search,
scrapes, extracts entities, and pivots — driven by the model — then writes a
report.

### Architecture (observed in source)

- **Tool-use loop** — straight `anthropic` messages + tool definitions; the loop
  re-feeds tool results until the model stops calling tools.
- **Bright Data** (the **paid** part we explicitly reject) powers two tools:
  - `search_dorks_live` — live Google/Bing results via Bright Data's SERP API.
  - `scrape_url` — Bright Data Web Unlocker, which defeats anti-bot/JS on
    walled sites.
- **Entity correlation graph + BFS pivot engine** — the standout. Entities are
  nodes; a breadth-first pivot runs with explicit budgets:
  `max_depth`, max entities per step, max total tool calls. Each tool has a
  registered *extractor* that pulls entities from its raw output.
- **`generate_dorks`** — 12 offline dork templates (no network) producing
  `site:`, `filetype:`, `intitle:`, leak/resume variants.
- **YAML playbooks** — reusable investigation workflows per objective.
- **PDF reports** via `reportlab`.
- **MCP server** — exposes its tools over the Model Context Protocol.

## What Cairn already matches

| OpenOSINT feature | Cairn equivalent | Notes |
|---|---|---|
| `generate_dorks` (12 templates) | `generate_dorks` plugin | Same idea; Cairn covers site/filetype/intitle/leak/resume per-platform. |
| `search_dorks_live` (Bright Data) | `web_search` | DDG (free) default, Brave (free-tier key) upgrade. **No Bright Data.** |
| `scrape_url` (Bright Data Unlocker) | `scrape_url` | httpx+BS4 default, crawl4ai for JS. **No paid unlocker.** |
| Per-tool extractors | `core/entities.py` (central) + plugin `entities` | Cairn extracts once centrally; OpenOSINT has one extractor per tool. |
| Tool-use loop | PydanticAI `Agent` + `tool_adapter` | Cairn is framework-based + provider-agnostic; OpenOSINT is Anthropic-locked. |
| Audit / grounding | audit log + `<untrusted_external_data>` | Cairn bakes the anti-fabrication invariant into the adapter. |
| MCP server | `interfaces/mcp.py` stub | Cairn: designed, not built. |

## What Cairn deliberately does differently

1. **Free-first, no Bright Data.** OpenOSINT's quality comes largely from paid
   SERP + anti-bot scraping. Cairn substitutes DDG/Brave + httpx/crawl4ai/Jina
   Reader, and treats walled social platforms via the **agent-reach cookie
   model** rather than a paid unlocker. (See
   [agent-reach analysis](agent-reach-analysis.md).)
2. **Provider-agnostic.** OpenOSINT is hard-bound to Anthropic. Cairn's
   `reasoning/agent.py` builds the model from config — **xAI Grok**, Claude,
   GPT, GLM (Z.AI, free), or local Ollama — with runtime `/model` switching and
   optional credential reuse from the `pi` coding-agent auth store.
   ([discoveries § provider matrix](../discoveries.md#provider-matrix),
   [configuration](../configuration.md))
3. **Hard-stop three-layer** enforcement (no upward imports; AST-tested). The
   model structurally cannot execute or see raw payloads. OpenOSINT is a flatter
   loop without that invariant.

## What to adopt from OpenOSINT (Roadmap inputs)

- **Deterministic BFS pivot engine** with explicit `max_depth` /
  max-entities / max-tool-calls budgets. Today Cairn's brain governs
  termination (good, flexible) but a budgeted engine makes pivoting reproducible
  and bounded. → [Roadmap](../roadmap.md)
- **YAML playbooks → Cairn "skills."** Reusable investigation workflows the user
  invokes by name (like Claude Code skills): `/investigate-person`,
  `/breach-check`, `/domain-recon`. → maps onto the new skills system.
- **PDF/report output** (`reportlab`) as an export interface.
- **Per-tool extractors** as an optional refinement (today's central
  `core/entities.py` is simpler; per-tool extractors add precision for
  platform-specific entity shapes).
