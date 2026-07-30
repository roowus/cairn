---
name: identity-fabric-sso
description: Map an org's identity fabric / SSO — fingerprint the IdP (Entra, Okta, ADFS, Google Workspace, generic OIDC/SAML), extract tenant IDs, and infer SaaS tenancies from DNS. Passive-first; active user-enum gated.
usage: /identity-fabric-sso <domain>
---

# Identity fabric / SSO mapping

Objective: identify which Identity Provider (IdP) owns authentication for a
domain, extract the tenant/slug/issuer identifier, enumerate SSO-exposed
subdomains, and inventory the SaaS tenancies implied by DNS — passive-first.

## Authorization (read first)

This skill is PASSIVE-BY-DEFAULT. Discovery techniques (OIDC discovery docs,
SAML metadata, `getuserrealm`, DNS) fetch published endpoints or public DNS and
are permitted in Cairn's default investigate mode. The **user-enumeration**
techniques (Microsoft `GetCredentialType`, Okta `/api/v1/authn`, per-user
SharePoint/OneDrive probes) are ACTIVE — they are logged in the target tenant's
audit trail and reveal whether specific accounts exist. **Active
scanning/exploitation/fuzzing/brute-force/user-enum requires `CAIRN_MODE=challenge`
AND explicit user authorization on an owned/in-scope target; Cairn's default
investigate mode is passive-only.** When scope is unclear, surface the question
and stop at the passive map.

## Gating matrix (which tool, which mode)

| Technique | Passive? | Cairn route |
|---|---|---|
| DNS MX/TXT/SPF → IdP inference | yes | `dns_lookup` (investigate) |
| `autodiscover.<domain>` A → M365 confirm | yes | `dns_lookup` (investigate) |
| OIDC discovery `/.well-known/openid-configuration` | yes (published doc) | `scrape_url` (investigate) |
| SAML metadata GET (5 paths) | yes (published doc) | `scrape_url` (investigate) |
| Entra `getuserrealm.srf` (domain / one probe user) | low detectability | `scrape_url` (investigate) — per-real-user probing edges toward enum |
| ADFS `/adfs/Services/Trust/mex` | low (metadata) | `scrape_url` (investigate) |
| AWS ARN / OAuth client_id harvest from JS | yes | `scrape_url` + `secret_scan` |
| Microsoft `GetCredentialType` POST | **NO — active user-enum** | `run_command` curl, challenge+authorized only |
| Okta `/api/v1/authn` POST | **NO — active user-enum** | `run_command` curl, challenge+authorized only |
| SharePoint/OneDrive per-user probe | low-active (per-user) | `run_command`, challenge+authorized |

## Plan

1. **Seed + IdP inference from DNS (parallel, passive):**
   - `whois_rdap <domain>` → registrar, org, created date (tenant-age context).
   - `dns_lookup MX <domain>` → mail provider = strongest single IdP signal
     (table below).
   - `dns_lookup TXT <domain>` → SaaS verification tokens
     (`MS=ms…`, `google-site-verification=`, `atlassian-domain-verification=`,
     `zscaler-verification-…`, `zoom_verify_…`, `workday-domain-verification=`,
     `adobe-idp-site-verification=`, `slack-domain-verification=`). Each token
     is a separate SaaS attack surface.
   - `dns_lookup A autodiscover.<domain>` → if it lands in Microsoft Exchange
     Online IP space, M365 is confirmed **even when MX is hidden behind
     Mimecast/Proofpoint/Barracuda**.
   - `crtsh <domain>` → subdomains; filter for SSO prefixes below.
2. **SSO subdomain discovery (passive):**
   - Filter crtsh output for the 8 prefixes: `auth. login. sso. idp. iam.
     identity. accounts. oauth.<domain>`, plus ADFS conventions (`adfs. sts. fs.`)
     and Okta vanity (`okta.`, `sso.`).
   - `dns_lookup CNAME sso.<domain>` / `okta.<domain>` → vanity CNAME to
     `<slug>.okta.com` reveals the Okta slug directly.
   - `wayback_cdx <domain>/adfs*` and `*/.well-known/openid-configuration` for
     historical SSO endpoints removed from live DNS.
3. **OIDC discovery sweep (passive):** `scrape_url` the root + every alive SSO
   subdomain for `/.well-known/openid-configuration` (and `/v2.0/...` for M365).
   The `issuer` field fingerprints the product (table below).
4. **SAML metadata sweep (passive):** `scrape_url` the 5 SAML paths on the root
   + `adfs.`/`sts.` subdomains.
5. **Provider-specific tenant extraction (passive):** pull Entra GUID / Okta
   slug / Google issuer / SAML EntityID (sections below).
6. **Cross-tenant cloud-ID correlation (passive):** `scrape_url` the main
   webapp + JS bundles into the workspace; run `secret_scan` over the downloads
   to surface AWS account IDs (ARNs), Google OAuth `client_id`s, MSAL
   `client_id`s, OAuth `scope`s.
7. **Reference prior art (passive):** `h1_reference entra`, `h1_reference
   okta`, `h1_reference sso`, `h1_reference oauth`, `h1_reference saml` for
   disclosed reports naming this org's (or a similar) IdP misconfig.
8. **ACTIVE confirmation (challenge+authorized only):** user-enum against the
   discovered tenant to validate candidate emails (provider sections). Default
   investigate mode: skip and leave the map as tentative/firm.

## MX → IdP inference table

| MX pattern | IdP / mail host | Identity implication |
|---|---|---|
| `aspmx.l.google.com` | Google Workspace | Google Workspace = likely IdP; expect `accounts.google.com` issuer |
| `*.mail.protection.outlook.com` / `*.mail.eo.outlook.com` | Microsoft 365 | Entra ID tenant — extract GUID |
| Self-hosted IPs in target ASN (via `ripestat`) | On-prem Exchange | Often fronted by ADFS; check `/adfs/idpinitiatedsignon.aspx` |
| `*.mimecast.com` / `*.proofpoint.com` / `*.pphosted.com` / `*.barracudanetworks.com` | Mail filter wrapping real host | MX hides the platform — confirm via `autodiscover.<domain>` A record |
| (filter on MX, autodiscover→MS IPs) | M365 behind filter | `M365_CONFIRMED` via autodiscover IP |

Microsoft Exchange Online common ranges (truncated): `40.96.0.0/13`,
`52.96.0.0/14`, `13.107.6.152/31`, `13.107.18.10/31`, `40.99.0.0/16`,
`40.104.0.0/15`, `52.98.0.0/15`. Full list: learn.microsoft.com
Office 365 URLs and IP ranges.

## Provider playbooks

### Microsoft Entra (Azure AD)

Tenant GUID (passive):
```
GET https://login.microsoftonline.com/<domain>/.well-known/openid-configuration
  → .issuer contains the tenant GUID
```
GUID regex over the scraped body:
`\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b`

Managed vs federated (passive, low detectability):
```
GET https://login.microsoftonline.com/getuserrealm.srf?login=<probe-user>@<domain>
  → .NameSpaceType: Managed | Federated | Unknown
     Federated also returns .FederationBrandName + .AuthURL (upstream IdP — pivot!)
```

ACTIVE user-enum (challenge + authorized only) — `GetCredentialType`:
```
POST https://login.microsoftonline.com/common/GetCredentialType
{"username":"<email>","isOtherIdpSupported":true,"isRemoteNGCSupported":true,
 "isFidoSupported":true,"country":"US","federationFlags":0}
  → .IfExistsResult: 0=exists, 1=absent, 5=exists-in-federated-tenant
```
Detectability: medium (tenant audit log). Cap ~20 attempts/tenant.
**Default investigate mode: do not run.**

### Okta

Slug derivation (passive): stems from root domain + discovered subdomains; probe
`<slug>.okta.com` and `<slug>.oktapreview.com`. `dns_lookup CNAME` on
`okta.<domain>`/`sso.<domain>` vanity hosts often yields the slug directly.
Slug regex: `[a-z0-9][a-z0-9-]{1,40}\.okta(?:preview)?\.com`

OIDC fingerprint (passive):
`GET https://<slug>.okta.com/.well-known/openid-configuration`

ACTIVE user-enum (challenge + authorized only) — `/api/v1/authn`:
```
POST https://<slug>.okta.com/api/v1/authn
{"username":"<email>","password":"<intentionally-invalid-for-enum>"}
  → 400 E0000004 = absent (or generic password error);
     401 PASSWORD_WARN|LOCKED_OUT|MFA_REQUIRED = exists
```
Detectability: medium (audit-log per attempt). Cap ~20/tenant.
**Default investigate mode: do not run.**

### ADFS

Passive fingerprint:
`GET https://<domain>/adfs/idpinitiatedsignon.aspx` → 200 +
`urn:com:microsoft:ADFS:` reference confirms ADFS; version string greppable in
HTML resource refs.
Mex endpoint (metadata, low): `GET https://<domain>/adfs/Services/Trust/mex`
→ SOAP federation metadata (endpoints, signing certs, claim types).

### Google Workspace

OIDC discovery (passive):
`GET https://<domain>/.well-known/openid-configuration` → `issuer` of
`https://accounts.google.com` + JWKS URI. Corroborate with `aspmx.l.google.com`
MX (≥2 signals → firm).

### Generic OIDC (Keycloak / Auth0 / Ping / OneLogin / Duo)

Probe `/.well-known/openid-configuration` on every alive subdomain. Fingerprint
by `issuer`:

| Product | `issuer` pattern |
|---|---|
| Auth0 | `https://*.auth0.com` |
| OneLogin | `https://*.onelogin.com` |
| Ping | `https://*.pingone.com` / `*.pingidentity.com` |
| Duo | `https://*.duosecurity.com` |
| Keycloak | URL contains `/realms/<realm>` |

### SAML metadata — 5 paths (passive)

```
/saml/metadata
/FederationMetadata/2007-06/FederationMetadata.xml
/federationmetadata/2007-06/federationmetadata.xml
/simplesaml/saml2/idp/metadata.php
/auth/saml2/metadata
```
Extract: `EntityID`, signing certs (cert-reuse pivot), `SingleSignOnService`
URL, `NameIDFormat`. LOW `MISCONFIG`; escalate to MEDIUM if metadata leaks
internal hostnames or non-public certs.

### AWS account-ID + OAuth client extraction (passive, from JS/scrape)

ARN: `arn:aws:[a-z0-9\-]+:[a-z0-9\-]*:([0-9]{12}):`
AccountId property: `(?i)["']?account[_\-]?id["']?\s*[:=]\s*["']([0-9]{12})["']`
Google OAuth client_id: `\b\d{8,}-[a-z0-9]{10,40}\.apps\.googleusercontent\.com\b`
MSAL client_id (GUID): `(?i)["']?client[_\-]?id["']?\s*[:=]\s*["']([0-9a-f-]{36})["']`
OAuth scope: `(?i)["']?scope["']?\s*[:=]\s*["']([^"']+)["']`
Run via `secret_scan` over downloaded JS/workspace artifacts.

### Microsoft 365 deep surface (passive; per-user parts gated)

- SharePoint tenant probe (passive, INFO): `https://<stem>.sharepoint.com/`,
  `<stem>-my.sharepoint.com/`, `<stem>-admin.sharepoint.com`. **Read result
  carefully:** HTTP 200 = tenant provisioned (Microsoft serves a generic
  auth-redirect page) — it does NOT mean anonymous content access. 401/403 =
  tenant exists, auth-required. 404 = not provisioned at this stem (try known
  stems from crtsh SANs).
- OneDrive personal site (per-user, low-active): `https://<stem>-my.sharepoint
  .com/personal/<user_token>/Documents/` → 401=exists, 404=not provisioned.
  `run_command`, challenge+authorized.
- Device-code phishing feasibility (passive): check
  `.device_authorization_endpoint` in OIDC metadata; non-null + no tenant
  restriction → MEDIUM.
- Power Platform/Dynamics: `*.crm.dynamics.com`, `*.api.crm.dynamics.com`.

## Pivots

- **Tenant key → breach intersection.** The Entra GUID / Okta slug / Google
  issuer is the join key. Cross-reference breach corpora (HudsonRock Cavalier
  free API by domain, HIBP via the keyed `hibp` plugin) for `<*>@<domain>`
  creds. Non-empty intersection → `SSO_EXPOSURE`, severity CRITICAL — even if
  the org migrated off legacy on-prem mail (stolen passwords survive via reuse).
- **Federated AuthURL → upstream IdP.** If `getuserrealm` returns `Federated`,
  the `AuthURL` points at the real IdP (often a `*.okta.com` or on-prem ADFS) —
  re-run the matching provider playbook there.
- **Cert SANs → vanity SSO hosts.** crtsh SANs reveal `login.<brand2>.com` /
  `sso.<subsidiary>.com` that live DNS doesn't surface.
- **TXT tokens → SaaS sprawl.** Each verification token is a separate identity
  surface (Atlassian, Zoom, Workday, Webex, Zscaler, Adobe) with its own
  credential store and MFA posture.
- **Shared client_id / ARN across subdomains** → confirms common ownership
  (rule of three for attribution; never single-source).

## Output

```
IDENTITY FABRIC — <domain>
IdP:          <Microsoft Entra | Okta | Google Workspace | ADFS | Keycloak | Auth0 | ...>
Tenant key:   <Entra GUID | Okta slug | Google issuer | SAML EntityID>  [tentative|firm|confirmed]
Evidence:     <OIDC issuer URL + MX + autodiscover IP, each cited to its tool>
Federation:   <Managed | Federated via <upstream IdP URL>>
SSO hosts:    <login.x, sso.x, ...>  (alive / dead-but-in-CT)
SaaS tenants: <Atlassian, Zoom, Workday, ...> from TXT tokens
Cloud IDs:    <AWS acct 123456789012 | Google OAuth client_id | MSAL client_id>
ACTIVE-enum:  <not run — investigate mode>  (or: <N users confirmed, challenge+authorized>)
Severity:     INFO (map only) | CRITICAL if breach×tenant intersection
Next steps:   <hand off to breach-check skill; authorized user-enum if scoped>
```
Every fact cites its tool. Mark tenant-key `tentative` until ≥2 signals agree
(e.g. OIDC issuer + MX, or issuer + autodiscover IP).

## Sources & excluded platforms

Free-first: `dns_lookup`, `crtsh`, `whois_rdap`, `scrape_url`, `wayback_cdx`,
`secret_scan`, `h1_reference`, plus HudsonRock Cavalier free API, HIBP (keyed
plugin), Shodan InternetDB, urlscan, RIPEstat. **Excluded (paid):**
SecurityTrails, DomainTools, RiskIQ (beyond free), Censys (beyond free),
WhoisXML API, Hunter.io, DeHashed, IntelX paid. Where the source technique
needs a paid source (e.g. SecurityTrails DNS history of an SSO host), it is
**note-only / requires your own key** — use `crtsh` + `wayback_cdx` +
`dns_lookup` as the free alternative.

> Tradecraft adapted from [Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT) by ElementalSoul (MIT). Active techniques gated to authorized/challenge use.
