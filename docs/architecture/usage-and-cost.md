# Usage & cost reporting

Cairn is free-first, but the brain *can* reach for daily-quota'd and key-gated
(credit-metered) sources. So the CLI reports exactly what each investigation
costs — **credits used, time taken, and rate/quota/service usage** — focused on
the metered and paid plugins. Free sources show call counts + time too.

This mirrors the [progress tap](../discoveries.md#the-progress-tap-live-status):
an **accountant only**, never influencing execution. It cannot alter tool
arguments, suppress a call, or change the answer.

## What gets tracked

For every plugin call the tool closure (in `orchestration/tool_adapter.py`, the
single source of truth) records:

| Field | Source | Example |
|---|---|---|
| call count + ok/error | always | `scrape_url · 12 calls (+1✗)` |
| wall-clock time | `time.perf_counter()` | `2.3s` |
| units consumed | plugin `CostSpec.per_call` | `2 credits`, `1 lookups/day` |
| static quota | plugin `CostSpec` | `50/day`, `2000/mo` |
| dynamic remaining | response (headers/body) | `47 left`, `quota hit` |

## The two scopes

- **Live (session)** — `orchestration/usage.py::UsageTracker` accumulates across
  a REPL session or one `cairn search` run. Surfaced by `/usage` (REPL), the
  per-turn summary line, and the post-run block in `cairn search`.
- **Historical (persisted)** — every call writes `elapsed_ms` + a per-call
  `usage_json` snapshot to the append-only `audit_log`.
  `aggregate_history(db)` reconstructs per-source totals; this powers
  `cairn usage`.

### The per-call invariant (don't over-count)

The audit snapshot stores the **per-call delta** (`CostSpec.per_call`), **not**
the tracker's running total. Otherwise summing snapshots across rows would add
cumulative running totals (2 + 4 + 6 …) and massively over-count. The
checkpoint/delta helpers (`UsageTracker.checkpoint` / `.delta`) give true
per-turn deltas for the live summary line. Regression-tested in
`tests/unit/test_usage.py`.

## How a plugin declares its cost

A `CostSpec` (frozen dataclass) as a `cost` ClassVar on `BasePlugin`. Free
plugins inherit the default and need nothing; override on metered sources:

```python
from cairn.execution.base import CostSpec

# paid, credit-metered
cost = CostSpec(unit="credits", per_call=1.0, paid=True, note="1 query credit/lookup")

# free but a hard daily quota
cost = CostSpec(unit="lookups/day", daily_quota=50, note="~50/day per IP")
```

A plugin may also read **dynamic** metering from its response into the standard
`PluginOutput` fields, and the report carries the last-known value forward:

```python
out.rate_limit_remaining = int(r.headers["X-RateLimit-Remaining"])   # GitHub
out.rate_limit_reset     = int(r.headers["X-RateLimit-Reset"])
out.quota_remaining      = 0      # hackertarget: "api count exceeded"
out.credits_remaining    = bal    # a credit balance from a JSON body
```

## Current metered sources

| Plugin | tier | metering | paid? |
|---|---|---|---|
| `hackertarget` | limited/day | 50 lookups/day (per IP); reports `0 left` when exhausted | no |
| `web_search` | free | Brave 2,000 queries/mo (DDG fallback is anti-bot-blocked) | no |
| `abuseipdb` | keyed | 1,000 lookups/day (free key) | no |
| `github` | free | 60/hr unauth → 5k/hr keyed; reports `X-RateLimit-Remaining` | no |
| `urlscan` | free | ~1,000 searches/day community → higher with key | no |
| `shodan_full` | keyed | 1 query credit/lookup | **yes** |
| `censys` | keyed | draws search credits | **yes** |
| `hibp` | keyed | paid API key required | **yes** |
| `virustotal` | keyed | ~4/min free public → 500/min premium | no |

(The free, unmetered sources — `whois_rdap`, `dns_lookup`, `crtsh`, `ripestat`,
`wayback_*`, `common_crawl`, `shodan_internetdb`, `generate_dorks`,
`scrape_url`, `username_check`, `holehe`, `sherlock` — show only calls + time.)

## Surfaces

```bash
cairn plugins        # cost column (free · 50/day · credits · paid · …)
cairn usage          # historical: credits/time/quota across all runs (audit log)
```

```text
cairn> /usage        # this session: metered/paid table + totals line
```

After each REPL turn (and after `cairn search`):

```text
▸ 3 tool call(s) · 2.3s · 1 credits used (paid)
```

## Estimating cost honestly

The report measures in each service's **native unit** (credits, lookups/day,
queries/mo, calls/hr) — never a guessed USD figure, since per-call pricing
varies by plan and is often undocumented. `paid?` marks sources that charge
money or require a paid plan, so you always know which calls draw credits.

See also: [plugin contract](plugin-contract.md), [discoveries](../discoveries.md),
[free-first strategy](../discoveries.md#free-first-strategy).
