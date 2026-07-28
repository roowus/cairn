# Configuration, install & model switching

This is the full operator guide for getting Cairn onto your `PATH`, wiring LLM
credentials (including reusing the `pi` coding-agent auth store), and switching
models at runtime with `/model`.

Related code:

| Concern | Module |
|---|---|
| Settings load / precedence | `src/cairn/core/config.py` |
| Paths (`~/.cairn`, override) | `src/cairn/core/paths.py` |
| pi `auth.json` + xAI OAuth refresh | `src/cairn/core/pi_auth.py` |
| Model construction | `src/cairn/reasoning/agent.py` |
| Named profiles (`/model`) | `src/cairn/reasoning/catalog.py` |
| Live switch | `Session.switch_model` in `src/cairn/orchestration/session.py` |
| REPL commands | `src/cairn/interfaces/repl.py` (`/model`, …) |
| Esc / Ctrl-C cancel | `src/cairn/interfaces/interrupt.py` |
| Allowlisted CLI auto-install | `src/cairn/execution/cli_tools.py` + `plugins/identity/install_cli.py` |
| Browser-like HTTP + social probes | `execution/browser_http.py`, `social_probe.py`, `username_check` |
| Global install | `Makefile` target `install-global` |

Social / Sherlock / incognito lessons: **[social-probing.md](social-probing.md)**.

Engineering notes / lessons: [Discoveries](discoveries.md).

---

## 1. Global install (`cairn` works from any directory)

Cairn is a Python package with a console script entry point:

```toml
# pyproject.toml
[project.scripts]
cairn = "cairn.cli:main"
```

### Recommended: editable tool install (like `pi` / `claude`)

From the repo checkout:

```bash
cd ~/projects/cairn          # or wherever you cloned
uv sync --extra dev          # project .venv for tests/dev
cp .env.example .env         # optional project-local env while developing
make install-global
```

What `make install-global` does:

1. **`uv tool install --editable --force .`**
   - Builds/installs Cairn into uv's tool environment
     (`~/.local/share/uv/tools/cairn/`).
   - Symlinks the `cairn` executable to **`~/.local/bin/cairn`**
     (same directory as `claude` on a typical Mac setup).
   - **Editable**: the tool points at your checkout. Edits under
     `src/cairn/` are picked up on the next process start — no reinstall
     needed for normal code changes.
2. **Seeds `~/.cairn/.env`**
   - Copies `./.env` → `~/.cairn/.env` (mode `600`) if a project `.env` exists.
   - Else, if `~/.cairn/.env` is missing, copies `.env.example` there.
   - This is what makes config work **when you are not in the repo directory**.

### PATH requirement

`~/.local/bin` must be on your `PATH`. It already is if you use:

- Homebrew + uv defaults
- Claude Code's installer
- A normal `~/.zshrc` that includes `$HOME/.local/bin`

Check:

```bash
which cairn          # expect: /Users/<you>/.local/bin/cairn
cairn --version      # expect: cairn 0.1.0
cairn plugins        # works from /tmp, ~, anywhere
```

### Equivalent manual install

```bash
uv tool install --editable --force /path/to/cairn
mkdir -p ~/.cairn
cp /path/to/cairn/.env ~/.cairn/.env && chmod 600 ~/.cairn/.env
```

### Uninstall / reinstall

```bash
uv tool uninstall cairn
# reinstall after major dependency changes:
cd /path/to/cairn && make install-global
```

### Why not only `uv run cairn`?

| Invocation | Works from any cwd? | Needs repo checkout? | Typical use |
|---|---|---|---|
| `uv run cairn` | only if you `cd` into the project first | yes | local dev / CI |
| `cairn` after `make install-global` | **yes** | only for editable source updates | daily driver |
| `python -m cairn` inside the tool venv | yes | no | debugging |

### Data directory vs install directory

These are separate:

| Path | Purpose |
|---|---|
| Checkout, e.g. `~/projects/cairn` | Source (editable install target) |
| `~/.local/bin/cairn` | CLI shim on `PATH` |
| `~/.local/share/uv/tools/cairn/` | Isolated tool virtualenv + deps |
| **`~/.cairn/`** | **Runtime data + user config** (db, env, skills, toml) |

Override the runtime data dir (tests do this):

```bash
export CAIRN_CONFIG_DIR=/tmp/cairn-scratch
cairn
```

---

## 2. Config file locations & precedence

`load_settings()` (`core/config.py`) builds a pydantic-settings object with:

**Priority high → low:**

1. **Process environment variables** (`CAIRN_*`, nested with `__`)
2. **`~/.cairn/.env`** (or `$CAIRN_CONFIG_DIR/.env`)
3. **`./.env`** (current working directory — convenient in the repo)
4. **`~/.cairn/config.toml`** (or `$CAIRN_CONFIG_DIR/config.toml`)

### Environment variable shape

Nested LLM fields use double-underscore:

```bash
export CAIRN_LLM__PROVIDER=xai
export CAIRN_LLM__MODEL=grok-4.5
export CAIRN_LLM__API_KEY=...          # optional for xAI/Z.AI if pi auth exists
export CAIRN_LLM__BASE_URL=...        # only for custom OpenAI-compatible gateways
export CAIRN_LOG_LEVEL=INFO
export CAIRN_ALLOW_DAILY_LIMITED=0
export CAIRN_BRAVE_KEY=...            # optional plugin keys
```

### TOML shape

```toml
# ~/.cairn/config.toml
[llm]
provider = "xai"
model = "grok-4.5"
# api_key = "..."   # prefer env / pi auth over committing secrets here
# base_url = "https://api.x.ai/v1"
```

### What lives under `~/.cairn/`

| File / dir | Role |
|---|---|
| `.env` | Primary user config when running from any directory |
| `config.toml` | Optional TOML alternative / partial overrides |
| `cairn.db` | SQLite audit log (+ future durable state) |
| `skills/` | User investigation playbooks (override built-ins by name) |
| `history/` | Reserved for session history exports |

### There is no hard-coded default provider

If nothing configures an LLM, `require_llm()` raises with copy-pasteable
export examples (xAI, Anthropic, Ollama). The *suggested* free/paid options
live in `.env.example` and the profile catalog — not as silent code defaults.

---

## 3. LLM providers

`build_model(settings)` in `reasoning/agent.py` constructs a PydanticAI model.
Supported routes:

| `CAIRN_LLM__PROVIDER` | How it is built | Default model if unset | Notes |
|---|---|---|---|
| `xai` or `grok` | `OpenAIChatModel` → `https://api.x.ai/v1` | `grok-4.5` | Also detected if `model` starts with `grok` or `base_url` contains `api.x.ai` |
| `anthropic` | `AnthropicModel` | `claude-sonnet-5` | Also detected if `model` contains `claude` |
| `openai` | `OpenAIChatModel` | `gpt-4o-mini` (cloud) or `llama3.1` (if `base_url` set) | Covers OpenAI, Z.AI, Ollama, any OpenAI-compatible gateway |
| `ollama` | same as openai + local base_url conventions | `llama3.1` | Placeholder key `ollama` is fine |

### Provider matrix (operational)

| Profile name (`/model`) | provider | base_url | model id | Cost | Credential source |
|---|---|---|---|---|---|
| `grok` | `xai` | `https://api.x.ai/v1` | `grok-4.5` | Grok/X sub or API | pi OAuth / `XAI_API_KEY` / `CAIRN_LLM__API_KEY` |
| `grok-4.3` | `xai` | `https://api.x.ai/v1` | `grok-4.3` | same | same |
| `glm` | `openai` | `https://api.z.ai/api/coding/paas/v4` | `glm-5.2` | free coding plan | pi `zai.key` / `ZAI_API_KEY` / `CAIRN_LLM__API_KEY` |
| `glm-5.1` | `openai` | Z.AI URL above | `glm-5.1` | free | same |
| `ollama` | `openai` | `http://localhost:11434/v1` | `llama3.1` | local | placeholder `ollama` |
| *(env only)* | `anthropic` | — | e.g. `claude-sonnet-5` | paid | `CAIRN_LLM__API_KEY` |
| *(env only)* | `openai` | — | e.g. `gpt-4o` | paid | `CAIRN_LLM__API_KEY` |

Aliases accepted by `/model` / `find_profile()`:

| You type | Resolves to |
|---|---|
| `grok`, `grok-4.5`, `xai`, `grok4.5` | profile `grok` |
| `grok-4.3`, `grok4.3` | profile `grok-4.3` |
| `glm`, `glm-5.2`, `zai`, `glm5.2` | profile `glm` |
| `glm-5.1`, `glm5.1` | profile `glm-5.1` |
| `ollama`, `local`, `llama3.1` | profile `ollama` |

### Tool-capable models only

The agentic loop **requires tool/function calling**. Verified workable families:

- xAI Grok (`grok-4.5`, `grok-4.3`) via OpenAI-compatible chat completions
- Z.AI GLM (`glm-5.2`, …)
- OpenAI GPT-4o class
- Anthropic Claude
- Local: `llama3.1`, `qwen2.5`, `mistral`, `llama3.2`

**Not suitable:** vision-only or non-tool models (e.g. `llava-phi3`) — they
reject tool calls and the REPL will error mid-turn.

### Example `.env` snippets

**A — xAI Grok (recommended when using `pi` subscription login)**

```bash
CAIRN_LLM__PROVIDER=xai
CAIRN_LLM__MODEL=grok-4.5
# leave API key unset → pi_auth pulls/refreshes OAuth access token
```

**B — Z.AI GLM free**

```bash
CAIRN_LLM__PROVIDER=openai
CAIRN_LLM__BASE_URL=https://api.z.ai/api/coding/paas/v4
CAIRN_LLM__MODEL=glm-5.2
# CAIRN_LLM__API_KEY=...   # or rely on ~/.pi/agent/auth.json zai.key
```

**C — Anthropic**

```bash
CAIRN_LLM__PROVIDER=anthropic
CAIRN_LLM__MODEL=claude-sonnet-5
CAIRN_LLM__API_KEY=sk-ant-...
```

**D — Local Ollama**

```bash
bash scripts/bootstrap_ollama.sh   # one-time model pull
CAIRN_LLM__PROVIDER=openai
CAIRN_LLM__MODEL=llama3.1
CAIRN_LLM__BASE_URL=http://localhost:11434/v1
CAIRN_LLM__API_KEY=ollama
```

---

## 4. Reusing `pi` credentials (`core/pi_auth.py`)

If you already use the [pi coding agent](https://github.com/earendil-works/pi-coding-agent)
(or compatible), Cairn can reuse its auth file so you do **not** paste tokens
into `.env`.

### Auth file location

Default: **`~/.pi/agent/auth.json`**

Override for tests or custom layouts:

```bash
export PI_AUTH_PATH=/path/to/auth.json
```

### Expected shape (secrets redacted)

```json
{
  "zai": {
    "type": "api_key",
    "key": "<Z.AI coding-plan key>"
  },
  "xai": {
    "type": "oauth",
    "access": "<JWT access token>",
    "refresh": "<refresh token>",
    "expires": 1785195107202
  }
}
```

xAI may also be stored as a static API key:

```json
{
  "xai": {
    "type": "api_key",
    "key": "xai-..."
  }
}
```

### How login is obtained (outside Cairn)

In `pi` interactive mode:

```text
/login xai
```

Choose **Use a subscription** (device-code OAuth for SuperGrok / X Premium) or
**Use an API key**. Tokens land in `auth.json`. Cairn never implements the
device-code browser flow itself — it only **reads and refreshes**.

### Credential resolution order

When building or switching to a profile:

**xAI / Grok (`auth="xai"`)**

1. `settings.llm.api_key` **if** the active settings already match this profile
   (avoids sending a Z.AI key to xAI after `/model` switch)
2. `XAI_API_KEY` or `CAIRN_XAI_KEY` env
3. `get_xai_api_key()` from pi auth:
   - static `key` if present
   - else OAuth `access`, refreshing when `expires` is reached

**Z.AI / GLM (`auth="zai"`)**

1. Matching `settings.llm.api_key` (same match rule)
2. `ZAI_API_KEY` or `CAIRN_ZAI_KEY` env
3. `get_zai_api_key()` → `auth.json` → `zai.key`

**Ollama**

- No real secret; placeholder `ollama` is injected when needed.

### xAI OAuth refresh (detail)

pi stores `expires` already skewed ~5 minutes early. When
`time.time()*1000 >= expires`, Cairn:

1. `POST https://auth.x.ai/oauth2/token` with
   `grant_type=refresh_token`,
   `client_id=b1a00492-073a-47ea-816f-4c329264a828` (same public client id pi uses),
   and the stored refresh token.
2. Parses `access_token` / optional rotated `refresh_token` / `expires_in`.
3. Writes the updated `xai` blob back to `auth.json` (mode `600`, atomic
   replace via `.tmp`).
4. On refresh failure: logs a warning and **falls back to the existing access
   token** (may still work until the provider hard-rejects it).

**Why not copy the access JWT into `.env`?**  
Access tokens expire (on the order of an hour). Putting them in `.env` guarantees
stale credentials. Leaving `CAIRN_LLM__API_KEY` empty and reading pi auth keeps
refresh working for both `pi` and `cairn`.

### Security properties

- Secrets are `SecretStr` in settings; `settings_source_summary()` only exposes
  `has_api_key: bool`.
- Audit log params are redacted (`core/security.redact_secrets`).
- Keys are **never** placed in the model context or system prompt.
- pi auth file permissions: written as `0600`.

---

## 5. Runtime model switching (`/model`)

### User-facing REPL

```text
cairn> /model
┌ Models (current: grok-4.5) ─────────────────────────┐
│   name       model id    creds   description         │
│ ★ grok       grok-4.5    ✓       xAI Grok 4.5 …      │
│   grok-4.3   grok-4.3    ✓       …                   │
│   glm        glm-5.2     ✓       Z.AI GLM-5.2 …      │
│   glm-5.1    glm-5.1     ✓       …                   │
│   ollama     llama3.1    ✓       Local Ollama …      │
└──────────────────────────────────────────────────────┘
Switch with /model <name>  e.g. /model grok

cairn> /model glm
Model → glm-5.2

cairn> /model grok
Model → grok-4.5
```

Legend:

- **★** — best-effort current profile (`current_profile_name`)
- **✓** — `profile_available` found a credential (or Ollama placeholder)
- **—** — no credential; switching will error with setup hints

Also listed in `/help`.

### What `Session.switch_model(name)` does

1. `find_profile(name)` — case-insensitive name/alias lookup; unknown →
   `ConfigError`.
2. `apply_profile(settings, profile)` — mutates `settings.llm`
   (`provider`, `model`, `base_url`, resolved `api_key`).
3. `build_model(settings)` — new PydanticAI model instance.
4. Assigns `session.model` and **`session.agent.model`** (tools stay registered;
   conversation `history` is preserved).
5. Updates `session.audit.model_name` so subsequent audit rows tag the new model.

`tool_adapter` records `audit.model_name` live on each tool call (not a stale
closure capture from session start), so `/model` mid-investigation is reflected
in the audit trail.

### Persistence

`/model` changes the **in-memory session only**. Restarting `cairn` reloads
from env/toml. To make a switch permanent, edit `~/.cairn/.env` (or export
vars in your shell profile):

```bash
# permanent default = Grok
CAIRN_LLM__PROVIDER=xai
CAIRN_LLM__MODEL=grok-4.5
```

### When to switch

| Situation | Action |
|---|---|
| Z.AI / GLM daily quota hit | `/model grok` |
| Want free local offline | `/model ollama` (Ollama must be running) |
| Need a different Grok SKU | `/model grok-4.3` |
| Back to free cloud GLM | `/model glm` |

---

## 6. Optional OSINT source keys

These are independent of the LLM. A keyed plugin activates when its env var is
non-empty (`Settings.plugin_keys()`).

| Variable | Plugin(s) | Notes |
|---|---|---|
| `CAIRN_SHODAN_KEY` | `shodan_full` | Free tier with key |
| `CAIRN_VIRUSTOTAL_KEY` | `virustotal` | |
| `CAIRN_CENSYS_KEY` | `censys` | |
| `CAIRN_ABUSEIPDB_KEY` | `abuseipdb` | |
| `CAIRN_HIBP_KEY` | `hibp` | |
| `CAIRN_BRAVE_KEY` | `web_search` (reliable path) | Free 2k queries/mo — **strongly recommended** |
| `CAIRN_EXA_KEY` | reserved / future | |
| `CAIRN_GITHUB_KEY` | `github` | Optional: 60/hr → 5,000/hr |
| `CAIRN_URLSCAN_KEY` | `urlscan` | Optional rate-limit boost |

Misc:

| Variable | Default | Meaning |
|---|---|---|
| `CAIRN_LOG_LEVEL` | `INFO` | Logging verbosity |
| `CAIRN_ALLOW_DAILY_LIMITED` | `0` / false | Opt in daily-quota free sources (e.g. hackertarget) |
| `CAIRN_CONFIG_DIR` | `~/.cairn` | Runtime data directory |
| `PI_AUTH_PATH` | `~/.pi/agent/auth.json` | Override pi auth file |

---

## 7. CLI surface (after global install)

```bash
cairn                     # interactive REPL (default)
cairn repl                # same
cairn search <question>   # one-shot agentic query
cairn plugins             # list plugins + tier + brain status
cairn plugin <name> …     # run a plugin directly (no LLM required)
cairn --version
```

### REPL slash commands

| Command | Action |
|---|---|
| `/help` | Show help |
| `/model` | List LLM profiles |
| `/model NAME` | Switch profile (`grok`, `glm`, …) |
| `/plugins` | List OSINT tools |
| `/skills` | List investigation playbooks |
| `/<skill> TARGET` | Run a playbook (e.g. `/domain-recon example.com`) |
| `/graph` | Show captured entities |
| `/audit [N]` | Last N audited tool calls |
| `/reset` | Clear conversation history |
| `/quit` | Exit |

Anything else is sent to the analyst agent as natural language.

### Stop a running turn (Esc / Ctrl-C)

While the agent is thinking or calling tools, press **Esc** or **Ctrl-C** to
cancel *that turn only* — you stay in the REPL. Implementation:
`interfaces/interrupt.py` (`run_cancellable`) watches the TTY in cbreak mode and
cancels the asyncio task; `Session.ask` re-raises `CancelledError` without
committing a half-written history entry. Ctrl-D or `/quit` still exits the REPL.

### Self-installing external CLIs (you do nothing)

Some plugins wrap third-party binaries (`sherlock`, `holehe`). **You never need
to run an install command.** Cairn provisions them itself:

1. **On REPL startup** — any missing allowlisted CLI is installed automatically
   (`ensure_missing_cli_tools`). You'll see a one-line status if something was
   missing; silence means everything was already present.
2. **On first tool use** — `sherlock` / `holehe` call `run_cli_tool(...,
   auto_install=True)` as a safety net if startup was skipped (headless, etc.).
3. **Brain tool (optional)** — `install_cli(target='list'|'all'|name)` for
   status/repair only. The system prompt forbids asking the user to install.

**Security boundary:** only packages in the allowlist
(`execution/cli_tools.py::_TOOLS`) can ever be installed. The model cannot pass
an arbitrary package name or shell string. Requires `uv` on `PATH`; new shims
land in `~/.local/bin` (also searched explicitly after install).

| Logical name | Binary | `uv tool install` package |
|---|---|---|
| `sherlock` | `sherlock` | `sherlock-project` |
| `holehe` | `holehe` | `holehe` |

---

## 8. End-to-end setup checklist

```bash
# 1. Clone & deps
git clone <repo> ~/projects/cairn && cd ~/projects/cairn
uv sync --extra dev

# 2. LLM credentials
#    Option A: already use pi with xAI → nothing to paste
pi    # /login xai if needed, then quit
#    Option B: put a key in .env (see §3)

cp .env.example .env
# edit if you want a non-Grok default

# 3. Global command + user config dir
make install-global

# 4. Optional but recommended for web search
# export CAIRN_BRAVE_KEY=...   # also fine inside ~/.cairn/.env

# 5. Smoke
cairn --version
cairn plugins
cairn plugin shodan-internetdb 8.8.8.8
cairn
# inside REPL:
#   /model
#   /model grok
#   look up 8.8.8.8 on shodan internetdb
```

### Verify Grok auth without the full REPL

```bash
python - <<'PY'
from cairn.core.config import load_settings
from cairn.reasoning.agent import build_model
from cairn.reasoning.catalog import list_profiles
s = load_settings()
print(s.llm.provider, s.llm.model)
for p, ok in list_profiles(s):
    print(f"{p.name:10} available={ok}")
m = build_model(s)
print("built", getattr(m, "model_name", m))
PY
```

---

## 9. Tests covering this surface

| File | Covers |
|---|---|
| `tests/unit/test_config.py` | env/toml load, empty provider, key mapping |
| `tests/unit/test_pi_auth.py` | zai key, xai static, oauth fresh, refresh + persist, refresh failure fallback |
| `tests/unit/test_model_catalog.py` | aliases, availability, apply_profile errors, `Session.switch_model` |
| `tests/unit/test_build_model.py` | xai/anthropic routing, missing xai key, pi-auth injection |
| `tests/unit/test_cli_tools.py` | allowlist, auto-install via mocked `uv`, plugin `install_cli` |
| `tests/unit/test_interrupt.py` | cancellable turn helper |
| `tests/conftest.py` | strips host `CAIRN_LLM__*` so developer shell keys don't leak into pytest |

```bash
make test
# or:
uv run pytest tests/unit/test_pi_auth.py tests/unit/test_model_catalog.py \
              tests/unit/test_build_model.py tests/unit/test_config.py -q
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `command not found: cairn` | not installed or `~/.local/bin` off PATH | `make install-global`; ensure PATH |
| `No LLM provider configured` | empty env + no toml | set `CAIRN_LLM__PROVIDER` / copy `.env` to `~/.cairn/.env` |
| `xAI/Grok is selected but no credential` | no pi auth, no `XAI_API_KEY` | `pi` → `/login xai`, or set a key |
| GLM quota / 429 from Z.AI | free plan exhausted | `/model grok` |
| Works in repo, fails elsewhere | only `./.env` configured | `cp .env ~/.cairn/.env` or `make install-global` |
| Stale Grok auth after long idle | refresh token revoked | re-run `pi` `/login xai` |
| Ollama tool errors | non-tool model | use `llama3.1` / `qwen2.5`, not `llava-*` |
| `/model foo` → Unknown model | not in catalog | `/model` to list; custom providers stay env-only |
| `sherlock unavailable` / install fails | no `uv`, or `~/.local/bin` off PATH | install uv; ensure `~/.local/bin` on PATH |
| Sherlock misses Instagram but incognito works | old third-party probe / use majors tool | use **`username_check`**; Sherlock now cross-checks first-party too — see [social-probing.md](social-probing.md) |
| GitHub finds no email | profile field null; or 60/hr rate limit | commit mining needs quota — set `CAIRN_GITHUB_KEY`; re-run `github` |
| Sherlock/holehe “timed out after 30s” | outdated build | overall timeouts are 240s/180s now; update checkout |
| Esc does nothing | non-TTY / piped stdin | use Ctrl-C; Esc needs an interactive TTY |
| Tests randomly see your real provider | missing env strip | ensured by `tests/conftest.py::_clean_llm_env` |

---

## 11. Design rationale (short)

1. **Provider-agnostic brain** — OpenOSINT is Anthropic-locked; Cairn builds the
   model from config so Grok, GLM, Claude, GPT, and Ollama share one agent loop.
2. **Don't fork credentials** — developers already logged into `pi` should not
   maintain a second secret store; OAuth refresh must stay shared.
3. **Switch without restart** — quota exhaustion mid-investigation is common on
   free tiers; `/model` keeps history and tools, only swaps the LLM endpoint.
4. **Global CLI** — OSINT investigations are not "only inside the monorepo";
   `cairn` belongs next to `pi` and `claude` on `PATH`, with config in `~/.cairn`.
5. **Self-sufficient tooling** — missing OSINT CLIs should install themselves
   from an allowlist (`uv tool install`), not dump the user out to Stack Overflow.
6. **Interruptible turns** — long agent loops must be stoppable with Esc without
   killing the whole REPL (Claude Code muscle memory).
