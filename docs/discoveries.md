# Discoveries — everything we learned building Cairn

A consolidated engineering reference of the non-obvious technical findings,
design decisions, and constraints established across sessions. Source of truth
for "why is it like this."

## Provider matrix

Cairn is provider-agnostic — `reasoning/agent.py` builds the PydanticAI model
from config, with **no default**. `require_llm()` raises with exact guidance if
nothing is set. The REPL `/model` command switches named profiles at runtime
(`reasoning/catalog.py` + `Session.switch_model`).

| Provider | `provider` | `base_url` | `model` | Cost | `/model` name |
|---|---|---|---|---|---|
| **xAI Grok** | `xai` | `https://api.x.ai/v1` | `grok-4.5` / `grok-4.3` | sub / paid | `grok` |
| Anthropic Claude | `anthropic` | — | `claude-sonnet-5` / `claude-opus-4-8` | paid | — |
| OpenAI GPT | `openai` | — | `gpt-4o` | paid | — |
| **Z.AI GLM-5.2** | `openai` | `https://api.z.ai/api/coding/paas/v4` | `glm-5.2` | **free** | `glm` |
| Local Ollama | `openai` | `http://localhost:11434/v1` | `llama3.1` | free | `ollama` |

Credentials for xAI and Z.AI can be left out of `.env`: `core/pi_auth.py`
reads `~/.pi/agent/auth.json` (the same store the `pi` coding agent uses).
xAI subscription auth is OAuth — access tokens are auto-refreshed and written
back to that file. Static `XAI_API_KEY` / `ZAI_API_KEY` also work. Secrets are
never logged or sent to the model context.

> **Ollama caveat:** the agentic loop needs a *tool-capable* model. `llama3.1`,
> `qwen2.5`, `mistral` work; vision models like `llava-phi3` reject tool calls.

Full operator guide (env files, OAuth refresh, `/model`, global install):
**[configuration.md](configuration.md)**.

### pi auth reuse (`core/pi_auth.py`)

Rather than forcing a second secret store, Cairn reads `~/.pi/agent/auth.json`
(overridable via `PI_AUTH_PATH`):

- **Z.AI** — static `zai.key`
- **xAI** — OAuth `access`/`refresh`/`expires`, or static `key`

xAI access tokens are short-lived. On expiry Cairn refreshes against
`https://auth.x.ai/oauth2/token` with the same public client id pi uses, then
atomically rewrites `auth.json` (mode `0600`). Never put the JWT in `.env`.

### Runtime `/model` switch

`reasoning/catalog.py` defines named profiles (`grok`, `glm`, `ollama`, …).
`Session.switch_model` rebuilds the PydanticAI model, assigns
`agent.model`, and updates `audit.model_name`. Tools + history stay put.
In-memory only — persist by editing `~/.cairn/.env`.

### Global CLI install

`make install-global` → `uv tool install --editable .` → `~/.local/bin/cairn`,
and seeds `~/.cairn/.env`. Same ergonomics as `pi` / `claude`: run from any
directory. Editable so checkout edits apply without reinstall.

### Esc / Ctrl-C cancels a turn

`interfaces/interrupt.py` runs the agent coroutine under a cancellable task and
watches the TTY (cbreak) for Esc (`\x1b`) or Ctrl-C (`\x03`). Cancel does **not**
exit the REPL; history is left unchanged for that aborted turn.

### Browser-like fetches + first-party username probes

**Full write-up:** [social-probing.md](social-probing.md).

**Corrected mental model:** Incognito *without login* can still load many
profile pages (e.g. Instagram). The failure mode is not “login required” — it
is (a) bot-shaped HTTP getting an empty JS shell, and (b) Sherlock using
**third-party** `urlProbe` hosts (Instagram → `imginn.com`, X → nitter forks)
that false-negative while the real site works in a browser.

**Fix in code:**

| Piece | Role |
|---|---|
| `execution/browser_http.py` | Chrome navigation headers, HTTP/2, retries on empty shells / 429 |
| `runner.build_context` | Shared client is browser-like (not `cairn/0.1` UA) |
| `execution/social_probe.py` | First-party probes → `found` / `not_found` / `unknown` / `error` |
| `username_check` plugin | Preferred tool for IG/GitHub/Reddit/YT/TikTok/X/Threads |
| `sherlock` plugin | 300+ sweep, then first-party cross-check; drops imginn/nitter URLs |

**Statuses:** `unknown` ≠ `not_found`. An empty shell means retry/browser, not
“account missing.”

**“Look like a human” tiers:** (A) browser-like HTTP ✅ · (B) your browser
cookies (agent-reach) 🟡 · (C) Playwright 🟡. Not proxy farms.

### GitHub profile email is often a lie by omission

`GET /users/{login}` frequently returns `"email": null` even when **public
commits** carry `From: name <real@gmail.com>` (including on `gh-pages`). The
`github` plugin therefore mines recent commits (default + pages branches),
ranks personal emails above `users.noreply.github.com`, pulls YouTube embeds
from README/`index.md`, and emits avatar/`image_url` entities. Unauthenticated
GitHub is 60/hr — set `CAIRN_GITHUB_KEY` for deep mining (5k/hr).

### Long CLI tools need their own timeouts

`ctx.timeout` defaults to **30s** (HTTP). Sherlock full scans need **~240s**;
holehe **~180s**. Early bug: process budget was `max(ctx.timeout, site_timeout)`
→ 30s kill, mislabeled as “auto-install failed.” Fixed: independent
`overall_timeout` fields + accurate error strings. Holehe flag is
`--only-used` (not `--only-known`).

### Self-installing external CLIs (allowlist only)

`sherlock` / `holehe` used to print “install with `uv tool install …`” and stop.
That fights the point of an agentic CLI. Now:

- `execution/cli_tools.py` holds a **fixed allowlist** (`sherlock-project`,
  `holehe`) and runs only `uv tool install <that package>` via the safe
  subprocess runner (array args, no shell).
- Plugins call `run_cli_tool(..., auto_install=True)` so first use installs.
- Brain tool `install_cli` + REPL `/install` for explicit control.
- Unknown names (`nmap`, arbitrary PyPI) are rejected.

This is *not* arbitrary code execution for the model — it is a capability gate
over a two-row table.

## PydanticAI patterns (the framework layer)

Cairn uses **PydanticAI** (not the raw Anthropic SDK). Key patterns verified by
introspection + `TestModel`:

- **`Agent(model, system_prompt=…, output_type=str, retries=2)`** — one agent
  per session (`orchestration/session.py`).
- **`agent.tool_plain(fn)`** — register a plain (non-dependency) tool. Each
  plugin is wrapped into one by `tool_adapter.register_tools`.
- **Dynamic tool schemas via signature injection** — plugins don't write a
  function signature by hand; `_apply_signature` builds an
  `inspect.Signature` from the `PluginInput` Pydantic fields so PydanticAI
  derives the JSON schema automatically. One pattern serves every plugin.
- **`agent.run(prompt, message_history=…)`** for multi-turn; `res.all_messages()`
  feeds the next turn's `message_history`.
- **`TestModel`** for deterministic unit tests: `call_tools=[…]` +
  `custom_output_text` to drive the agent without a real LLM.

## The progress tap (live status)

Live "what's happening" output (replacing the dead spinner) is an **observer
only**, never influencing execution:

- `orchestration/progress.py` defines `Progress` (hooks: `on_turn_start`,
  `on_tool_start`, `on_tool_end`, `on_turn_end`) + `NullProgress` default.
- The **single source of truth** is the tool closure in `tool_adapter` — it
  calls `on_tool_start`/`on_tool_end` with the same `status`/`target`/`summary`
  that get written to the audit log.
- Interfaces subclass it: `RichProgress` (REPL) and `HeadlessProgress` update a
  `console.status` spinner as tools run — `▸ name (target)` → `✓/✗ excerpt`.
- Hooks are synchronous (run on the loop thread) so Rich rendering is safe.

This deliberately avoids parsing PydanticAI's streaming events (fragile); the
closure tap is robust and already wired to audit.

## Usage & cost reporting

The cost/quota analogue of the progress tap — an **accountant only**, never
influencing execution. Because the brain can reach for daily-quota'd and
credit-metered sources, every call is timed and its consumption accounted, then
surfaced as **credits used, time taken, and rate/quota**.

- **`CostSpec`** (frozen dataclass, `cost` ClassVar on `BasePlugin`): unit,
  per-call cost, daily/monthly quota, paid flag. Free plugins inherit the
  default and declare nothing; override on metered sources (hackertarget 50/day,
  Brave 2k/mo, shodan 1 credit/lookup, etc.).
- **`PluginOutput`** carries optional dynamic signals (`rate_limit_remaining`,
  `rate_limit_reset`, `quota_remaining`, `credits_remaining`) read from a
  response — GitHub's `X-RateLimit-*` headers, hackertarget's exhausted body.
- **`UsageTracker`** (orchestration) accumulates per-source calls/time/consumed
  across a session; the tool closure (single source of truth) times each call
  with `time.perf_counter()` and feeds it. `checkpoint()`/`delta()` give true
  per-turn deltas for the REPL summary line.
- **Persisted per-call**: the audit log gained `elapsed_ms` + `usage_json`
  columns (forward-only migration `0002`; `db._ensure_columns` back-fills legacy
  DBs at runtime). `aggregate_history(db)` reconstructs totals → `cairn usage`.
- **Per-call invariant:** the snapshot stores the *per-call delta*
  (`CostSpec.per_call`), **not** the running total — otherwise aggregating rows
  sums cumulative totals and over-counts. Regression-tested in
  `tests/unit/test_usage.py`.
- **No USD guessing:** the report measures in each service's native unit
  (credits, lookups/day, queries/mo, calls/hr); `paid?` flags money-drawing
  sources. See [usage & cost](architecture/usage-and-cost.md).

## Free-first strategy

**Default to fully-free, no-key sources.** Keyed plugins are *optional
accelerators* (free-tier-with-key: Brave, Shodan, VT, Censys, AbuseIPDB, HIBP),
not requirements.

| Need | Free default | Optional keyed upgrade |
|---|---|---|
| Web search | DuckDuckGo (no key) — **but anti-bot blocks it (2026)**; see below | Brave (`CAIRN_BRAVE_KEY`) — the reliable path |
| Scrape page | httpx + BeautifulSoup | crawl4ai (JS) / Jina Reader |
| IP intel | shodan_internetdb, urlscan | shodan_full, censys, abuseipdb |
| IP intel (daily-quota'd) | hackertarget ~50/day — **off by default** | `CAIRN_ALLOW_DAILY_LIMITED=1` to opt in |
| Breach intel | — (none free) | hibp |
| GitHub | 60/hr no key | `CAIRN_GITHUB_KEY` → 5k/hr |

**Web search reality (2026):** free no-key search is blocked by anti-bot on
DuckDuckGo / Google / Bing (all return a 202 interstitial), SearXNG public
instances are unreliable, and Jina *Search* now requires a key. So `web_search`
detects the DDG block and returns an **actionable** message pointing to a free
Brave key — never a silent failure or fabricated hits. Jina *Reader*
(`r.jina.ai`) is still free no-key for *page* scraping.

### Daily-quota gating

Some free sources have a hard per-DAY quota (not just rate-limiting) — currently
`hackertarget` (~50/day). These are `daily_limited=True` and are **excluded from
the brain's tool list by default** (`CAIRN_ALLOW_DAILY_LIMITED=0`). The user opts
in with `CAIRN_ALLOW_DAILY_LIMITED=1`. Pure rate-limited sources (shodan
internetdb, urlscan, crtsh, github 60/hr, rdap, wayback, dns) stay on — a rate
limit is acceptable; a daily *quota* is not, by default. `cairn plugins` shows
each plugin's tier and status (active / hidden + reason).

### Avoid-paid-platforms directive (user feedback)

**No fundamentally-paid services:** Bright Data (Web Unlocker / SERP), SerpAPI,
TinEye, facecheck, or any platform whose useful tier costs money. This is why
OpenOSINT's Bright Data backbone was rejected and replaced with the free-first
table above, and why walled social platforms are approached via the
[agent-reach cookie model](research/agent-reach-analysis.md) instead of a paid
unlocker.

## The hard-stop / anti-hallucination model

The defining safety property, generalised from Claude Code's "the model can't
touch the filesystem":

- **Layer 1 (`reasoning/`) has no shell/socket/subprocess access** — AST-tested
  by `tests/unit/test_layering.py`.
- **The model never sees raw payloads.** Every tool result is a Markdown summary
  wrapped in `<untrusted_external_data source=… target=…>…</untrusted_external_data>`
  (`core/security.wrap_untrusted`). The system prompt marks that content
  *passive observation only* — data, never instruction (defence against
  prompt-injection in scraped/WHOIS text).
- **Subprocesses use `create_subprocess_exec(*args)`** (array args, no shell) —
  defence against command injection in `holehe`/`sherlock` wrappers.
- **Every tool call is audited** (append-only SQLite: tool, target, params,
  status, error, model, result_size, ts).

Net effect: a fabricated port/hostname/breach is *structurally impossible* at
the execution layer — it can only originate from a real, audited tool call.

## Entity extraction (the pivot fuel)

`core/entities.py` — pure stdlib regex extractor (`email`, `url`, `ip`
(validated), `crypto_btc`, `crypto_eth`, `phone`, `domain` (bare only, not part
of an email/url)). Runs *inside* `scrape_url`/`web_search` before they return,
so entities are ambient — the brain doesn't spend a turn extracting. The
`tool_adapter` pushes them into the NetworkX graph automatically.

## Config & secrets (and the env-leak lesson)

`core/config.py` (pydantic-settings, prefix `CAIRN_`, nested `__`):

- Precedence (high→low): real env vars > `~/.cairn/.env` > `./.env` >
  `~/.cairn/config.toml`.
- `load_settings(config_dir=…, project_env_file=".env")` — the
  `project_env_file` param lets tests opt out of the cwd `.env` (production
  convenience) via `project_env_file=None`.
- **Lesson learned:** `CAIRN_LLM__*` vars exported in the developer shell leak
  into pytest via the env-settings source. The fix is an autouse fixture
  (`tests/conftest.py::_clean_llm_env`) that strips them per-test; tests set
  their own provider explicitly. This is why "provider is unset" tests must
  clear *all* `CAIRN_LLM__*` keys, not just `PROVIDER`.
- Plugin keys map logical name → Settings field via `_KEY_FIELDS`
  (`shodan`→`shodan_key`, …, `github`→`github_key`, `urlscan`→`urlscan_key`).

## Verified state (as of this writing)

- **22+ plugins** including `username_check`, `install_cli`, identity/infra/web/paid.
- Unit suite: config, pi-auth, model catalog, build_model, cli_tools, interrupt,
  browser_http, social_probe, github commit mining, tool adapter, layering, …
- Global install: `make install-global` → `cairn` on `PATH`.
- Default LLM: xAI Grok via pi OAuth; `/model glm` for Z.AI.
- Live checks: first-party Instagram/GitHub/Threads for real handles; GitHub
  commit email + YT embed mining; Sherlock imginn false-negative understood.
- External CLIs auto-install; long CLI timeouts fixed (240s / 180s).
- Docs: [configuration.md](configuration.md), [social-probing.md](social-probing.md).
