---
name: secrets-hunting
description: Hunt leaked credentials in repos, gists, JS bundles, and challenge artifacts via the 48-pattern scanner plus code-search/paste dorks.
usage: /secrets-hunting <org, domain, repo URL, or handle>
---

# Hunt leaked secrets

Find hardcoded credentials/API keys/private keys exposed in a target's code,
gists, JS bundles, commit history, paste sites, and challenge artifacts. Route
all scanning through `secret_scan`; gather candidate text with `github`,
`scrape_url`, `wayback_fetch`, and `download_url`. **Discovery is passive.
Validation is not — see the gating box.**

## Plan

1. **Anchor the target.** Determine what `<target>` is: a GitHub login/org, a
   domain, a single repo/gist URL, or (in challenge mode) a workspace path.
   Every later step fans out from this.

2. **Map the code surface (parallel).**
   - `github <login-or-url>` → profile, repos, **commit-mined emails** (authors
     of `.env`, `config/`, `*.key` commits are high-signal), gists, and avatar.
     List every repo URL and gist URL for step 4.
   - `generate_dorks <target>` → leak-shaped queries; feed the strongest 4–5 to
     `web_search` (see Dorks below).
   - If a domain: also `crtsh` (subdomains often host distinct JS bundles) and
     `wayback_cdx <domain>` — old snapshots leak secrets that were since scrubbed.

3. **Pull candidate artifacts into the workspace** (so `secret_scan` can read a
   real path — it only resolves inside the workspace). For each promising source:
   - **JS bundles / HTML / config files** on a live site → `scrape_url <url>`
     returns text+links; if the body is large or you need the raw file, use
     `download_url <url>` (challenge) to land it on disk, then scan.
   - **Gists / raw repo files** → `download_url` the `raw.githubusercontent`
     / `gist.githubusercontent` URL, OR `scrape_url` if read-only suffice.
   - **Old/scrubbed commits** → `wayback_fetch <repo-url>` for the snapshot at
     the commit date; diff against current to spot deleted secrets.
   - **Challenge artifacts** already in the workspace → skip straight to step 4.

4. **Scan everything.** `secret_scan <workspace-path-or-file>` runs the full
   48-pattern catalog (see Catalog below) and emits typed `secret` entities with
   severity, `FIRM` confidence, and SHA-256 provenance. Scan:
   - each downloaded JS/JSON/env file,
   - the cloned repo tree (challenge: `run_command` `git clone` then
     `secret_scan` the dir; also `git log -p --all -S 'AKIA' -- '*.env'`),
   - gist bodies,
   - any `sourcesContent`/source-map blobs referenced by the JS,
   - Wayback-fetched HTML.

5. **Triage hits.** Dedupe by SHA-256; downgrade obvious test/example data
   (`sk_test_`, an `AKIA…EXAMPLE` access-key id, `example.com` bearer tokens, keys in
   `README.md` code fences). For each surviving hit, record provider, the file
   it came from, severity, and whether the source looks production (`.env`,
   bundled minified JS) vs. docs/example.

6. **Validate — ONLY under the gating conditions below.** Default (investigate)
   mode: do **not** validate; report each secret as *discovered, unvalidated*
   and hand the list to the operator. If `CAIRN_MODE=challenge` AND the user has
   explicitly authorized validating a specific credential on a target they own,
   the read-only endpoints in the Validators section confirm liveness.

## Secret catalog (what `secret_scan` detects)

`secret_scan` runs all 48 patterns, most-specific first. Grouped overview so you
know what a hit means (full regex live in the plugin):

- **CRITICAL — cloud/IAM:** AWS access key (`AKIA`/`ASIA`+16), AWS secret
  (typed + loose), GCP service-account JSON, GitHub classic/fine-grained PAT
  (`ghp_`/`github_pat_`), Stripe live key (`sk_live_`), RSA/EC/OpenSSH/PGP
  private-key headers.
- **HIGH — SaaS/AI/package:** GitHub OAuth/s2s (`gho_`/`gh[usr]_`), Google API
  key (`AIza`), Slack token (`xox*`), SendGrid (`SG.…`), Mailgun (`key-…`),
  Twilio API key/SID/auth, Anthropic (`sk-ant-`), OpenAI legacy/project
  (`sk-…T3BlbkFJ…`/`sk-proj-`), OpenAI session (`sess-`), HuggingFace (`hf_`),
  DigitalOcean (`dop_v1_`), npm (`npm_`), PyPI (`pypi-AgENdGV…`), Docker Hub
  (`dckr_pat_`), Atlassian (`ATATT3xFfGF0…`), DataDog (in `DD_API_KEY` ctx),
  Discord bot token, Telegram bot token.
- **MEDIUM/LOW:** Stripe test (`sk_test_`), Slack webhook, Firebase URL, any
  JWT, `Authorization: Bearer …` assignments, `https://user:pass@host` basic
  auth, Cloudflare/ngrok/New Relic/Linear/Sentry-DSN (context-paired), generic
  `api_key=`/`access_token=` assignments.

**False-positive cues:** JWT/Bearer/Generic fire on docs and examples — judge by
context (a JWT in `.env` ≠ one in a README block). Fine-grained PAT is exactly
82 chars; be skeptical of longer/shorter. Stripe-test and Mailgun-loose are
noisy by design (severity set low).

## Dorks (route via `generate_dorks` then `web_search`; paste hits via `scrape_url`)

Substitute `{t}` = the org/domain/handle. Engines differ — run the top queries
across whichever `web_search` backend is active.

```
# GitHub code search (highest-yield for org repos)
site:github.com "{t}" (AKIA OR ghp_ OR sk_live_ OR "BEGIN RSA PRIVATE KEY")
site:github.com "{t}" (filename:.env OR filename:config.json OR filename:settings.py)
site:github.com "{t}" (AIza OR sk-ant- OR sk-proj- OR xox OR github_pat_)

# Paste / leak sites
site:pastebin.com "{t}"
site:gist.github.com "{t}"
site:rentry.co "{t}" OR site:ghostbin.com "{t}" OR site:hastebin.com "{t}"
"{t}" "BEGIN RSA PRIVATE KEY" OR "BEGIN OPENSSH PRIVATE KEY"

# Live-site config / backup exposure (passive — you're reading public files)
site:{t} (filetype:env OR ext:env OR ext:ini OR ext:conf OR ext:yml)
site:{t} (ext:bak OR ext:old OR ext:orig OR ext:sql OR ext:dump)
site:{t} inurl:.git OR inurl:/.git/
site:{t} ext:js (apiKey OR api_key OR Authorization)        # then scrape_url + scan

# Shadow-IT / cloud storage (often holds .env or tokens)
site:s3.amazonaws.com "{t}"
site:storage.googleapis.com "{t}"
site:blob.core.windows.net "{t}"
```

For each paste/gist/raw hit, `scrape_url` to confirm the secret is actually
present in the body (paste titles lie), then `download_url`/`read_file` so
`secret_scan` can cite it with a hash.

## Validators (KNOWLEDGE — gated, see below)

Read-only liveness checks. Each returns live/dead without writing anything.
Tag every validation with `detectability` and `checked_at` (UTC ISO-8601).

| Provider | Read-only call | Live signal | Detectability |
|---|---|---|---|
| GitHub PAT | `GET api.github.com/user`, `Authorization: token ghp_…` | 200 + `X-OAuth-Scopes`; 401 = dead | low |
| Slack | `POST slack.com/api/auth.test`, `Bearer xox…` | `{"ok":true}`; `invalid_auth` = dead | low |
| Anthropic | `GET api.anthropic.com/v1/models`, `x-api-key`+`anthropic-version` | 200; 401 dead; 403 org_disabled | low |
| OpenAI | `GET api.openai.com/v1/models`, `Bearer sk-…` | 200; 429 = live/quota gone | low |
| npm | `GET registry.npmjs.org/-/whoami`, `Bearer npm_…` | 200 `{"username":…}` | low |
| Postman | `GET api.getpostman.com/me`, `X-Api-Key: PMAK-…` | 200 user obj; 401 dead | low |
| Atlassian | `GET <ws>.atlassian.net/rest/api/3/myself`, Basic `email:ATATT…` | 200; 401 dead | low |
| AWS | `sts:GetCallerIdentity` (boto3/`aws sts get-caller-identity`) | Account+ARN+UserId; `InvalidClientTokenId` dead | **medium** (CloudTrail logs it in the victim account) |

**Hard rules (when validation is authorized at all):** read-only endpoint only;
never create/modify/delete/send; record `checked_at`; for root AWS keys,
infrastructure-write GitHub PATs, or admin Slack tokens, **do not validate** —
flag and let the operator decide. Post-discovery enumeration (AWS IAM enum,
GitHub repo/org enum, Slack `conversations.list`, Postman workspace/collection
dump, JWT alg-confusion/`none`-bypass testing) is **active offensive
tradecraft** — same gate applies, and JWT brute-force (hashcat `-m 16500`) is
outright out of scope for Cairn.

## Active-probe gating (critical)

- **Discovery is passive and allowed in default `investigate` mode:** reading
  public GitHub code, scraping live JS/HTML, pulling Wayback snapshots, and
  scanning artifacts already in your workspace.
- **Validating or enumerating with a discovered credential is ACTIVE use of that
  credential** — even a read-only `GET /me` uses a stolen key and may log in the
  victim's account. It requires `CAIRN_MODE=challenge` **AND** explicit user
  authorization on the specific credential and an owned/in-scope target.
- **Cairn's default investigate mode is passive-only.** When not authorized,
  report each secret as `status: discovered_unvalidated` and stop. Do not
  auto-run validators against a third party. Active scanning, fuzzing,
  brute-force, and exploitation are forbidden unless separately authorized.

## Paid / excluded sources

DeHashed, IntelX (paid), SecurityTrails, RiskIQ, Hunter.io (paid), Censys
(beyond free), TinEye, facecheck, Bright Data, SerpAPI are **excluded** from
Cairn. Free alternatives for this hunt: GitHub code search (rate-limited, no
key), `crtsh`, Wayback (`wayback_cdx`/`wayback_fetch`), urlscan, `github`
(commit-mining), paste-site dorks via `web_search`, and `secret_scan` on
anything you can land in the workspace. For breach↔credential correlation,
`hibp` (keyed, free-tier) is the only in-platform option; everything else is
note-only / requires your own key.

## Pivot on

- A live-suspected **AWS key** → enumerate the victim org's other repos/gists
  for `AWS_SECRET_ACCESS_KEY` near the same `AKIA` (secrets are committed in
  pairs).
- A **GitHub PAT** → the owning user's other repos and gists (one leaked token
  usually means a sloppy hygiene pattern).
- **Bundled JS** that references an internal API base URL or S3 bucket →
  `scrape_url`/`download_url` that endpoint's config; follow `sourcesContent`
  source maps back to un-minified source (richer secret surface).
- **Commit-mined emails** from `github` → cross-reference against paste-site and
  breach dorks for the same identity.
- **GCP service-account JSON** → the `project_id` and `client_email` fields
  identify the victim project; pivot to that org's other repos.

## Output

One-line exposure verdict (e.g. "3 unvalidated CRITICAL secrets across 2 repos
+ 1 gist, AWS + GitHub PAT"), then a per-finding table: provider, severity,
source URL/path + SHA-256, status (`discovered_unvalidated` unless the gating
conditions authorized validation), and `detectability` if validated. Then
"Next steps" — the highest-value pivot not taken, and an explicit reminder that
validation/enumeration needs `CAIRN_MODE=challenge` + user authorization. Never
report a secret a tool did not surface; never claim a credential is live unless
an authorized validator returned 200.

> Tradecraft adapted from [Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT) by ElementalSoul (MIT). Active techniques gated to authorized/challenge use.
