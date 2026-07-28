# Research: agent-reach (`Panniantong/agent-reach`)

> The free answer to walled social platforms: use the user's *own browser
> cookies* to talk to platform endpoints directly over HTTP — no Bright Data, no
> scraping-API bill.

## What agent-reach is

A Python toolkit that reaches *behind* the login wall of platforms (Twitter/X,
Reddit, YouTube, Bilibili, V2EX, GitHub, Xiaohongshu, LinkedIn) **without a paid
scraper and (mostly) without a headless browser.** Its trick: read the cookies
your real browser already holds for a site and replay them as an HTTP `Cookie`
header on the platform's own internal/JSON endpoints.

### Architecture (observed in source)

- **Cookie-session model** — `browser_cookie3` (Chrome/Firefox/Safari/Edge on
  macOS/Windows/Linux) and `rookiepy` (for encrypted-Chrome on newer OSes) load
  cookies for a domain into an `httpx`/`requests` session. Authenticated
  requests then look indistinguishable from the browser's own background calls.
- **`Channel` abstraction** — each platform is a channel with:
  - `can_handle(url)` / `can_handle_id(id)` — routing predicate,
  - `check(...)` — fetch the data,
  - `ordered_backends` — a fallback chain (e.g. try internal JSON API, then a
    CLI tool, then HTML scrape).
- **Routes to upstream CLIs** rather than reimplementing scrapers where a good
  one exists: `twitter-cli`, `rdt-cli` (Reddit), `yt-dlp` (YouTube metadata),
  `gh` (GitHub), `bili-cli` (Bilibili).
- **Mostly pure HTTP** — no Playwright except for `xiaohongshu` and `linkedin`,
  which are too fragile/JS-heavy to hit over plain HTTP.

## Why this matters for Cairn

It is the free path to the social pivots the investigator loop needs (read a
user's posts, comments, follows, profile) without paying Bright Data to unlock
them. A scrape of a logged-out Instagram/Twitter page is near-useless today;
agent-reach's cookie model gets the *real* data a logged-in user sees.

## How to apply it to Cairn (the plan)

A new **`plugins/social/`** category — one channel per platform, each a normal
Cairn plugin (`requires_key=None`, because the "key" is the local browser
cookie, not an API token):

| Platform | Transport | Notes |
|---|---|---|
| Twitter / X | cookies → internal GraphQL API | most data; no browser |
| Reddit | cookies → JSON / `rdt-cli` | no browser |
| YouTube | `yt-dlp` metadata | no browser; no login for public data |
| Bilibili | cookies / `bili-cli` | no browser |
| GitHub | already done (`github` plugin, REST API) | — |
| Instagram | **partial ✅** logged-out metadata via first-party `username_check` (og:title/counts); **deep** posts/graph still need cookies/Playwright | see [social-probing.md](../social-probing.md) |
| Facebook | **gap** — Playwright / cookies | — |
| LinkedIn | **gap** — Puppeteer-class only | too fragile; out of scope for v1 |
| Xiaohongshu | Playwright only | optional, deferred |
| Threads | **partial ✅** first-party og probe in `username_check` | deep content later |

**Design choice:** *reimplement thin channels* (vendoring agent-reach wholesale
pulls in a lot of surface area and CLI deps). Each Cairn social plugin will:
1. lazily import `browser_cookie3`,
2. load cookies for its domain (graceful "log in to X in your browser, then
   retry" message if absent),
3. hit one or two internal endpoints via the shared `ctx.http`,
4. return a normal `PluginOutput` (summary + mined entities), so it composes
   with the rest of the loop identically.

## Gaps to acknowledge honestly

- **Cookie auth is per-user, per-machine.** It reads *your* browser session —
  fine for a personal investigator CLI, not for a multi-tenant service.
- **Cookies expire / platforms change endpoints.** Channels will break and need
  maintenance; this is inherent to non-API access.
- **Logged-out ≠ useless, but ≠ complete.** Incognito can load Instagram profile
  *metadata* (name, counts) without login. Bare bot HTTP often gets an empty JS
  shell; browser-like HTTP + retries often recovers og-tags. **Deep** content
  (posts, graph, private) still wants cookies/Playwright. Sherlock’s old
  Instagram path used **imginn.com** and false-negatived — fixed via first-party
  probes in core (not only via agent-reach).
- **Facebook / LinkedIn** remain hard without a real browser session.

## What shipped in core before full agent-reach

Cairn already implements **tier A** social existence (no cookies):

- `username_check` / `social_probe` — first-party IG, GitHub, Reddit, YouTube,
  TikTok, X, Threads with `found|not_found|unknown`
- Shared browser-like `httpx` client
- Sherlock cross-check so wide sweeps don’t trust imginn/nitter alone

Full write-up: [Social probing](../social-probing.md).

## Recommendation

1. Keep using **tier A** (`username_check`) for major-platform existence.
2. Next agent-reach channels: **X + Reddit cookies** (JSON), **YouTube via
   yt-dlp** (public metadata), then **Instagram Playwright** for posts.
3. Behind `uv sync --extra social` for cookie/browser deps.
4. Keep the `Channel` pattern (ordered backends). → [Roadmap](../roadmap.md)
