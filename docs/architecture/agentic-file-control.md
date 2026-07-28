# Agentic file & tool control

Cairn's defining property is the **anti-injection hard-stop**: the model never
executes code, makes network requests, or sees raw external payloads — every
tool result flows back wrapped in `<untrusted_external_data>`. Until recently
that came at the cost of a hard ceiling: the brain could call curated OSINT
lookups but **could not touch files** — no read, no write, no download, no
shell, no install. That blocks the next goal — **solving OSINT challenges**
(file forensics, pcap triage, document extraction, steganography) — which need
exactly the "Claude Code level control of files" the project asked for.

This doc covers how agentic file/tool control is added **without weakening the
hard-stop**. The reconciliation is the load-bearing idea below.

## The two-layer model (the load-bearing invariant)

Two independent layers; relaxing one does **not** relax the other:

- **Layer A — execution permission (RELAXED, by design).** The brain's
  *decision* to read / write / run / download is **auto-allowed when the target
  resolves inside the workspace** (cwd + scratch dir). No per-command prompt.
  Only **installs** and **outside-workspace** ops are gated (v1: denied by
  default).
- **Layer B — anti-injection (PRESERVED, unchanged).** The *results* of every
  agentic tool still flow back to the model wrapped in
  `<untrusted_external_data>` via `wrap_untrusted` (`src/cairn/core/security.py`).
  Wrapping is **structural** — done by the audited `_tool` closure at
  `src/cairn/orchestration/tool_adapter.py`, which every agentic tool routes
  through automatically because **agentic tools are `BasePlugin` subclasses**,
  not a separate `agent.tool` toolset.

Making the agentic tools ordinary plugins is what makes wrap-back impossible to
forget: they ride the same closure that already wraps every OSINT plugin
(`test_tool_result_is_wrapped` proves it structurally;
`tests/plugins/test_agentic.py::test_read_file_runs_through_wrapping_closure`
proves it for `read_file` end-to-end).

## Honesty about containment

"Auto-allow in sandbox" in v1 is a **policy / intent boundary, not OS-enforced
containment.** Arbitrary shell via `run_command` *can* escape the workspace (a
symlink, `cp ~/`, `curl | sh`). We never claim airtight containment. The
defenses that *do* hold:

- **Boundary check** on the structured file ops (`read_file`, `write_file`,
  `download_url`'s `dest`, `list_files`) — `Path.resolve(strict=False)`
  collapses `..` and follows symlinks, so a `../../etc/passwd` target or a
  symlink pointing outside resolves outside the roots and is denied.
- **Secret scrubbing** before exec — `scrub_env` strips `CAIRN_*` and any
  secret-shaped env var before the subprocess sees its environment.
- **Result wrapping** — even when `run_command` cats a file full of
  prompt-injection, the bytes reach the model only as wrapped observation.

OS-level sandboxing (firejail / bubblewrap / container) is flagged
**future-hardening** (see [backburner.md](../backburner.md)). The system prompt
and the [security model](security.md) state this explicitly.

## The workspace

Two roots, both trusted for auto-allow:

- **cwd** (`./`) — always a root, so challenge files dropped in the working
  directory are directly accessible.
- **scratch** (`~/.cairn/workspace`, overridable via `CAIRN_WORKSPACE_DIR`) —
  for downloads and analyzer artifacts.

`Settings.workspace_dir` (`src/cairn/core/config.py`) holds the scratch root;
`load_settings` defaults it under the config dir. `workspace_roots(ctx)`
(`src/cairn/execution/workspace.py`) returns `[cwd, workspace]` per call.

## The permission gate

`src/cairn/execution/workspace.py`:

- `decide(op, target, roots) -> Allow | Deny` — pure v1 policy: allow iff
  `target` resolves inside a root.
- `authorize(op, target, roots, permission)` — consults the UI **only** for a
  denial (in-workspace ops never prompt). v1 has no UI, so out-of-workspace ops
  deny silently.
- `PermissionUI` protocol + `NullPermissionUI` — the **v2 seam** for an
  interactive accept/deny panel. Defined now, wired later (Phase 4).
  Cancel-safe by construction: a future interactive `request()` awaits a
  cancellable `asyncio.Event`, so Esc / Ctrl-C (`task.cancel()`) always wins —
  never a blocking `input()` in the loop.

## Secret hygiene before exec

`scrub_env(env) -> dict` returns a copy minus:

- every `CAIRN_*` var,
- any var whose name matches
  `.*(API_KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION|BEARER|CREDENTIAL).*`,
- any var whose value looks like a known secret shape (`sk-…`, `AKIA…`).

Keys in `PluginContext.keys` are `SecretStr` and never reach `os.environ`
anyway — scrubbing catches the case that matters: a key the user `export`ed.
`run_command` builds its child env from `scrub_env(os.environ)`.

## The subprocess invariant (preserved, not relaxed)

Cairn's standing rule: never `shell=True`; always `create_subprocess_exec(*args)`
with array args (`src/cairn/execution/subprocess_util.py`). The full-agentic
shell satisfies **both** this invariant and the "arbitrary shell" requirement:

- `run_shell(command)` executes `["bash", "-c", command]` via
  `create_subprocess_exec` — `bash` is argv[0], `-c` is argv[1], the command a
  single argv[2]. Pipes / redirects / globs / `&&` work; the no-shell-at-the-
  Python-level property holds. A non-zero exit is **data**
  (`CommandResult.returncode`), never raised.
- `run_subprocess(args, *, cwd=…)` keeps its existing 2-tuple `(stdout, stderr)`
  contract (used by `cli_tools`); the shared `_exec` core owns timeout + kill
  discipline.

## The agentic tools

All in `src/cairn/plugins/agentic/`, all `requires_key=None`,
`daily_limited=False`, `category="agentic"`, auto-discovered (no registration).

| Tool | Input | Boundary | Notes |
|---|---|---|---|
| `read_file` | `target=path, max_bytes` | checked | Returns capped text + mined IOC entities; the wrap-back is the injection defense. |
| `list_files` | `target=dir, max_depth, max_entries` | checked | Depth-limited tree with sizes. |
| `write_file` | `target=path, content, append` | checked | mkdir parents; append vs overwrite. |
| `download_url` | `target=url, dest=path` | checked (dest) | Saves raw bytes + sha256 + content-type; distinct from `scrape_url` (text). |
| `run_command` | `target=command, timeout` | policy-level | Full shell via `run_shell`; env scrubbed; exit code as data. |

CLI install is the existing `install_cli` plugin (`src/cairn/plugins/identity/`),
reused — not duplicated.

## Investigate vs challenge mode

`Settings.mode: Literal["investigate","challenge"]` (default `investigate`, set
via `CAIRN_MODE`) selects the reconnaissance stance in the system prompt:

- **investigate** — passive recon only (the standing stance): public records,
  third-party indexes, certificate transparency, DNS, web archives. No active
  scanning of external hosts.
- **challenge** — permits active analysis of **provided artifacts** (challenge
  files, captured traffic, local images) and lets `run_command` / `download_url`
  fetch challenge resources — but **still forbids scanning third-party / external
  hosts** without explicit user instruction.

`build_system_prompt(settings)` renders the stance by mode; the REPL banner
surfaces the active mode.

## Two-tier analyzer allowlist

`cli_tools.CliToolSpec` gains `manager` (`uv` | `system`), `install_hint`, and
`bootstrap`. Analyzers split:

- **Tier A — uv-installable** (`manager="uv"`, bootstrapped at startup):
  `binwalk`, `oletools`, `html2text`, `pdfminer.six`.
- **Tier B — system packages** (`manager="system"`, hint-only, no auto-install):
  `exiftool`, `foremost`, `tshark`, `nmap`, `dig`, `pdftotext`, `steghide`,
  `identify`, `zsteg`, `strings`.

The brain calls `run_command` to invoke any of them; if one is missing it calls
`install_cli`, which auto-installs Tier-A and relays a Tier-B install hint
(`brew install …` / `apt install …`) without attempting an install.

## Phase progress

| Phase | Scope | Status |
|---|---|---|
| 1 — Foundations | `workspace.py` (boundary, gate, scrub, tree), `subprocess_util.run_shell`/`_exec`, `config.mode`/`workspace_dir`, `PluginContext.workspace`/`permission`, `runner` workspace wiring | ✅ shipped |
| 2 — Agentic plugins | `read_file` / `list_files` / `write_file` / `download_url` / `run_command` + tests (boundary, scrub, wrap-back, exit-code-as-data) | ✅ shipped (165 tests, ruff clean) |
| 3 — System prompt + allowlist | `build_system_prompt(settings)` mode-gated; two-tier `CliToolSpec`; `repl` bootstrap filter; `security.md` section; tests | ✅ shipped (174 tests) |
| 4 — UI track | `/workspace` (`/files`) REPL command; `permission_panel.py` (`RichPermissionUI` v2 seam, tested, not wired into the live turn) | ✅ shipped (181 tests) |
| 5 — Adversarial review + smoke | 6-lens workflow review (3-skeptic panels); real-model `CAIRN_MODE=challenge` smoke | ✅ review done (5 defects fixed, 184 at review); smoke **partial** — `read_file` ✓ on grok-4.5, rest pending |

## Phase 5 — adversarial review: findings & fixes

A 6-dimension review workflow (boundary, wrap-back, secret-scrub, subprocess
invariant, mode/prompt, doc drift — each finding verified by a 3-skeptic panel)
found **5 code defects + 3 doc-drift items**; all fixed (**184 tests at review,
187 repo-wide after the Phase-6 theme foundation; ruff clean**). The two majors
are load-bearing:

- **`wrap_untrusted` attribute bypass (Layer B, major)** — `source`/`target`
  were interpolated *raw* into the opening tag's attributes. A model-authored
  `run_command` target carrying the literal closing tag (or even a double-quote)
  broke the wrapper, letting text appear *outside*
  `<untrusted_external_data>` — a direct anti-injection bypass. Fixed: both are
  now XML-attribute-escaped (`_attr_escape` in `core/security.py`); regression
  test `test_wrap_untrusted_neutralizes_tag_and_quote_in_target`.
- **CLI-tool env leak (secret hygiene, major)** — `_augment_path_env` passed
  `os.environ.copy()` raw to sherlock/holehe/binwalk subprocesses (networked),
  bypassing the scrub `run_command` applies. Fixed: it now routes through
  `scrub_env` like the agentic shell; test `test_augment_path_env_scrubs_exported_secrets`.
- **`scrub_env` name/value gaps (minor)** — broadened `_SECRET_NAME_RE`
  (AUTH, COOKIE, PRIVATE_KEY, PASSWD, APIKEY, ACCESS_KEY, …) and
  `_SECRET_VALUE_RES` (AWS STS `ASIA` prefix; GitHub `ghp_`/`github_pat_`);
  test `test_scrub_env_catches_broadened_secret_names`.
- **`download_url` bespoke gate (minor)** — now routes its dest through the
  shared `authorize()` + `resolve_in_workspace()` (clean Deny on a symlink loop;
  symmetric v2-UI approval path with read/write/list).
- **Doc drift (3×)** — Phase 3/4 were marked pending in the table + roadmap
  despite being shipped; corrected.

Only the `wrap_untrusted` finding was a live Layer-B escape (now closed); the
rest hardened secret-hygiene and consistency. The remaining Phase-5 half is the
real-model `CAIRN_MODE=challenge` smoke — now **partial**: `read_file` verified
end-to-end on grok-4.5 (2026-07-28); `run_command` exit-as-data / `scrub_env` /
Esc-cancel prompts still pending.

## File map

- `src/cairn/execution/workspace.py` — boundary, permission gate, env scrub, tree.
- `src/cairn/execution/subprocess_util.py` — `run_shell` / `run_subprocess` / `_exec`.
- `src/cairn/execution/cli_tools.py` — `CliToolSpec`, two-tier allowlist (Phase 3), `install_cli`.
- `src/cairn/core/config.py` — `Settings.workspace_dir`, `Settings.mode`.
- `src/cairn/execution/base.py` — `PluginContext.workspace`, `PluginContext.permission`.
- `src/cairn/plugins/agentic/` — the five tools.
- `src/cairn/plugins/identity/install_cli.py` — two-tier install list (uv auto / system hint).
- `src/cairn/reasoning/system_prompt.py` — `build_system_prompt(settings)` (mode-gated).
- `src/cairn/interfaces/repl.py` — `/workspace` (`/files`) command; bootstrap filter; mode banner.
- `src/cairn/interfaces/tui/permission_panel.py` — `RichPermissionUI` v2 seam (tested, not wired into the live turn).
- `tests/unit/test_workspace.py`, `tests/plugins/test_agentic.py`, `tests/unit/test_system_prompt.py`, `tests/unit/test_cli_tools.py`, `tests/unit/test_workspace_ui.py`.
