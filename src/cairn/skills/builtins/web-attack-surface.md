---
name: web-attack-surface
description: Map a web app attack surface — Swagger/OpenAPI, GraphQL, HTTP misconfigs (.git/.env/actuator/heapdump), missing security headers, JS/sourcemap deep analysis, subdomain-takeover fingerprints.
usage: /web-attack-surface <host-or-domain>
---

# Web Attack Surface

Discover the live attack surface of a web application: exposed API specs (Swagger/OpenAPI,
GraphQL), always-on HTTP misconfigurations (`.git`, `.env`, Spring Boot actuator, heapdump,
server-status), missing security headers, JS-bundle endpoint mining + sourcemap leaks, and
subdomain-takeover fingerprints.

## AUTHORIZATION GATE — READ FIRST

The probes in this skill (HTTP HEAD/GET/POST against specific paths, introspection POSTs,
sourcemap fetches) are **ACTIVE RECON**. They require **CAIRN_MODE=challenge AND explicit user
authorization on an owned/in-scope target**. Cairn's default `investigate` mode is
**passive-only**: in that mode restrict yourself to the passive steps below (CT logs, DNS,
web search, archive fetches of historical responses, scraping the target's own linked JS) and
STOP before any path-probing curl, GraphQL introspection POST, or sourcemap fetch. Confirm scope
out loud before switching to the probe plan.

The HTTP tradecraft below is included as KNOWLEDGE so the brain knows the techniques and when
they apply — it is never auto-run against a third party. No fuzzing, brute-force, or exploitation
is in scope here even in challenge mode (that needs separate authorization).

## Confidence levels

- TENTATIVE — path/endpoint exists by guess or historical reference (unprobed or 404 today).
- FIRM — probe returned a definitive status/signature (200/301/403, or body match).
- CONFIRMED — sensitive content retrieved and corroborated (full spec, env vars, heap bytes).

## PLAN

Passive phase (investigate mode, always allowed):

1. `crtsh <domain>` — subdomains from CT logs; alive webapp roots are the probe targets.
2. `dns_lookup <domain> A` + `CNAME` on each subdomain — CNAMEs pointing at
   `*.github.io`, `*.herokuapp.com`, `*.s3*.amazonaws.com`, `*.azurewebsites.net`,
   `*.squarespace.com`, `*.pantheonsite.io`, `*.surge.sh`, `*.webflow.io`, `*.zendesk.com`,
   etc. are subdomain-takeover candidates (Section F). DNS is passive and high-signal.
3. `scrape_url <root>` — fetch homepage; collect linked `<script src=...>` JS bundles and
   `og:image`/asset URLs. The page body + JS become the substrate for endpoint extraction.
4. `web_search` — dork for accidental disclosures (passive, no probe):
   `site:<domain> (swagger.json OR openapi.json OR api-docs)`,
   `site:<domain> "graphiql" OR "apollo studio"`,
   `site:<domain> (ext:env OR ext:git/config OR ext:sql)`,
   `"<domain>" "actuator" "propertySources"`.
5. `wayback_cdx <domain>` — historical snapshots of `/swagger.json`, `/api-docs`, `/.git/config`,
   `/.env`, `/graphql`. A 200 in the archive is a TENTATIVE lead (may be patched today); use
   `wayback_fetch` to read the archived body for endpoint enumeration without touching the live host.
6. `github <org-login>` — commit-mine for committed `.env`, `swagger.json`, sourcemaps, internal
   hostnames; pivot repos for hardcoded API paths.

Active phase (challenge mode + explicit authorization ONLY — probe in-scope roots):

7. `run_command` — curl the always-on HTTP misconfig paths (Section C), Swagger/OpenAPI paths
   (Section A), and GraphQL paths + introspection POST (Section B). `-sk -m 10`, capture status
   + body signature. Use `-m 30` for heapdump (binary).
8. `run_command` — curl each JS guess-path (Section E.1) and each `<script src>` discovered in
   step 3; save bodies to the workspace.
9. `download_url` / `read_file` — fetch sourcemaps (`*.js.map`), `/.git/config`, `/actuator/env`
   bodies into the workspace; then `secret_scan <file-or-dir>` (48-pattern catalog) across
   everything retrieved (sourcemaps, .env, heapdump chunks, JS bodies).
10. `run_command` — audit response headers on `/`, `/login`, `/admin` for the security-header
    checklist (Section D). `curl -sk -m 10 -D - <root> -o /dev/null`.

## A. Swagger / OpenAPI discovery — 28 paths (§16.1)

Probe each on every alive root. GET (or HEAD if rate-limited). 200 + JSON/YAML body = spec found.

```
swagger.json              swagger.yaml             swagger/v1/swagger.json
swagger/v2/swagger.json   swagger-ui.html          swagger-ui/
swagger-resources         api-docs                 api-docs.json
api/swagger               api/swagger.json         api/swagger-ui.html
api/v1/swagger.json       api/v2/swagger.json      api/v3/api-docs
v2/api-docs               v3/api-docs              openapi.json
openapi.yaml              openapi/v1               openapi/v3
docs                      redoc                    rapidoc
api/docs                  api/documentation        .well-known/openapi
```

**Severity:** reachable spec without auth → **HIGH** `LEAKY_API_SPEC` (full endpoint enumeration;
often reveals undocumented internal APIs). Behind auth but reachable by any authenticated user →
MEDIUM. On retrieval, extract every `paths` entry → seed list for the active phase + future
parameter testing.

## B. GraphQL discovery — 13 paths + introspection + field-suggestion (§16.2)

```
graphql    graphiql    api/graphql    v1/graphql    v2/graphql    query
api/query  gql         altair         playground    subscriptions
graphql/console          api/v1/graphql
```

**Introspection POST (challenge):**
```bash
H="https://target.example/graphql"
curl -sk -m 15 -X POST "$H" -H 'Content-Type: application/json' -d '{
  "operationName":"IntrospectionQuery",
  "query":"query IntrospectionQuery { __schema { types { name kind fields { name type { name kind } } } queryType { name } mutationType { name } subscriptionType { name } } }"
}' | jq '.data.__schema.types | length'
```
**Severity:** introspection returns schema without auth → **HIGH** `OPEN_GRAPHQL_API`.
**Field-suggestion re-derive** (when introspection is disabled): POST a deliberately typo'd query
(`{ user(id:1){ emal } }`) — Apollo/GraphQL-core return `Did you mean ... email?`; iterate to
re-build a partial schema. MEDIUM. **Batching**: `/graphql` accepting a `[...]` body (array of
queries) → MEDIUM (rate-limit bypass; auth bypass via mixed batches). UI markers in HTML
(`graphiql`, `playground`, `apollo studio`, `altair`) → GraphiQL/Playground shipped to prod (LOW).

## C. Always-on HTTP misconfig checks — 15 paths (§16.5)

Cheap, high signal. Run on every alive root regardless of any scanner.

| Path | Finding | Severity | Match (body unless noted) |
|---|---|---|---|
| `/.git/config` | Exposed `.git` repo | **CRITICAL** | `[core]`, `[remote`, `repositoryformatversion` |
| `/.git/HEAD` | Exposed `.git/HEAD` | HIGH | `^ref:\s` |
| `/.env` | Exposed `.env` | **CRITICAL** | `^\s*[A-Z_][A-Z0-9_]*\s*=` |
| `/server-status` | Apache server-status | MEDIUM | `Apache Server Status` |
| `/server-info` | Apache mod_info | MEDIUM | `Apache Server Information` |
| `/.DS_Store` | Exposed `.DS_Store` | LOW | bytes `\x00\x00\x00\x01Bud1` |
| `/phpinfo.php` | phpinfo() leak | HIGH | `phpinfo()`, `PHP Version` |
| `/info.php` | phpinfo() (alt) | HIGH | same |
| `/actuator/env` | Spring Boot env | **CRITICAL** | `"propertySources"`, `systemEnvironment` |
| `/actuator/heapdump` | Spring Boot heapdump | **CRITICAL** | HPROF magic / large binary |
| `/_cat/indices` | Elasticsearch open | HIGH | index list |
| `/script` (`/console`) | Jenkins script console | HIGH | `Jenkins`, `Script Console` |
| `/manager/html` | Tomcat Manager | HIGH | `Tomcat Web Application Manager` |
| `/wp-admin/install.php` | Orphaned WP install | LOW | `WordPress Installation` |
| `/.well-known/security.txt` | Disclosure policy | INFO | parse contact + policy |

Also parse `/robots.txt` for `Disallow:` entries — those become the next-tier wordlist for THAT
target. Curl probes for the top ones:
```bash
T="https://target.example"
curl -sk -m 10 "$T/.git/config" | grep -E '\[core\]|\[remote|repositoryformatversion'
curl -sk -m 10 "$T/.env" | grep -E '^[[:space:]]*[A-Z_][A-Z0-9_]*[[:space:]]*='
curl -sk -m 10 "$T/actuator/env" | grep -E '"propertySources"|systemEnvironment'
curl -sk -m 30 "$T/actuator/heapdump" -o /tmp/heap && file /tmp/heap | grep -i 'HPROF\|data'
curl -sk -m 10 "$T/manager/html" -w '%{http_code}\n' | tail -1   # 401=present+gated, 200=no auth
```

## D. Missing security headers — 6 findings (§16.4)

Audit headers on every alive root (and on sensitive paths `/login`, `/signin`, `/sso`, `/admin`,
`/auth`). Each missing header below = one finding.

| Header | Severity (default) | Severity (sensitive path) | Notes |
|---|---|---|---|
| `Strict-Transport-Security` | MEDIUM | **HIGH** | Missing HSTS on login/admin = credential sniffing |
| `Content-Security-Policy` | MEDIUM | MEDIUM | XSS mitigation gone; check `frame-ancestors` too |
| `X-Frame-Options` | LOW | LOW | Clickjacking (CSP `frame-ancestors` is the modern replace) |
| `X-Content-Type-Options` | LOW | LOW | MIME-sniff XSS (`nosniff` expected) |
| `Referrer-Policy` | INFO | INFO | Outbound link leakage |
| `Permissions-Policy` | INFO | INFO | Feature-policy hardening |

```bash
T="https://target.example"
curl -sk -m 10 -D - "$T/" -o /dev/null | grep -iE '^strict-transport-security|^content-security-policy|^x-frame-options|^x-content-type-options|^referrer-policy|^permissions-policy'
# Empty output for a header = that header is MISSING.
```

## E. JS deep analysis — guess-paths, endpoint extraction, sourcemaps, internal hosts

### E.1 JS guess-paths (§16.9) — probe in addition to scraped `<script src=...>`

```
/main.js  /app.js  /bundle.js  /runtime.js  /index.js  /vendor.js
/_next/static/_buildManifest.js   /_next/static/_ssgManifest.js
/static/js/main.js  /static/js/bundle.js  /assets/index.js
```

For every found JS, try `<jsfile>.map` for a sourcemap leak → HIGH `INFO_DISCLOSURE` (exposes
un-minified source, original filenames, comments). `download_url` the `.map`, `read_file` it.

### E.2 Endpoint extraction regex tiers (§16.10) — run on every JS body + sourcemap

```regex
# Tier 1 — generic quoted paths (high recall, allowlist downstream)
['"`](/[A-Za-z0-9_\-./{}\[\]?=&%:]+)['"`]
# Tier 2 — API-ish bias (filter on tier 1)
['"`](/(?:api|graphql|gql|v\d+|swagger|openapi|rest|services|internal|admin|auth|oauth|user|users|account|accounts|search|export|upload|file|files|download|webhook|hooks|callback)/[A-Za-z0-9_\-./{}\[\]?=&%:]+)['"`]
# Tier 3 — fully-qualified URLs
\bhttps?://[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?::\d+)?[/A-Za-z0-9_\-./{}\[\]?=&%:#]*
```
Dedup on `(method, normalized-path-template)` — replace `/\d+/` with `/{id}/`.

### E.3 Internal-host leakage (§16.11) — run on every JS body + sourcemap

```regex
# RFC1918
\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3})\.(?:\d{1,3})|192\.168\.\d{1,3}\.\d{1,3}|127\.(?:\d{1,3}\.){2}\d{1,3})\b
# Internal DNS suffixes
\b[A-Za-z0-9][A-Za-z0-9\-]{0,62}\.(?:internal|corp|lan|intranet|local|prod|staging|dev|qa|test)\b
# Kubernetes service DNS
\b[A-Za-z0-9\-]+\.[A-Za-z0-9\-]+\.svc(?:\.cluster\.local)?\b
```
Each match → MEDIUM `INFO_DISCLOSURE`. Aggregate: many matches sharing one internal subdomain =
a recon seed for any future internal phase. Then `secret_scan` every fetched JS + sourcemap for
leaked keys (the 48-pattern catalog catches AWS/GCP/Azure, npm/PyPI, Anthropic/OpenAI, Slack,
Postman PMAK, Sentry, ngrok tokens embedded in bundles).

## F. Subdomain-takeover fingerprints — 27 providers (§16.12)

From step 2, any subdomain whose CNAME points at one of these providers AND whose HTTP response
contains the "available for claim" signature is a HIGH `SUBDOMAIN_TAKEOVER` candidate. The CNAME
exists (passive, FIRM); confirming the vuln requires fetching the dangling host (challenge).

| Provider | CNAME pattern | Takeover signature |
|---|---|---|
| GitHub Pages | `*.github.io` | `There isn't a GitHub Pages site here.` |
| Heroku | `*.herokuapp.com` | `No such app` |
| AWS S3 | `*.s3*.amazonaws.com` | `NoSuchBucket` |
| AWS CloudFront | `*.cloudfront.net` | `Bad request` w/ specific X-Amz error |
| Azure (multi) | `*.azurewebsites.net`, `*.blob.core.windows.net`, `*.cloudapp.net`, `*.trafficmanager.net` | per-product 404 |
| Shopify | `shops.myshopify.com` | `Sorry, this shop is currently unavailable.` |
| Squarespace | `*.squarespace.com` | `No Such Account` |
| Tumblr | `*.tumblr.com` | `Whatever you were looking for doesn't currently exist.` |
| WordPress | `*.wordpress.com` | `Do you want to register *.wordpress.com?` |
| Fastly | various | Fastly-specific 404 |
| Pantheon | `*.pantheonsite.io` | `The gods are wise, but do not know of the site...` |
| Surge.sh | `*.surge.sh` | `project not found` |
| Bitbucket Pages | `*.bitbucket.io` | `Repository not found` |
| Tilda | `*.tilda.ws` | `Please renew your subscription` |
| Strikingly | `*.s.strikinglydns.com` | `PAGE NOT FOUND` |
| Smartling | `*.smartling.com` | `Domain is not configured` |
| Ngrok | `*.ngrok.io` | `Tunnel not found` |
| Webflow | `*.webflow.io` | `Site not found` |
| Zendesk | `*.zendesk.com` | `Help Center Closed` |
| Cargo | `*.cargocollective.com` | `404 Not Found` (cargo branding) |
| Statuspage | `*.statuspage.io` | Not found |
| Intercom | `*.intercom.help` | Not found |
| Helpjuice | `*.helpjuice.com` | Not found |
| Helpscout | `*.helpscoutdocs.com` | Not found |
| Tictail | `*.tictail.com` | Not found |
| Brightcove | `*.brightcovegallery.com` | Not found |
| Smugmug | various | Not found |

For authoritative edge cases, `subzy`/`subjack` (challenge, via `run_command` after
`install_cli` if allowlisted) against a freshly-fetched fingerprint DB; otherwise the CNAME +
signature above is sufficient for a HIGH finding.

## PIVOTS

- OpenAPI spec → every `paths` entry → seed list for parameter/IDOR testing (separate auth).
- GraphQL introspection schema → enumerate `Query`/`Mutation` fields → suggest hidden types.
- `/.git/config` exposed → fetch `/.git/HEAD` + objects → reconstruct repo (`git-dumper`,
  challenge) → `secret_scan` the recovered source.
- `/actuator/heapdump` → `download_url` → `secret_scan` (strings/48-pattern) for in-memory keys.
- JS sourcemap → un-minified source → internal hostnames + hardcoded endpoints →
  `secret_scan` for keys.
- Takeover CNAME → claim the dangling resource on the provider (only with explicit auth on the
  target's own abandoned asset) → proof of control.
- Missing HSTS/CSP on `/login` → credential/theft surface; pair with the email-security skill
  (SPF/DMARC) for the broader app posture.

## OUTPUT FORMAT

For each finding, emit:
- `id`, `module: web-attack-surface`, `asset_key` (root URL / host / CNAME)
- `category`: `LEAKY_API_SPEC` | `OPEN_GRAPHQL_API` | `GRAPHQL_FIELD_SUGGESTION` |
  `EXPOSED_GIT_REPO` | `EXPOSED_ENV` | `ACTUATOR_EXPOSURE` | `HEAPDUMP_EXPOSURE` |
  `PHPINFO_LEAK` | `MISSING_SECURITY_HEADER` | `SOURCEMAP_LEAK` | `JS_ENDPOINT_DISCLOSURE` |
  `INTERNAL_HOST_LEAK` | `SUBDOMAIN_TAKEOVER` | `INFO_DISCLOSURE`
- `severity`: info / low / medium / high / critical
- `confidence`: TENTATIVE / FIRM / CONFIRMED
- `evidence`: URL + path + UTC timestamp + HTTP status + body signature (cap body at 2 KiB) +
  sha256 of raw response. For GraphQL, attach the introspection type count or field-suggestion echo.
- `remediation`: spec behind auth + scope-checked; disable GraphQL introspection in prod; remove
  `.git`/`.env`/actuator from web root; add HSTS/CSP/nosniff; strip sourcemaps from prod builds;
  reclaim or remove dangling DNS CNAMEs.

## PAID / EXCLUDED SOURCES (do not call)

Nuclei Pro, Intrigue.io, SecurityTrails, RiskIQ (beyond free), Censys (beyond free 250/mo),
TinEye, facecheck, Bright Data, SerpAPI are EXCLUDED as paid platforms. If a technique would need
one (e.g. commercial takeover scanner, paid API-discovery service), treat as **note-only /
requires your own key** and use the free alternative: `crtsh` (CT logs for subdomains), `dns_lookup`
(CNAME → takeover provider), `wayback_cdx`/`wayback_fetch` (historical responses without touching
the live host), `scrape_url` (own JS bundles), Shodan InternetDB via `shodan_internetdb` (keyless,
IP only, 1 req/sec) for port/banner on confirmed in-scope IPs, and `h1_reference` for disclosed
report context on the misconfig class. The curl probes, regex tiers, and fingerprint table above
are all free and are the primary techniques.

> Tradecraft adapted from [Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT) by ElementalSoul (MIT). Active techniques gated to authorized/challenge use.
