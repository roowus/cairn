# 0005. Reuse pi auth, multi-model switching, allowlisted CLI install

- **Status:** Accepted
- **Date:** 2026-07-27

## Context

Cairn is provider-agnostic, but day-to-day use hit three friction points:

1. Free Z.AI / GLM quotas exhaust; operators already have **xAI Grok** via the
   `pi` coding agent's OAuth login (`~/.pi/agent/auth.json`).
2. Switching models required editing env and restarting the process.
3. `sherlock` / `holehe` failed with "binary not found — install with …", which
   is the opposite of an agentic CLI experience.
4. Running only via `cd repo && uv run cairn` is worse than `pi` / `claude`.

## Decision

1. **`core/pi_auth.py`** reads `~/.pi/agent/auth.json` for xAI (OAuth + refresh)
   and Z.AI (API key). Access tokens are not copied into `.env`.
2. **`reasoning/catalog.py` + `/model` + `Session.switch_model`** provide named
   profiles (`grok`, `glm`, `ollama`, …) switchable mid-session.
3. **`make install-global`** editable-installs the console script to
   `~/.local/bin/cairn` and seeds `~/.cairn/.env`.
4. **`execution/cli_tools.py`** allowlists external CLIs and runs only
   `uv tool install <fixed package>`. Plugins auto-ensure; `/install` and
   `install_cli` expose the same gate. No general shell tool.
5. **Esc / Ctrl-C** cancel the in-flight turn via `interfaces/interrupt.py`
   without exiting the REPL.

## Consequences

- Operators with `pi` already logged into xAI get Grok "for free" credential-wise.
- Free-tier quota exhaustion is a `/model grok` away, not a config archaeology session.
- Adding a new auto-installable CLI requires a code change to the allowlist
  (intentional — keeps the RCE surface closed).
- Global install couples the on-PATH binary to a local checkout when editable;
  re-run `make install-global` on new machines.

## See also

- [Configuration guide](../configuration.md)
- [Discoveries § provider matrix](../discoveries.md#provider-matrix)
- [Security model § allowlisted CLI installs](../architecture/security.md#allowlisted-cli-installs-not-arbitrary-shell)
