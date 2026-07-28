---
name: ip-enrich
description: Enrich an IP address — open ports/products, hosting/ASN, reputation history, and co-hosted domains.
usage: /ip-enrich <ipv4 address>
---

# IP enrichment

Build a grounded picture of an IP from passive sources. Run the independent
lookups in parallel.

## Plan
1. **Baseline (parallel):**
   - `shodan_internetdb` → hostnames, open ports, products, vulns, tags (free,
     no key). If `CAIRN_SHODAN_KEY` is set, `shodan_full` gives richer detail.
   - `ripestat` → ASN, holder, prefix, country.
   - `hackertarget` → reverse DNS and co-hosted domains (hostsearch/reverseip).
   - `urlscan` → page/domain/title/server history seen scanning this IP.
2. **Pivot:**
   - a hostname on the IP → `dns_lookup`, `whois_rdap` (if a domain).
   - suspicious service/banner → note the product+version for the assessment.
   - if keyed: `virustotal` (malicious verdict) and `abuseipdb` (abuse score).
3. **Correlate:** ASN owner + country + open-service profile → likely hosting
   class (cloud / VPS / residential / CDN). Flag anything anomalous.

## Output
One-line host characterization, per-source evidence bullets (ports, ASN,
co-hosted names), then "Next steps". Only report what the tools returned.
