# Architecture Overview

Cairn is a terminal-native, LLM-driven OSINT assistant built as a **decoupled
three-layer system**. The defining rule: **the LLM never executes code.** It
plans and emits structured tool calls; deterministic local code runs them and
returns only sanitized summaries.

## Layers

```
reasoning ──▶ orchestration ──▶ execution
 (Layer 1)      (Layer 2)         (Layer 3)
   LLM         validate /         async runners
                memory /          (httpx + create_subprocess_exec)
                audit / graph
                     │
                     ▼
               storage  (SQLite + NetworkX)
```

### Layer 1 — `cairn.reasoning` (the LLM)
A [PydanticAI](https://ai.pydantic.dev) `Agent`. It receives the user's
natural-language investigation and the running context, and emits structured
tool calls. **It has zero access** to shells, sockets, or subprocesses. It only
returns text + tool-call requests, and consumes summaries wrapped in
`<untrusted_external_data>`.

### Layer 2 — `cairn.orchestration` (control + state)
The deterministic controller. It:
- validates tool-call arguments against Pydantic schemas,
- manages conversation memory and the token budget,
- writes every call to the append-only **audit log** (SQLite),
- captures entities into the **graph** (NetworkX),
- intercepts failures and returns structured error frames,
- notifies a **progress observer** (`progress.py`) so the REPL/headless show
  live tool-call status — `▸ name (target)` → `✓/✗ excerpt`.

### Layer 3 — `cairn.execution` (hard-stop runners)
Async Python wrappers around REST APIs and CLI tools. Outputs are parsed and
validated into Pydantic models. Raw payloads are **never** returned to Layer 1;
only condensed Markdown summaries (plus entities mined by `core/entities.py`
from any returned text, so pivoting data is ambient).

## Dependency rule (enforced)

Dependencies flow **downward only**: `reasoning → orchestration → execution`.
There are **no upward imports**, and `reasoning` imports nothing from
`execution`, `orchestration`, `subprocess`, or `socket`. A unit test
(`tests/unit/test_layering.py`) AST-walks the reasoning package and fails if
this invariant is violated.

## Delivery interfaces

All interfaces sit on top of the same plugin registry:

- **Interactive REPL / headless CLI** (`cairn.interfaces.repl`, `.headless`,
  `.plugin_cli`) — built in Phase 1. Global entry point: `make install-global`
  puts `cairn` on `PATH` (`~/.local/bin`). REPL extras: `/model`, Esc-to-cancel
  (`interfaces/interrupt.py`).
- **Config / credentials** — `~/.cairn/.env` + optional pi `auth.json` reuse
  (`core/pi_auth.py`). See [Configuration](../configuration.md).
- **HTTP / social** — browser-like shared client; first-party username probes
  (`username_check`). See [Social probing](../social-probing.md).
- **MCP server** (`cairn.interfaces.mcp`) and **REST/OpenAPI**
  (`cairn.interfaces.api`) — deferred. Because plugins already take a
  `PluginContext` and return Pydantic models, each is a thin adapter over the
  registry (~50 lines), not a rewrite.

## Why this shape

Three independent research documents converge on this design. See
[../research/](../research/). The reasoning: a single LLM-emitted fabrication
in a WHOIS record, open-port list, or breach entry "destroys the utility of the
system." Forcing all ground truth through deterministic tools, and never feeding
raw scraped content straight into the model, makes that failure mode
structurally impossible.

This is the OSINT analogue of Claude Code's "the model can't touch the
filesystem" rule. Cairn generalises it: the model never makes a network request,
runs a subprocess, or sees a raw payload — every capability is a tool. See
[The "Like Claude Code" Model](claude-code-model.md) and
[The Investigator Loop](investigator-loop.md) for how the brain uses those tools.
The full plugin catalogue is in the [Plugin Reference](../plugin-reference.md).
