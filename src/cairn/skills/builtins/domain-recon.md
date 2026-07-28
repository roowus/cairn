---
name: domain-recon
description: Passive reconnaissance of a domain — registrar, subdomains, DNS, history, and hosting footprint.
usage: /domain-recon <domain>
---

# Domain reconnaissance

Passive recon of a domain. Run independent lookups in parallel, then pivot on
what they reveal.

## Plan
1. **Baseline (parallel):**
   - `whois_rdap` → registrar, created/updated/expires, nameservers, status.
   - `crtsh` → subdomains via certificate transparency.
   - `dns_lookup` (A, then MX, NS) → resolved hosts and mail config.
   - `urlscan` → known page/IP/title/server history.
2. **History:** `wayback_cdx` for snapshot timeline; `wayback_fetch` the oldest
   or most-changed snapshot if the site looks different now.
3. **Pivot on resolved IPs / subdomains:**
   - ip → `shodan_internetdb` (ports/products), `ripestat` (ASN/owner),
     `hackertarget` (reverse DNS / co-hosted).
   - interesting subdomain → `scrape_url` to see what's hosted.
4. **Correlate:** which IPs host multiple subdomains? Which ASN owns the
   infrastructure? Does the cert cover unexpected names?

## Output
One-line posture summary (e.g. "single-IP Cloudflare-fronted site, 14
subdomains, registered 2019"), then per-source evidence, then "Next steps".
Cite every fact to its tool.
