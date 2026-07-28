# Cairn

> Terminal-native **agentic OSINT** assistant — like Claude Code, but for OSINT.

You describe a target or investigation in plain English. An LLM — the **brain** —
plans the steps and chains deterministic OSINT tool calls. The tools run for
real; the model only ever sees sanitized summaries. Every action is audited.

**The model never executes code.** It emits structured tool calls; local Python
runs them. This "hard-stop execution" makes fabricated findings structurally
impossible at the execution layer. The AI is the brain doing the task; the
plugins are the tools it reaches for — search, scrape, extract, pivot, image.
See [how the investigator loop works](docs/architecture/investigator-loop.md).

## Status

Phase 1 (MVP): interactive REPL + headless CLI, plugin registry, PydanticAI
agent, SQLite audit + NetworkX graph, **20 OSINT plugins** (free-first), live
progress output, and an entity-extraction pivot layer. STIX output, graph/vector
DBs, multi-agent, MCP, and REST are designed behind clean seams — see
[docs/roadmap.md](docs/roadmap.md) and
[docs/decisions/0004](docs/decisions/0004-defer-kuzu-qdrant-stix-mcp.md).

## Quick start

```bash
uv sync --extra dev        # install deps (uv required: https://docs.astral.sh/uv)
cp .env.example .env       # then edit .env with your LLM provider/key
make install-global        # puts `cairn` on PATH (editable install → ~/.local/bin)

# From any directory:
cairn                      # interactive REPL
cairn plugin shodan-internetdb 8.8.8.8
cairn plugin whois-rdap example.com
cairn plugin crtsh example.com            # subdomains
cairn plugin dns-lookup example.com --record-type MX
```

`make install-global` runs `uv tool install --editable .` and seeds
`~/.cairn/.env` so config works outside the repo (same idea as `pi` / `claude`).
Re-run it after cloning on a new machine. Code edits in this checkout are picked
up immediately (editable).

No cloud key at all? Use local Ollama:

> **Note:** the agentic loop needs a **tool-capable** model. `llama3.1`,
> `qwen2.5`, `mistral`, and `llama3.2` work; vision models like `llava-phi3`
> reject tool calls. `scripts/bootstrap_ollama.sh` pulls `llama3.1` by default.

```bash
bash scripts/bootstrap_ollama.sh        # one-time model pull
export CAIRN_LLM__PROVIDER=openai \
       CAIRN_LLM__MODEL=llama3.1 \
       CAIRN_LLM__BASE_URL=http://localhost:11434/v1 \
       CAIRN_LLM__API_KEY=ollama
uv run cairn
```

## Configuration

There is **no default LLM provider**. Set whichever you have:

| Variable | Meaning |
|---|---|
| `CAIRN_LLM__PROVIDER` | `xai` \| `anthropic` \| `openai` \| `openai`(+base_url for Ollama) |
| `CAIRN_LLM__MODEL` | e.g. `grok-4.5`, `claude-sonnet-5`, `gpt-4o`, `glm-5.2`, `llama3.1` |
| `CAIRN_LLM__API_KEY` | your key (optional for xAI/Z.AI if `pi` auth is present; `ollama` for local) |
| `CAIRN_LLM__BASE_URL` | only for Ollama / OpenAI-compatible gateways |
| `CAIRN_<SOURCE>_KEY` | optional — `SHODAN`, `VIRUSTOTAL`, `CENSYS`, `ABUSEIPDB`, `HIBP`, `BRAVE`, `EXA` |

Precedence: real env vars > `~/.cairn/.env` > `./.env` > `~/.cairn/config.toml`.

**xAI Grok / Z.AI GLM:** if `CAIRN_LLM__API_KEY` is unset, Cairn reuses
`~/.pi/agent/auth.json` (xAI OAuth access token or `zai.key`). In the REPL:

```text
/model            # list profiles (★ current, ✓ credentials found)
/model grok       # switch to grok-4.5
/model glm        # switch to glm-5.2
```

**Esc** or **Ctrl-C** stops the current agent turn (stays in the REPL).
External CLIs (`sherlock`, `holehe`) **auto-install** at startup / first use —
you never run an install command yourself.

Deep dive: [docs/configuration.md](docs/configuration.md).
Social / Sherlock / Instagram lessons: [docs/social-probing.md](docs/social-probing.md).

## Plugins

**Free / no key** — the default set works with zero keys:
`shodan_internetdb`, `whois_rdap`, `dns_lookup`, `crtsh`, `wayback_cdx`,
`ripestat`, `wayback_fetch`, `common_crawl`, `github`, `urlscan`, plus the
investigator primitives `generate_dorks`, `web_search`, `scrape_url` (and
`core/entities` extraction built in).
**Off by default (daily quota):** `hackertarget` (~50/day) — opt in with
`CAIRN_ALLOW_DAILY_LIMITED=1`.
**Key-gated** (free-tier-with-key; activate when their `CAIRN_*_KEY` is set):
`shodan_full`, `virustotal`, `censys`, `abuseipdb`, `hibp`.
**External CLIs:** `holehe` + `sherlock` **auto-install** at REPL startup and on
first use (allowlisted `uv tool install`). No manual step.

`cairn plugins` lists every plugin with its tier, **cost** (free · 50/day ·
credits · paid · …) and whether the brain will use it (`active` / `hidden` +
reason). `cairn usage` and the REPL `/usage` show **credits used, time taken, and
rate/quota** across metered/paid sources — see
[usage & cost reporting](docs/architecture/usage-and-cost.md).

> **Web search needs a key to be reliable.** Free no-key search (DuckDuckGo) is
> blocked by anti-bot in 2026 — `web_search` will tell you so and point you to a
> free **Brave Search API** key (2,000/mo): set `CAIRN_BRAVE_KEY`.

Full catalogue with inputs, outputs, and entities:
[docs/plugin-reference.md](docs/plugin-reference.md). Add your own:
`uv run scripts/new_plugin.py identity my_lookup` — see
[docs/plugin-authoring.md](docs/plugin-authoring.md).

## Skills (investigation playbooks)

In the REPL, run a packaged workflow by name — the brain gets a focused playbook
for that turn, orchestrating the tools above (no new capability, just know-how):

```
cairn> /skills                       # list playbooks
cairn> /investigate-person jane_doe  # full identity pivot loop
cairn> /domain-recon example.com     # passive domain recon
cairn> /ip-enrich 8.8.8.8            # IP enrichment
cairn> /breach-check jane@x.com      # breach / exposure check
```

Drop your own `*.md` playbook in `~/.cairn/skills/` to override or extend.

## Architecture

Three decoupled layers, unidirectional dependencies, no upward imports:

```
reasoning ──▶ orchestration ──▶ execution
  (LLM)         (validate/          (deterministic runners)
                 audit/graph)
                     │
                     ▼
            storage (SQLite + NetworkX)
```

See [docs/architecture/overview.md](docs/architecture/overview.md) and
[docs/architecture/security.md](docs/architecture/security.md). The original
research these designs are based on lives in [docs/research/](docs/research/).

## Development

```bash
make dev             # install core + dev deps
make install-global  # `cairn` on PATH (editable) + ~/.cairn/.env
make test            # unit tests (no network)
make test-net        # + real free-API calls
make lint format typecheck
make docs-import     # convert research RTFs to Markdown
```

Docs index: [docs/README.md](docs/README.md).

## License

MIT.
