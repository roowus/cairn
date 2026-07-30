# The evidence model — provenance, confidence, OPSEC, typed assets

> Cairn ingests attacker-controlled text for a living (scraped pages, breach
> dumps, doc metadata, challenge files). An investigator treats tool output as
> **evidence** — citable, hashable, frozen in time, confidence-tagged — not as
> throwaway context. This page documents the evidence-grade data models and
> disciplines that turn Cairn from "a chat that can do OSINT" into a tool that
> *thinks in investigations*. These are the concrete implementations of three of
> the four [strategy moats](../strategy.md) (Pillars 2–4) plus the data shape of
> the fourth (Pillar 1). Models + tradecraft adapted from
> [Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT) by ElementalSoul
> (MIT); active techniques are gated to authorized/challenge use.

## Provenance / chain-of-custody (Pillar 2 — implemented)

`src/cairn/core/provenance.py` defines the evidence types:

- **`Provenance`** — the chain-of-custody on an entity: `source_url`,
  `captured_at` (UTC), `raw_sha256`, `tool`, `archive_ref`. A mined email records
  *where, when, and from what bytes* it came, so a since-deleted tweet or tampered
  page is still citable. `download_url` already SHA-256s every artifact; the
  converters attach `Provenance` to text-mined entities.
- **`Confidence`** (StrEnum) — `tentative` / `firm` / `confirmed` + the rule-of-
  three aggregation. ≥2 independent sources promote to `firm`; an explicit
  `confirmed` (a read-only credential validator) is sticky; aggregation never
  *manufactures* confirmed from tentatives.
- **`Severity`** (StrEnum) — `info`/`low`/`medium`/`high`/`critical`, ordered, with
  one-way `escalate` (never downgrades).
- **`Finding`** — the portable unit a technique emits: `module`, typed
  `asset_key`, `category`, `severity`, `confidence`, `title`, `evidence`
  (url/timestamp/sha256/raw ≤ 2 KiB), `references`, `remediation`, stable `id`.

The `Entity` graph node (`src/cairn/execution/base.py`) carries optional
`confidence`, `provenance`, `first_seen` (all default `None` → zero change to the
existing ~13 construction sites). The graph store
([graph_store](../../src/cairn/storage/graph_store.py)) persists/round-trips them
(JSON-safe) and **promotes `confidence` to `firm` on ≥2 independent sources** —
the rule-of-three seed, applied automatically as the investigation widens.

## Confidence / temporal reasoning (Pillar 4 — implemented)

The brain ([system_prompt](../../src/cairn/reasoning/system_prompt.py)) is taught
the discipline always-on: the three levels, the rule-of-three for attribution,
"never claim CONFIRMED without corroboration; **downgrade when in doubt**," and a
calibrated hedging posture ("TENTATIVE — single source: <tool>, as of <date>").
This is the epistemic twin of the anti-injection stance: refuse to assert past
what the evidence supports. (Full staleness/decay scoring per asset type remains
future work, layered on `Provenance.captured_at`.)

## OPSEC / fingerprint-aware execution (Pillar 3 — implemented)

Every plugin declares `detectability` (`src/cairn/execution/base.py`,
`BasePlugin.detectability`):

- **`low`** — passive; the target never sees you (CT logs, archives, third-party
  indexes, DNS via resolver, local file ops).
- **`medium`** — a targeted probe the target's infra observes (HTTP GET to the
  target, `holehe`/`username_check` presence checks, `scrape_url`, `download_url`).
- **`high`** — active scanning (`run_command`, which can run nmap/fuzzing).

Default is `low` (passive-by-default). `CliToolSpec.detectability` tags the
external CLIs the same way (nmap = high). The tag is surfaced in both plugin
listings (`cairn plugins`, REPL `/plugins`) and the brain is told to justify any
medium/high touch. (The full passive/active **gate** + UA-rotation/Tor routing
remains future work, layered on this flag.)

## Typed-asset taxonomy (Pillar 1 — data shape; engine is future work)

`src/cairn/core/assets.py` defines the substrate the future pivot engine runs on:

- **9-category taxonomy** (`dns_network`, `service`, `identity`, `code_config`,
  `cloud_storage`, `web`, `mobile`, `phishing`, `crypto`, …) covering Cairn's
  existing entity types plus the OSINT-native additions (`subdomain`, `netblock`,
  `secret`, `credential`, `repo`, `webapp`, `bucket`, `certificate`, …).
- **`asset_key(type, value)`** — the typed dedup key (`subdomain:api.example.com`).
  Deliberately identical in form to the graph store's node id, so adopting it
  breaks zero existing nodes.
- **`EDGES`** — the canonical relationship vocabulary (`resolves_to`, `exposes`,
  `contains_secret`, `employed_by`, …) for typed edges.

`extract_entities` now also mines `subdomain` (additive — the `domain` type is
preserved). **The deterministic BFS pivot engine itself is a separate, future
epic** ([roadmap §3](../roadmap.md)); this is its data shape, landed.

## Plugins added this pass

- **`secret_scan`** (`plugins/agentic/secret_scan.py`) — stdlib 48-pattern secret
  scanner; findings become typed `secret` entities with `Severity`, `FIRM`
  confidence, and `Provenance` (tool + source file + file SHA-256). Free, local.
- **`h1_reference`** (`plugins/web/h1_reference.py`) — keyless HackerOne Hacktivity
  GraphQL reference agent; disclosed reports as `url` entities. Free.

## Tradecraft skills

Eight Markdown playbooks in `src/cairn/skills/builtins/` (invoke with
`/<skill> <target>`): `recon-methodology` (the "how to think": pipeline +
confidence + detectability + severity + reporting), and seven chunked arsenals
(secrets-hunting, web-attack-surface, cloud-k8s-surface, identity-fabric-sso,
email-security, cdn-origin-discovery, vuln-prioritization). Each maps to Cairn's
real plugins, gates active techniques behind `CAIRN_MODE=challenge` + explicit
authorization, excludes paid platforms, and carries MIT attribution. See the
[UI overhaul](ui-overhaul.md) for the skill dispatch mechanics.

## Status vs. strategy

| Pillar | Status |
|---|---|
| 1 — Pivot engine | **Data shape landed** (taxonomy + typed keys + subdomain mining); BFS engine is the next epic |
| 2 — Provenance | **Implemented** (`Provenance`/`Finding` models + Entity fields + graph round-trip) |
| 3 — OPSEC | **Implemented** (`detectability` flag + listings + brain discipline); full passive/active gate + UA/Tor future |
| 4 — Temporal/confidence | **Implemented** (confidence model in brain + graph promotion + `Severity`); decay scoring future |
