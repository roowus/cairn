# 0006. First-party social probes over Sherlock mirrors

- **Status:** Accepted
- **Date:** 2026-07-27

## Context

Operators observed that **incognito browsers** load Instagram profiles without
login, while Sherlock reported no Instagram hit. Investigation showed:

1. Sherlock’s Instagram rule uses `urlProbe: https://imginn.com/{}` (third-party).
2. Bare HTTP clients often receive empty JS shells; browser-like clients often
   receive `og:title` metadata matching the browser.
3. Collapsing “empty shell” into “not found” causes false negatives.

Separately, GitHub’s public profile `email` is often null while commit metadata
still exposes real addresses — the old `github` plugin never mined commits.

## Decision

1. Add `execution/browser_http.py` and make the shared session client browser-like.
2. Add `execution/social_probe.py` + plugin `username_check` for major platforms
   with statuses `found | not_found | unknown | error`.
3. Run first-party cross-check after Sherlock; drop mirror URLs (imginn, nitter).
4. Extend `github` to mine commit emails and portfolio YouTube embeds.
5. Document the model in [social-probing.md](../social-probing.md). Cookie /
   Playwright channels remain the next tier (agent-reach), not a substitute for
   fixing first-party existence checks.

## Consequences

- Brain should call `username_check` before/instead of Sherlock for majors.
- `unknown` must not be summarized as absence.
- Unauthenticated GitHub rate limits (60/hr) constrain commit mining; PAT
  recommended (`CAIRN_GITHUB_KEY`).
- Sherlock remains valuable for long-tail sites only.

## See also

- [Social probing](../social-probing.md)
- [agent-reach analysis](../research/agent-reach-analysis.md)
- ADR [0005](0005-pi-auth-and-model-switching.md)
