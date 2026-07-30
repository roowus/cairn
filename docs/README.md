# Cairn Documentation

> Cairn is an **LLM-driven OSINT investigator** — like Claude Code, but for OSINT.
> The AI is the brain doing the task; the plugins are the tools it reaches for.

## Start here

- **[Configuration, install & model switching](configuration.md)** — global `cairn` on PATH, `~/.cairn`, xAI/Grok + pi OAuth, `/model`, Esc-to-stop, allowlisted CLI auto-install (`sherlock`/`holehe`). **Read this to run Cairn day-to-day.**
- **[Social probing](social-probing.md)** — why incognito ≠ Sherlock; first-party probes; browser-like HTTP; `username_check` vs `sherlock`; GitHub commit emails; “look like a human” tiers.
- **[The "Like Claude Code" Model](architecture/claude-code-model.md)** — how Cairn maps onto Claude Code (brain + tools + skills + MCP). The mental model.
- **[The Investigator Loop](architecture/investigator-loop.md)** — search → scrape → extract → pivot → image, driven by the brain.
- **[Discoveries](discoveries.md)** — engineering notes: providers, PydanticAI, free-first, hard-stop, pi-auth, social probes, CLI auto-install.
- **[Plugin Reference](plugin-reference.md)** — every plugin (cost, target, purpose, entities).
- **[Roadmap](roadmap.md)** — what's next: cookie social channels, reverse image, video, MCP.
- **[Strategy — the moat](strategy.md)** — the product thesis (4 pillars): why Cairn isn't just "Claude Code + OSINT MCPs".
- **[Known limitations](known-limitations.md)** — holehe's rate-limit ceiling, the GLM headless gap, Grok billing, parallel-contribution PR hygiene.
- **Backlog** is [GitHub issues](https://github.com/roowus/cairn/issues) (`enhancement` / `bug` / `priority` / `moat` / `decision-needed`), not a doc.

## Architecture

- **[Overview](architecture/overview.md)** — the three-layer model and dependency rules.
- **[Security model](architecture/security.md)** — hard-stop execution, injection defenses, audit log, allowlisted installs.
- **[Agentic file & tool control](architecture/agentic-file-control.md)** — Claude Code parity (read/write/download/shell/install) via a relaxed *execution* layer that preserves the *anti-injection* layer; investigate vs challenge mode.
- **[Evidence model](architecture/evidence-model.md)** — provenance, confidence, severity, OPSEC detectability, typed-asset taxonomy (the strategy moats, implemented) + 8 tradecraft skills + the `secret_scan` / `h1_reference` plugins.
- **[UI overhaul](architecture/ui-overhaul.md)** — the live REPL: zoned chrome, prompt_toolkit input, collapsible thinking + live stdout, `!`/`!!`/`@file`, theme tokens, JSONL sessions (U1–U6).
- **[Parallel sessions](architecture/parallel-sessions.md)** — the SessionPool backend (N concurrent sessions, shared audit) for issue #2.
- **[Usage & cost reporting](architecture/usage-and-cost.md)** — credits/time/quota per source (`/usage`, `cairn usage`, the cost column).
- **[Plugin contract](architecture/plugin-contract.md)** — how plugins are defined and discovered.
- **[Authoring a plugin](plugin-authoring.md)** — step-by-step.

## Decisions & research

- **[Decisions (ADRs)](decisions/)** — why each major choice was made.
- **[Research](research/)** — design documents + comparable-tool analyses:
  - [Agent Architecture](research/agent-architecture.md) · [Development Research](research/dev-research.md) · [CLI Tool Architecture](research/cli-architecture.md)
  - [OpenOSINT analysis](research/openosint-analysis.md) — what we matched and what we deliberately do differently (free-first, no Bright Data).
  - [agent-reach analysis](research/agent-reach-analysis.md) — the free cookie-session model for walled social platforms.
