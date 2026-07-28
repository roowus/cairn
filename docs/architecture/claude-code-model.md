# The "Like Claude Code" Model

> **The AI is the brain doing the task; the tools are capabilities it reaches
> for.** Cairn is an LLM-driven investigator, not a toolkit with an LLM bolted
> on.

This page maps Cairn onto the architecture that makes Claude Code effective, and
records which pieces exist today versus which are designed-but-unbuilt.

## The mental model

Claude Code is, at its core, three things:

1. **A brain** — an LLM running in an agent loop. It reads the goal, reasons
   about the next step, and decides *which capability to invoke*.
2. **A set of tools** — typed functions the brain can call (`Read`, `Write`,
   `Bash`, …). The brain never manipulates the filesystem directly; it asks a
   tool to do it and reads back the result.
3. **Packaged know-how layered on top** — *skills* (reusable workflows), *MCP*
   servers (external tool sources), and *subagents* (specialised brains) — so
   the same brain can do more without growing larger.

Cairn is the same shape, but the domain is OSINT instead of coding:

| Claude Code | Cairn | Status |
|---|---|---|
| The model (agent loop) | `reasoning/` — a PydanticAI `Agent` | ✅ built |
| Tools (`Read`, `Bash`, …) | **OSINT plugins**, each wrapped as a tool by `orchestration/tool_adapter.py` | ✅ built (20+) |
| System prompt | `reasoning/system_prompt.py` | ✅ built (generic passive-OSINT; investigative brain rewrite is the next step) |
| Live status / streaming | `orchestration/progress.py` tap → REPL/headless render | ✅ built |
| Context window + memory | `Session.history` + token budget (`orchestration/budget.py`) | ✅ built |
| Permissions / audit trail | append-only audit log + `<untrusted_external_data>` wrap | ✅ built |
| Skills (packaged workflows) | **investigation playbooks** — `/skills`, `/investigate-person`, `/domain-recon`, `/ip-enrich`, `/breach-check` | ✅ built (`skills/` + 4 built-ins + user overrides) |
| Model picker | `/model` + `reasoning/catalog.py` + `Session.switch_model` (Grok/GLM/Ollama/…) | ✅ built |
| Provider credentials | env + `~/.cairn/.env` + **pi `auth.json` OAuth/key reuse** (`core/pi_auth.py`) | ✅ built |
| Global CLI on PATH | `make install-global` → `~/.local/bin/cairn` (editable uv tool) | ✅ built |
| Interrupt turn | Esc / Ctrl-C cancels in-flight agent turn (`interfaces/interrupt.py`) | ✅ built |
| Self-install tool deps | allowlisted `uv tool install` for `sherlock`/`holehe` (startup + first use) | ✅ built |
| Browser-like HTTP + first-party social probes | `browser_http` + `social_probe` + `username_check`; Sherlock cross-check | ✅ built |
| GitHub commit email mining | profile email often null; mine commits + gh-pages docs | ✅ built |
| MCP *client* | consume remote OSINT MCP servers (e.g. a Censys/Shodan MCP) | 🟡 designed |
| MCP *server* | expose every Cairn plugin as MCP tools for *other* AI agents | 🟡 stub (`interfaces/mcp.py`) |
| Subagents | specialised investigator agents (identity, infra, web) | ⏸ deferred (clean seam) |
| Slash commands | `/help` `/model` `/install` `/plugins` `/skills` `/graph` `/audit` `/reset` + skill names + `cairn plugin <name>` | ✅ built |

## Why this framing matters

The key reframe (recorded as user feedback): *the point is not for Cairn to be
an OSINT toolkit — the LLM itself is the intelligence.* A dumb toolkit just
exposes lookups and waits for a human to chain them. Cairn's value is that the
**LLM plans the chain**: it decides what to search, what to scrape, what to
extract, and where to pivot next, using the tools as primitive operations.

That distinction shows up concretely in the layering:

- The **brain** (`reasoning/`) has *no* shell, socket, or subprocess access. It
  can only reason and emit tool calls. It cannot "do" anything itself.
- The **tools** (`execution/` plugins) are deterministic, audited, and return
  only sanitised Markdown summaries wrapped in `<untrusted_external_data>`. The
  brain consumes their output as *observation*, never as instruction.

So the brain is powerful but sandboxed; the tools are capable but dumb. The
intelligence lives in *what the brain chooses to call, in what order, and how it
interprets the results* — exactly like Claude Code.

## The investigator's primitive operations (the "tools" palette)

The brain reaches for these. Each is one plugin = one tool:

- **Search** → `web_search` (DDG free / Brave keyed), `generate_dorks` (offline
  dork recipes).
- **Read a page** → `scrape_url` (httpx+BS4 free / crawl4ai JS-capable; Jina
  Reader as a free option).
- **Identity** → `username_check` (first-party social presence), `github`
  (incl. commit emails + YT embeds), `whois_rdap`, `shodan_internetdb`,
  `holehe`, `sherlock` (long-tail + first-party cross-check).
- **Infrastructure** → `dns_lookup`, `crtsh`, `wayback_cdx`, `ripestat`,
  `hackertarget`, `urlscan`.
- **Web/history** → `wayback_fetch`, `common_crawl`.
- **Entity extraction** → `core/entities.py` (runs *inside* scrape/search, not a
  separate tool the brain calls — it mines emails, URLs, IPs, domains, crypto
  addresses, phones from every page automatically).
- **Keyed (activate with a key)** → `shodan_full`, `virustotal`, `censys`,
  `abuseipdb`, `hibp`.
- **Self-provision** → `install_cli` (allowlisted external binaries only).
  `sherlock` / `holehe` also auto-install on first use.

Full catalogue with inputs/outputs/entities: [Plugin Reference](../plugin-reference.md).
Day-to-day setup (PATH, models, Esc, install): [Configuration](../configuration.md).

## Layering = Claude Code's "the model can't touch the filesystem," generalised

Claude Code's safety property is that the *model* never executes — a tool does.
Cairn generalises that to OSINT: the model never makes a network request, runs a
subprocess, or sees a raw payload. Everything flows through deterministic
plugins, gets validated into Pydantic models, and returns as a summary. A
fabricated port, hostname, or breach entry is therefore *structurally
impossible* at the execution layer — it can only come from a real tool call that
is recorded in the audit log.

See [Security model](security.md) and [The investigator loop](investigator-loop.md).
