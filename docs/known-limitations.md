# Known limitations & gotchas

Things that can look like bugs but are (currently) expected, plus fragile spots
worth knowing before you chase them.

## holehe — rate-limit / anti-bot ceiling
holehe finds email→site registrations via signup/password-recovery probes. In 2026
most major sites rate-limit or anti-bot those probes, so holehe's hit rate is low
and **degrades with repeated runs** (rapid probing trips the blocks → fast-fail to
0 hits in <1s). A thin or zero result is usually a **false negative**, not a clean
negative — the tool's own output shows `[x] Rate limit`.

- **History**: Cairn once passed `-NP`/`--no-password-recovery`, which skipped the
  very probes that *are* holehe's detection → always 0. Fixed (the flag was
  removed); a regression guard in `tests/plugins/test_holehe.py` asserts it's
  never re-passed.
- `-C` is just CSV output; `-T` (per-site timeout, default 10s) is already sane.
  There is **no** flag that defeats the sites blocking the probes.
- **For breadth, supplement**: `username_check` / `sherlock` (username→profiles, a
  *different* mechanism covering different sites) and `hibp` (breaches). holehe is
  one partial signal, not the whole picture. The brain's answer already steers this
  way; accept the pivot or chain the tools in a skill.

## GLM-5.2 (Z.AI) — REPL works, headless `cairn search` returns empty
GLM-5.2 is a reasoning model: it emits its text in `reasoning_content`. The REPL
path renders GLM answers fine, but **headless `cairn search` against GLM currently
returns empty** (a pydantic-ai↔GLM `reasoning_content` extraction gap, under
investigation). The raw Z.AI API itself works (HTTP 200). Grok (xAI) works in both
paths when the account has credits. **Use the REPL for GLM** until the headless
gap is fixed.

## Grok (xAI) — billing, not auth
Grok via pi-auth OAuth returns `403 "out of credits or need a Grok subscription"`
when the account's credits/subscription are exhausted — a **billing** issue, not
an auth/OAuth failure (the OAuth token itself is valid; check its expiry in
`~/.pi/agent/auth.json`). Add credits / renew SuperGrok, or re-login
(`pi /login` → pick xAI, in a browser) to switch to a subscribed account.

## Parallel contribution — use branch + PR
Multiple agent sessions edit this repo concurrently. Direct-to-`main` commits can
be **dropped by a PR rebase** (it happened to U4 once). The branch → PR → merge
flow (used by #23/#24/#30) survives rebases cleanly. Default to a **branch + PR**
for non-trivial work; rebase onto `main` before starting; keep your edit surface
disjoint from other in-flight sessions (see the file-ownership map in
`CLAUDE.md`). Commit/push when green and disjoint (the relaxed policy); never
force-push `main`.

## Live stdout — only the long-running CLI tools stream
`run_command`, `sherlock`, and `holehe` stream stdout into their card (UI U3).
Other plugins use the buffered `communicate()` path (`on_line=None`). Streaming is
**observer-only** — it changes live visibility, never the result or the
hard-stop.

## Containment is policy-level, not OS-enforced
The agentic workspace ("auto-allow inside cwd + scratch") is an *intent*
boundary, not OS sandboxing. `run_command` can escape the workspace (a symlink,
`cp ~/`, `curl | sh`). The defenses that hold: the file-op boundary check
(`Path.resolve` defeats `..`/symlink escape), `scrub_env` before exec, and result
wrapping. OS-level sandboxing (firejail/bubblewrap) is flagged future work — never
claim airtight containment. See
[agentic file & tool control](architecture/agentic-file-control.md).
