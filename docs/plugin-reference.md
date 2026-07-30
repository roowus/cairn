# Plugin Reference

Every plugin is one deterministic lookup = one tool the brain can call. Free
plugins are always available; keyed plugins (`requires_key`) activate the moment
their `CAIRN_*_KEY` is set. Auto-discovered — no registration needed. See the
[plugin contract](architecture/plugin-contract.md).

> **Free-first policy:** the default set needs *no* key and *no* paid platform.
> Keyed plugins here are free-tier-with-key (Brave, Shodan, VT, Censys,
> AbuseIPDB, HIBP) — *optional* accelerators, never required. Paid walled
> platforms (Bright Data, SerpAPI, TinEye, facecheck) are deliberately excluded.
> See [discoveries § free-first strategy](discoveries.md#free-first-strategy).

Legend: 🆓 free / no key · 🔑 free-tier-with-key (optional) · ⏳ free but a hard
per-day quota (off by default; opt in with `CAIRN_ALLOW_DAILY_LIMITED=1`) · the
`target` is the required input every plugin takes.

### Tiers & gating

Every plugin has a **tier** shown by `cairn plugins`: `free` (no key, no daily
quota), `limited/day` (free but a hard daily quota — excluded from the brain's
tools unless `CAIRN_ALLOW_DAILY_LIMITED=1`), or `keyed` (hidden until its
`CAIRN_*_KEY` is set). The brain only ever sees `active` plugins; the listing
shows hidden ones with the reason, so you know exactly how to enable them.

### Cost & usage

Each plugin also carries a **cost** (its `CostSpec`) — what each call consumes
and any quota: `free`, `50/day`, `2k/mo`, `credits`, `paid`, … shown in the
`cost` column of `cairn plugins`. Live credits/time/quota used are reported by
`/usage` (REPL) and `cairn usage` (historical, from the audit log). See
[usage & cost reporting](architecture/usage-and-cost.md).

## Identity (`plugins/identity/`)

| Plugin | Cost | `target` | Purpose |
|---|---|---|---|
| `generate_dorks` | 🆓 | name/handle | Offline Google-dork recipes (`site:` per platform, `filetype:pdf`, `resume OR cv`, `leaked OR breach`) as query strings + ready-to-open URLs. Feed into `web_search`. |
| `web_search` | 🆓 / 🔑 | query (dorks ok) | Live search. **Brave is the reliable path** (`CAIRN_BRAVE_KEY`); no-key DuckDuckGo fallback returns an actionable "blocked" message when anti-bot hits. |
| `github` | 🆓 / 🔑 | login or GitHub URL (not a bare email) | REST profile + repos + **commit-mined emails** (profile `email` is often null — mine `gh-pages`/default commits) + YouTube embeds from README/`index.md` + avatar URL. Accepts bare login, `github.com/…` URLs, and `git@github.com:user/repo`. Email-shaped inputs are not ideal (local-part may be tried as a login — see issue #31). 60/hr free → 5k/hr with `CAIRN_GITHUB_KEY` (**recommended** for commit mining). Details: [social-probing.md](social-probing.md#5-tools-when-to-use-which). |
| `whois_rdap` | 🆓 | domain | RDAP registrar/dates/nameservers/status. |
| `shodan_internetdb` | 🆓 | IP | Shodan InternetDB: hostnames, ports, vulns, tags (no key). |
| `holehe` | 🆓 | email | Which websites/services an email is registered on (wraps the `holehe` CLI). **Auto-installs** if missing. Full run often takes **1-2 min** (own process timeout, not the 30s HTTP default). Parser matches only **domain-shaped** `[+] host.tld` lines so the v1.61 legend (`[+] Email used, …`) is never reported as a platform. |
| `username_check` | 🆓 | username | **Preferred** major-platform presence check via **first-party** URLs (Instagram, GitHub, Reddit, YouTube, TikTok, X, Threads). Browser-like HTTP + empty-shell retries. Not Sherlock mirrors. |
| `sherlock` | 🆓 | username | Wide 300+ site sweep via `sherlock` CLI, then **first-party cross-check** of major platforms (fixes IG/imginn false negatives). Auto-installs. 1-3 min. Prefer `username_check` when you only need major sites. |
| `install_cli` | 🆓 | tool name or `list` | Repair allowlisted CLIs (`sherlock`/`holehe`). Usually unnecessary — they auto-install. |

**Keyed identity:** none mandatory; `github` and (via `web_search`) `brave` keys
are rate/quality boosts.

## Infrastructure (`plugins/infrastructure/`)

| Plugin | Cost | `target` | Purpose |
|---|---|---|---|
| `dns_lookup` | 🆓 | domain | DNS records (A default; `record_type` configurable). Uses `dnspython`. |
| `crtsh` | 🆓 | domain | Certificate-transparency subdomain enumeration. Distinguishes HTTP/timeout/JSON failures from true empty results; subdomain filter uses a **label boundary** (`*.base`, not string suffix) so `notexample.com` is not treated as under `example.com`. CT queries use ≥60s timeout headroom. |
| `wayback_cdx` | 🆓 | URL/domain | Wayback Machine CDX snapshot index (earliest/latest). Credentialed historical URLs (`user:pass@host`, including nested archive wrappers) are redacted before summary/entities. |
| `ripestat` | 🆓 | IP / prefix / ASN | ASN, holder, prefix, country via RIPEstat. |
| `hackertarget` | 🆓 ⏳ | IP or domain | hostsearch / reverseip / whois / dnslookup. Auto-picks by target type. **Off by default** — free tier is ~50/day, so it's `daily_limited`; opt in with `CAIRN_ALLOW_DAILY_LIMITED=1`. |
| `urlscan` | 🆓 / 🔑 | IP or domain | urlscan.io community results (page URL/domain/IP/title/server). Hits filtered to **on-target** domain/IP (or subdomains); raw index `total` is not claimed as on-target. Higher limit with `CAIRN_URLSCAN_KEY`. |

## Web / content (`plugins/web/`)

| Plugin | Cost | `target` | Purpose |
|---|---|---|---|
| `scrape_url` | 🆓 | URL | Fetch a page → title, visible text, links, images (incl. `og:image` profile pic). httpx+BeautifulSoup default; renders JS via **crawl4ai** when installed. Mines entities for pivoting. |
| `web_search` | 🆓 / 🔑 | query | Live search. **Reliable path = Brave** (`CAIRN_BRAVE_KEY`, free 2k/mo). No-key fallback is DuckDuckGo, which increasingly returns an anti-bot 202 page — when blocked, the tool returns no results *with an actionable Brave message* (never silent, never fabricated). |
| `wayback_fetch` | 🆓 | URL | Fetch an archived snapshot's body from the Wayback Machine (`timestamp` optional). Archived URL in summary/entities is userinfo-redacted (including nested playback forms). |
| `common_crawl` | 🆓 | domain/URL | Common Crawl index matches. Bare domains normalize to `host/*`; HTTP errors vs empty results are distinguished. |
| `h1_reference` | 🆓 | keyword | HackerOne Hacktivity disclosed-reports reference (keyless GraphQL). Rank by top-voted (validated techniques) or top-bounty; returns title/severity/bounty/url per report. For tradecraft / vuln-prioritization research. |

## Forensics / secrets

| Plugin | Cost | `target` | Purpose |
|---|---|---|---|
| `secret_scan` | 🆓 | path | 48-pattern secret/credential scanner (AWS/GitHub/Stripe/Slack/AI APIs/private keys/…). Scans a workspace file/dir; findings become typed `secret` entities with `Severity` + provenance (tool + file + file SHA-256). Pure stdlib. For challenge/forensics artifacts; results are untrusted (wrapped). |

**Reality check (2026):** free no-key web search is blocked by anti-bot on
DuckDuckGo / Google / Bing, and SearXNG public instances are unreliable. Jina
*Search* (`s.jina.ai`) now requires a key. So for dependable search, set a free
`CAIRN_BRAVE_KEY`. This is consistent with the avoid-paid-platforms policy
(Brave is a free-tier-with-key, not a paid walled service).

**Optional scrape backends (free):** crawl4ai (`uv sync --extra crawl`) for
JS-rendered social pages; Jina *Reader* (`r.jina.ai/{url}` → markdown, still
free no-key) is a documented alternative to wire in next.

**External CLI tools:** `holehe` and `sherlock` wrap external binaries. Cairn
**auto-installs** them at REPL startup and on first use (`uv tool install
<fixed package>`, allowlist in `execution/cli_tools.py`). You do **not** run
install commands. Requires `uv` on `PATH`; shims land in `~/.local/bin`.

**Username / social presence:** prefer **`username_check`** for Instagram and
other major platforms (first-party URLs, browser-like HTTP). Do not trust raw
Sherlock alone for IG — its upstream rule probes `imginn.com`. Sherlock still
helps for long-tail sites and now **cross-checks** majors first-party. Full
write-up: [social-probing.md](social-probing.md).

**CLI timeouts:** Sherlock overall default **240s**, holehe **180s** (not the
30s HTTP `ctx.timeout`). Holehe uses `--only-used` (not `--only-known`).

## Agentic (`plugins/agentic/`)

Workspace file/exec tools for challenges and local artifact analysis. They are
**always registered** today (both `investigate` and `challenge` mode) — mode only
swaps system-prompt stance ([issue #15](https://github.com/roowus/cairn/issues/15)).
Every result is still wrapped in `<untrusted_external_data>`. See
[agentic file & tool control](architecture/agentic-file-control.md).

| Plugin | Cost | `target` | Purpose |
|---|---|---|---|
| `read_file` | 🆓 | path | Read a workspace file (capped); mines IOC entities. |
| `list_files` | 🆓 | path (`.` = cwd) | Depth-limited workspace tree with sizes. |
| `write_file` | 🆓 | path | Create/overwrite/append text in the workspace. |
| `download_url` | 🆓 | http(s) URL | Stream raw bytes into the workspace; **25 MiB default cap** (`max_bytes`), Content-Length pre-check, sha256. Not for HTML text — use `scrape_url`. |
| `run_command` | 🆓 | shell command | `bash -c` in the workspace (array args, scrubbed env). Exit code is data. Policy sandbox only — not OS containment. |

## Keyed / paid-tier (`plugins/paid/`)

These are `requires_key` plugins — absent from the tool list until their key
exists, then they appear with zero code change.

| Plugin | Key | `target` | Purpose |
|---|---|---|---|
| `shodan_full` | `CAIRN_SHODAN_KEY` | IP | Full Shodan host: ports, org, hostnames, vulns. |
| `virustotal` | `CAIRN_VIRUSTOTAL_KEY` | IP/domain/hash/URL | VT reputation: malicious/suspicious/harmless counts, categories. |
| `censys` | `CAIRN_CENSYS_KEY` | IP | Censys services, ASN, location. |
| `abuseipdb` | `CAIRN_ABUSEIPDB_KEY` | IP | Abuse confidence score, country, ISP, report count. |
| `hibp` | `CAIRN_HIBP_KEY` | email | Have-I-Been-Pwned breach list (`include_unverified` opt-in). |

## Entity types the brain pivots on

Plugins emit `entities: list[Entity]` (captured into the NetworkX graph by
`tool_adapter`). Types mined automatically by `core/entities.py` from any
returned text:

| Type | Example |
|---|---|
| `email` | `jane@example.com` |
| `url` | `https://github.com/jane` |
| `ip` | `203.0.113.5` (validated) |
| `domain` | `sub.example.org` (only bare, not part of an email/url) |
| `crypto_btc` | `bc1q…` |
| `crypto_eth` | `0x71C7…` |
| `phone` | `+1-555-0100` |

Plus per-plugin synthetic entities: `github_login`, `github_repo`, `username`,
`person`, `asn`, `nameserver`, etc.

## Calling plugins without the LLM

The registry also powers a headless CLI, so any plugin runs directly:

```bash
uv run cairn plugin shodan-internetdb 8.8.8.8
uv run cairn plugin github torvalds
uv run cairn plugin web-search 'site:instagram.com "jane_doe"'
uv run cairn plugin scrape-url https://example.com
uv run cairn plugin list           # show available (key-gated ones appear once keyed)
```
