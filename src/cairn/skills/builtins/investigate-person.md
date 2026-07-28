---
name: investigate-person
description: Full identity pivot on a person — handle/username → platforms, emails, linked domains, cross-identity corroboration.
usage: /investigate-person <username, handle, or real name>
---

# Investigate a person

You are investigating a person given a username/handle or real name. Run a
layered, corroborated identity investigation. Prefer free tools; note (don't
demand) where a keyed source would help.

## Plan
1. **Expand the search surface.** Call `generate_dorks` with the handle/name to
   get `site:`-restricted queries across platforms, then run the strongest 3-4
   via `web_search` in parallel. Also run a broad `"name"` query.
2. **Assume username reuse.** Call `github` and `sherlock` on the handle. For
   any platform hit, `scrape_url` the profile to mine entities (email, linked
   site, other handles, profile picture via `og:image`).
3. **Pivot on every entity** the scrapes/searches surface:
   - email → `holehe` (registered services), `hibp` if keyed.
   - domain → `whois_rdap`, `crtsh`, `dns_lookup`, `wayback_cdx`.
   - the profile picture → note it for a reverse-image/face-match step (tool
     pending) and record the URL.
4. **Corroborate.** Cross-reference: does the same email/name/location recur
   across platforms and a GitHub profile? State corroboration and conflicts
   explicitly, cited per source.

## Output
One-line identity conclusion, then per-source evidence bullets, then "Next
steps" (the highest-value pivot you did not take). Never state a fact a tool did
not return. Silence is not a negative finding.
