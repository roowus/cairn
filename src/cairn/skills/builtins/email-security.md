---
name: email-security
description: Audit email-spoof feasibility (SPF/DMARC/DKIM/BIMI/MTA-STS/TLS-RPT/DNSSEC) and infer SaaS tenants from a domain's email DNS records.
usage: /email-security <domain>
---

# Email-Security Audit — Spoof Feasibility + SaaS-Tenant Inference

**Objective:** From one domain, determine (a) whether external parties can spoof mail from it (SPF/DMARC/DKIM posture), (b) whether MX→TLS is enforced (MTA-STS/TLS-RPT), (c) whether DNSSEC protects resolution, and (d) which SaaS/IdP tenants the org tied to the domain (TXT verification-token catalog + MX + SPF includes). All core lookups are passive public-DNS / public-WHOIS queries — no mail is sent and no SMTP banners are probed.

## PLAN

1. **Confirm domain + ownership.** Call `whois_rdap <domain>` for registrant, registrar, created/updated/expiry, NS, abuse contact. Capture NS — they gate every later lookup and identify the DNS provider (Cloudflare / Route 53 / Azure DNS / Gandi / etc.).
2. **Dump the full DNS record suite.** Call `dns_lookup <domain>` for each of `A`, `AAAA`, `MX`, `TXT`, `NS`, `SOA`, `CAA`, `SRV`, `CNAME`. Aggregate every TXT record into one corpus — most of this skill pivots on TXT.
3. **Parse SPF.** From the TXT corpus, extract the `v=spf1` record. Walk every `include:`, `a`, `mx`, `exists:`, and `redirect=` mechanism by recursing `dns_lookup <target> TXT`. Track lookup count against the RFC-7208 10-lookup limit.
4. **Parse DMARC.** Call `dns_lookup _dmarc.<domain> TXT`. Parse `p=`, `sp=`, `aspf=`, `adkim=`, `pct=`, `rua=`, `ruf=`, `fo=`.
5. **Discover DKIM selectors.** Call `dns_lookup <selector>._domainkey.<domain> TXT` over the selector wordlist below. From any hit, extract `p=<base64>`, decode, and check key length.
6. **BIMI.** Call `dns_lookup default._bimi.<domain> TXT`. If present, capture `l=` (logo URL) and `a=` (VMC cert URL).
7. **MTA-STS.** Call `dns_lookup _mta-sts.<domain> TXT` for the `id=` pointer; then `scrape_url https://mta-sts.<domain>/.well-known/mta-sts.txt` for the policy body. Parse `mode=` (enforce / testing / none), `mx:` list, `max_age=`.
8. **TLS-RPT.** Call `dns_lookup _smtp._tls.<domain> TXT`. Parse `rua=` (`mailto:` or `https:`).
9. **DNSSEC.** Call `dns_lookup <domain> SOA`; in challenge mode, `run_command "dig +dnssec <domain> SOA"` and `run_command "delv <domain>"` to distinguish "fully validated" (signed) from "insecure".
10. **MX → IdP / mail-host inference.** Match MX hosts from step 2 against the table below.
11. **SaaS-tenant catalog.** Match the full TXT corpus against the 35+ token table below. Each match = one SaaS tenancy.
12. **DMARC reporting-vendor inference.** Match `rua=` / `ruf=` from step 4 against the vendor table.
13. **Cross-tenant correlation.** For each SaaS tenant, note whether its IdP is implied by MX/SPF (e.g. M365 MX + `atlassian-domain-verification` + `MS=` on the same domain ⇒ single Entra tenant). Flag any tenant whose vendor also supplies DMARC reporting — vendor compromise = DMARC bypass surface.
14. **Optional enrichment.** `web_search "<domain> email security"` for public posture claims or prior incident reports; `crtsh <domain>` for cert-SAN hostnames that hint at mail infra (`mta-sts.`, `autodiscover.`, `enterprise.`).

## SPF parse checklist

- `-all` (hardfail) — strict; major providers reject spoofs.
- `~all` (softfail) — spam folder for spoofs.
- `?all` / no `all` — permissive; spoofs likely deliver.
- Count `include:` / `a` / `mx` / `exists:` / `redirect=`; ≥10 lookups = SPF PermError ⇒ receivers fall back to no-SPF ⇒ spoofs may pass.
- Per-include SaaS tells (recurse each):
  - `include:_spf.google.com` → Google Workspace
  - `include:spf.protection.outlook.com` → Microsoft 365
  - `include:_spf.salesforce.com` → Salesforce
  - `include:mail.zendesk.com` → Zendesk
  - `include:sendgrid.net` → SendGrid
  - `include:mailgun.org` → Mailgun
  - `include:_spf.atlassian.net` → Atlassian Cloud
  - `include:amazonses.com` → AWS SES
  - `include:mktomail.com` → Marketo
  - `include:_spf.intuit.com` → Intuit (QuickBooks/Mailchimp)
  - `include:spf.mandrillapp.com` → Mandrill
  - `include:_spf.workday.com` → Workday
  - `include:_spf.protonmail.ch` → Proton Mail
  - `include:spf.postmarkapp.com` → Postmark

## DMARC severity matrix

| Posture | Severity | Note |
|---|---|---|
| No `_dmarc` record at all | **HIGH** | spoof-feasible; no signal to receivers |
| `p=none` | **MEDIUM** | monitoring-only; spoof-feasible |
| `p=quarantine pct<100` | **LOW** | partial enforcement |
| `p=quarantine pct=100` + `aspf=s` + `adkim=s` | info | acceptable |
| `p=reject pct=100` + `aspf=s` + `adkim=s` | info | well-postured |
| `p=reject` but `sp=` absent on org owning many subdomains | **MEDIUM** | subdomain policy defaults to `p=`, but flag for review |

## DKIM selector wordlist

```
default google selector1 selector2 selector3 mail email k1 k2 dkim s1 s2 mta1 mta2
amazonses 20240101 20230101 20250101 mailchimp sendgrid mxvault zoho zmail
outlook o365 protonmail mailgun postmark mandrill googleapps rsa1 rsa2 selector
phishprotection proofpoint ess pps1 pps2
```

Key-length verdict: RSA-1024 → **MEDIUM** (deprecated; should be ≥2048). RSA-2048+ → info. Ed25519 → info (modern). Missing key on a known-selector → **LOW** (signing gap; recipients can't verify).

## BIMI / MTA-STS / TLS-RPT

- **BIMI**: present + `p=reject` DMARC = brand-impersonation defense in inbox UI. Absence is **LOW** only (operational, not exploitable). Pull `l=` (logo) and VMC cert chain (`a=`) if curious.
- **MTA-STS**: neither the DNS record nor the policy file at `https://mta-sts.<domain>/.well-known/mta-sts.txt` → STARTTLS not enforced, downgrade/MITM-able → **LOW**. `mode=enforce` + matching `mx:` list → well-postured. `mode=testing` → advertised but not enforced.
- **TLS-RPT**: absent → info (no TLS-failure reporting). Present → check `rua=` for vendor (often dmarcian/Valimail/EasyDMARC).

## DNSSEC

- `run_command "dig +dnssec <domain> SOA"` shows the AD flag and RRSIG if signed.
- `run_command "delv <domain>"` prints "fully validated" (signed) or "insecure" (no DNSSEC).
- "insecure" → **LOW** (hardening gap; does not enable spoof by itself).

## MX → IdP / mail-host inference

| MX host pattern | IdP / hosting |
|---|---|
| `aspmx.l.google.com`, `*.googlemail.com` | Google Workspace |
| `*.mail.protection.outlook.com` | Microsoft 365 |
| `*.mail.eo.outlook.com` | M365 (Exchange Online Protection, older) |
| `*.zoho.com` | Zoho Mail |
| `*.yandex.net` | Yandex 360 |
| `*.fastmail.com` | Fastmail |
| `*.proofpoint.com`, `*.pphosted.com` | Proofpoint (often M365 downstream) |
| `*.mimecast.com`, `*.mimecast-eu.com` | Mimecast |
| `*.barracudanetworks.com` | Barracuda |
| `*.icewarp.com` | IceWarp |
| Self-hosted IPs in target's own ASN | On-prem mail (often Exchange) |

## TXT verification-token catalog (35+ SaaS tenants)

Match each against the full TXT corpus from step 2. Each hit = a SaaS tenant on the domain.

| TXT pattern | SaaS / service |
|---|---|
| `google-site-verification=<token>` | Google Workspace / Search Console / Analytics |
| `MS=ms<digits>` | Microsoft 365 (older format) |
| `mscid=<token>` | Microsoft (newer M365 verification) |
| `apple-domain-verification=<token>` | Apple Business Manager |
| `atlassian-domain-verification=<token>` | Atlassian Cloud |
| `facebook-domain-verification=<token>` | Facebook Business / Pixel |
| `adobe-idp-site-verification=<token>` | Adobe Sign / Creative Cloud |
| `docusign=<token>` | DocuSign |
| `dropbox-domain-verification=<token>` | Dropbox Business |
| `box-verification=<token>` | Box |
| `webexdomainverification.<id>` | Cisco Webex |
| `cisco-ci-domain-verification=<token>` | Cisco Spark / Webex |
| `cisco-site-verification=<token>` | Cisco (various) |
| `zoom_verify_<id>` | Zoom |
| `notion=<token>` | Notion workspace |
| `slack-domain-verification=<token>` | Slack Enterprise Grid |
| `asana-domain-verification=<token>` | Asana Enterprise |
| `mongodb-site-verification=<token>` | MongoDB Atlas |
| `_dnsauth.<token>` | ACME / Let's Encrypt DNS-01 challenge |
| `pinterest-site-verification=<token>` | Pinterest Business |
| `_globalsign-domain-verification=<token>` | GlobalSign CA |
| `mailru-verification:<token>` | Mail.ru |
| `yandex-verification:<token>` | Yandex services |
| `zscaler-verification-<id>-<date>-<rand>` | Zscaler (ZIA/ZPA/ZDX) — date is verify-issued |
| `cloudflare-verify=<token>` | Cloudflare Zero Trust / Access |
| `_amazonses=<token>` | AWS SES sender verification |
| `salesforce-domain-verification=<token>` | Salesforce |
| `workday-domain-verification=<token>` | Workday (HR + Finance) |
| `shopify-domain-verification=<token>` | Shopify |
| `klaviyo-domain-verification=<token>` | Klaviyo |
| `mailchimp-domain-verification=<token>` | Mailchimp |
| `hubspot-domain-verification=<token>` | HubSpot |
| `zendesk-verification=<token>` | Zendesk (support) |
| `freshworks-verification=<token>` | Freshworks |
| `intercom-verification=<token>` | Intercom |
| `loom-site-verification=<token>` | Loom |
| `miro-site-verification=<token>` | Miro |
| `gitlab-domain-verification=<token>` | GitLab |
| `stripe-verification=<token>` | Stripe |
| `wix-site-verification=<token>` | Wix |

Each tenant is a separate attack surface: own credentials, own MFA posture, own data store. Cross-reference with `github`, `holehe`, and (where keyed) `hibp` to find employee logins on each.

## DMARC reporting-vendor inference (parse `rua=` / `ruf=`)

| RUA/RUF host | Vendor | Implication |
|---|---|---|
| `*.dmarcian.com` | dmarcian | DMARC reporting customer |
| `*.valimail.com`, `*.dmarc-rua.com` | Valimail | DMARC reporting customer |
| `*.kdmarc.com` | Kratikal kDMARC | IN-region vendor |
| `*.agari.com` | Agari (Fortra) | Email-security vendor |
| `*.easydmarc.com` | EasyDMARC | DMARC reporting customer |
| `*.dmarcanalyzer.com` | DMARC Analyzer | Reporting customer |
| `*.postmarkapp.com` | Postmark | Reporting addon |
| `<addr>@<target-domain>` | Self-hosted | Internal mailbox — sometimes leaks team-name (`itg@`, `secops@`, `dmarc@`, `postmaster@`) |

Both are leak surfaces: vendor compromise = DMARC bypass; internal RUA mailbox = phishing target.

## PIVOT on

- **SPF `include:` chain** → each new SaaS tenant. Recurse `dns_lookup` and accumulate.
- **MX host** → IdP tenant. Pair with `atlassian-domain-verification` + `MS=`/`mscid=` for a single-Entra-tenant picture.
- **TXT tokens** → SaaS tenants to enumerate (employee logins, OAuth client_ids, breach exposure).
- **`rua=` host** → DMARC vendor + internal security mailbox (phishing shortlist).
- **CAA records** → cert authorities the org uses (context for MTA-STS VMC issuer).
- **NS / SOA** → DNS provider; informs takeover feasibility if registrar lock is off.
- **WHOIS abuse contact + `/.well-known/security.txt`** (via `scrape_url`) → responsible-disclosure path if a finding warrants a report.
- **Historical posture** → `wayback_cdx https://mta-sts.<domain>/.well-known/mta-sts.txt` and `wayback_fetch` to date when DMARC/MTA-STS was added (patch-window context).

## OUTPUT / finding format

Emit one finding per posture gap and one inventory record per discovered SaaS tenant.

```
Finding:
  id:          emailsec-<domain>-<category>
  module:      email-security
  asset_key:   domain:<domain>
  category:    SPOOF_FEASIBLE | SPF_PERMERROR | DKIM_WEAK_KEY | MTA_STS_NONE | TLS_RPT_NONE | DNSSEC_NONE | SAAS_TENANT | DMARC_VENDOR_LEAK
  severity:    info|low|medium|high
  confidence:  firm           # DNS records are directly observed → firm by default
  title:       <one-line>
  description: <record value(s) + interpretation>
  evidence:
    record:    <full TXT/MX value>
    lookup:    dns_lookup <name> <type>
    timestamp: <UTC ISO8601>
  remediation: <concrete owner-side action>

Inventory (SaaS tenant):
  tenant:      <SaaS name>
  proof:       <TXT pattern matched>
  idp_link:    <MX/SPF-inferred IdP, or "unknown">
  confidence:  firm
```

UTC timestamps everywhere. Dedup tenants by (SaaS, token). Severity defaults: spoof-feasible (`p=none` or no DMARC) → MEDIUM/HIGH; well-postured → info; missing MTA-STS / DNSSEC → LOW.

## ACTIVE-PROBE GATING (critical)

Everything above is **passive**: DNS TXT/MX/TLS lookups, public WHOIS/RDAP, and a single HTTPS GET on a well-known policy file (`mta-sts.txt`). Cairn's default `investigate` mode permits all of it.

The following tradecraft is **knowledge only** — do NOT auto-run it:

- **Sending test spoof mail** to validate spoof-feasibility (`swaks --to victim --from ceo@<domain> --server <mx>`).
- **SMTP banner / `RCPT TO` enumeration** against the target's MX to confirm live mailboxes.
- **STARTTLS downgrade probes** to verify MTA-STS enforcement from an attacker vantage.
- **DKIM signature replay/forgery** to stress a weak selector key.
- **DNSSEC trust-anchor / cache-poisoning validation** against the live resolver.

These require `CAIRN_MODE=challenge` AND explicit user authorization on a domain you own or are contracted to test. Cairn's default `investigate` mode is passive-only; even in challenge mode, do not send mail to or probe SMTP on a third party's MX without written authorization. The DNS-only audit above already yields a complete spoof-feasibility verdict — active confirmation is for the asset owner's own validation, not external recon.

## PAID / EXCLUDED SOURCES (free-first)

This skill uses only free sources. Explicitly excluded as data sources: DeHashed, IntelX (paid tier), SecurityTrails, RiskIQ, Hunter.io (paid), Censys (beyond free), TinEye, facecheck, Bright Data, SerpAPI.

- **Breach × SaaS-tenant correlation** (which employees have creds on each discovered tenant): free HudsonRock Cavalier API (`https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-domain?domain=<domain>`) via `download_url`/`scrape_url`; or the `hibp` plugin if `CAIRN_HIBP_KEY` is set.
- **Historical DNS** (when DMARC/MTA-STS was added): `wayback_cdx` and `wayback_fetch` are free; SecurityTrails/DomainTools paid history is note-only — use Wayback snapshots of `mta-sts.<domain>/.well-known/mta-sts.txt` as the free alternative.
- **DMARC-report aggregation analytics** (dmarcian/Valimail paid dashboards): note-only; the `rua=` mailbox host is the free signal.

## Bash + PowerShell one-liners (reference — route via `run_command` in challenge mode, or use `dns_lookup` directly in investigate mode)

**Bash:**
```bash
D="target.example"
for rtype in A AAAA MX TXT NS SOA CAA SRV CNAME; do
  echo "=== $rtype ==="; dig +short "$D" "$rtype"
done
echo "=== DMARC ===";   dig +short TXT "_dmarc.$D"
echo "=== MTA-STS ==="; dig +short TXT "_mta-sts.$D"
echo "=== TLS-RPT ==="; dig +short TXT "_smtp._tls.$D"
echo "=== BIMI ===";    dig +short TXT "default._bimi.$D"
echo "=== DKIM selectors ==="
for s in default google selector1 selector2 mail email k1 dkim s1 s2 \
         mta1 mta2 amazonses mailchimp sendgrid mxvault zoho outlook o365; do
  r=$(dig +short TXT "$s._domainkey.$D"); [ -n "$r" ] && echo "$s: $r"
done
echo "=== DNSSEC ==="; dig +dnssec "$D" SOA | grep -E 'flags|RRSIG'
echo "=== MTA-STS policy ==="; curl -sk -m 10 "https://mta-sts.$D/.well-known/mta-sts.txt"
```

**PowerShell (5.1 lacks `-Type CAA`; use PS 7+ or `nslookup -type=CAA`):**
```powershell
$D = "target.example"
"=== SPF ===";     (Resolve-DnsName $D -Type TXT -EA SilentlyContinue | ? { $_.Strings -match 'v=spf1' }).Strings
"=== DMARC ===";   (Resolve-DnsName "_dmarc.$D" -Type TXT -EA SilentlyContinue).Strings
"=== MTA-STS ==="; (Resolve-DnsName "_mta-sts.$D" -Type TXT -EA SilentlyContinue).Strings
"=== TLS-RPT ==="; (Resolve-DnsName "_smtp._tls.$D" -Type TXT -EA SilentlyContinue).Strings
"=== BIMI ===";    (Resolve-DnsName "default._bimi.$D" -Type TXT -EA SilentlyContinue).Strings
"=== MX ===";      Resolve-DnsName $D -Type MX -EA SilentlyContinue | Select NameExchange,Preference
"=== DKIM ==="
foreach ($s in @("default","google","selector1","selector2","mail","email","k1","dkim","s1","s2",
                 "amazonses","mailchimp","sendgrid","mxvault","zoho","zmail","outlook","o365")) {
  $r = Resolve-DnsName "$s._domainkey.$D" -Type TXT -EA SilentlyContinue
  if ($r) { "$s : $($r.Strings)" }
}
"=== CAA (PS 5.1 fallback) ==="; nslookup -type=CAA $D 2>$null
"=== MTA-STS policy ==="; (Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "https://mta-sts.$D/.well-known/mta-sts.txt").Content
```

> Tradecraft adapted from [Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT) by ElementalSoul (MIT). Active techniques gated to authorized/challenge use.
