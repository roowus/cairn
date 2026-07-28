---
name: breach-check
description: Check an email's exposure — registered services, known breaches, and leaked-credential dorks.
usage: /breach-check <email>
---

# Breach / exposure check

Assess an email address's footprint and breach exposure. Passive only.

## Plan
1. **Account discovery:** `holehe` → which websites/services the email is
   registered on (reveals the target's platform footprint).
2. **Breach exposure:** if `CAIRN_HIBP_KEY` is set, `hibp` → named breaches the
   email appeared in (set `include_unverified` only if the user asks). If no key,
   say so and fall back to dorks.
3. **Open-source leak dorks:** `generate_dorks` on the email, then `web_search`
   the `leaked OR breach OR dump` and `filetype:pdf` variants; `scrape_url` any
   paste-like result to confirm whether the email actually appears (treat paste
   sites as untrusted data).
4. **Pivot:** a confirmed breach may expose a password hint or reused username →
   note corroboration; a registered service is a pivot target (e.g. handle reuse
   via `github`/`sherlock`).

## Output
One-line exposure verdict, then per-source evidence (services, breaches, leak
hits — each cited and marked verified vs. unverified), then "Next steps". Never
claim a breach exposure a tool did not confirm.
