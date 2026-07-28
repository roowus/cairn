# Social probing, Sherlock, and “looking like a human”

Everything we learned about username/social checks — why bare HTTP and Sherlock
sometimes disagree with what you see in an **incognito browser**, and how Cairn
fixes that without Bright Data or fingerprint farms.

**Code:**

| Module | Role |
|---|---|
| `execution/browser_http.py` | Chrome-like headers, HTTP/2, empty-shell / 429 retries |
| `execution/social_probe.py` | First-party probes (IG, GitHub, Reddit, YT, TikTok, X, Threads) |
| `execution/runner.py` | Shared session client uses browser-like defaults |
| `plugins/identity/username_check.py` | Preferred major-platform tool |
| `plugins/identity/sherlock.py` | 300+ sweep **+** first-party cross-check |
| `plugins/identity/github.py` | Profile + **commit-mined emails** + YouTube embeds |

Related: [agent-reach analysis](research/agent-reach-analysis.md) (cookie sessions
for deeper social), [Plugin reference](plugin-reference.md),
[Discoveries](discoveries.md).

---

## 1. The misconception we corrected

### Wrong framing (early)

> “Instagram blocks all non-login checks; Sherlock is right that the user doesn’t exist.”

### Right framing (verified)

1. **Incognito, no login, no prior cookies** can still load
   `https://www.instagram.com/{user}/` and show a real profile (name, counts).
2. **Bare bot HTTP** (minimal UA, no `Sec-Fetch-*`, HTTP/1.1-only) often gets a
   large HTML **JS shell** whose `<title>` is just `Instagram` — no `og:title`
   profile markers. Same URL, different body.
3. **Browser-like HTTP** (Chrome UA + navigation headers + HTTP/2) **sometimes**
   returns full `og:title` / `og:description` logged-out — matching incognito
   metadata — and sometimes still returns a shell. Flaky, not impossible.
4. **Sherlock’s Instagram rule does not probe Instagram first.** In
   `sherlock_project/resources/data.json`:

   ```json
   "Instagram": {
     "errorType": "status_code",
     "url": "https://instagram.com/{}",
     "urlProbe": "https://imginn.com/{}"
   }
   ```

   Existence is decided by **imginn.com** (third-party mirror). When imginn
   returns `410`, Sherlock reports “not found” even if Instagram has the
   account. That is a **bad probe**, not ground truth.

**Ground truth for “does this page work logged-out?”** is what a real browser
shows, not what a stale mirror returns.

---

## 2. Why Sherlock and “manual OSINT” diverge

Sherlock is a **wide net** (~400 sites). Many rules are excellent first-party
checks. A minority use `urlProbe` on a **different host** than `url`.

Examples of probe host ≠ site host (from Sherlock’s `data.json` at build time):

| Site | Main host | Probe host (problem class) |
|---|---|---|
| Instagram | instagram.com | **imginn.com** (mirror; false negatives) |
| Twitter/X | x.com | **nitter.*** forks (often down/stale) |
| Venmo | account.venmo.com | test1.venmo.com |
| Others | … | Often OK official APIs (Imgur, Mixcloud, …) |

So:

- **Manual / incognito:** first-party URL, real browser TLS + JS.
- **Sherlock on IG:** third-party status code.
- **Naive httpx:** first-party URL but bot-shaped client → empty shell → easy to
  mis-read as “no account.”

Cairn’s rule: **major platforms = first-party probes with browser-like HTTP.**
Sherlock remains for long-tail niche sites, with major platforms cross-checked.

---

## 3. “Make it look like a human” — three tiers

The AI doesn’t need to *impersonate* a stranger. It needs the **same capability
class** as your hands on a keyboard.

| Tier | What it is | Looks human? | Cairn status |
|---|---|---|---|
| **A. Browser-like HTTP** | Chrome UA, `Sec-Fetch-*`, HTTP/2, retries on empty shells | Close to logged-out incognito for **public metadata** | ✅ `browser_http` + `username_check` |
| **B. Your browser cookies** | `browser_cookie3` → replay session on platform JSON APIs | Yes — *is* your session | 🟡 designed ([agent-reach](research/agent-reach-analysis.md)) |
| **C. Real browser automation** | Playwright + your profile / headed browser | Yes for hardest SPAs | 🟡 roadmap (IG deep posts, FB, LinkedIn) |

### What we deliberately do **not** build

- Residential proxy “undetectable” farms  
- CAPTCHA-solving as a core dependency  
- Stolen sessions / credential stuffing  
- Pretending mass anonymous enumeration equals careful manual review  

Those are industrial evasion products, not a personal hard-stop OSINT CLI.

### What “human-like” means in tier A

Not fingerprint theatre. Practical defaults:

```text
User-Agent: Chrome/131 macOS
Accept: text/html, …
Sec-Fetch-Dest: document
Sec-Fetch-Mode: navigate
Sec-Fetch-Site: none
Sec-Fetch-User: ?1
HTTP/2 when available
Retry on 429/5xx
Retry when body looks like an empty SPA shell (title brand-only, no og profile)
```

Shared client: `build_context()` → `make_browser_client()`.

---

## 4. First-party probe contract

Each probe returns one of:

| Status | Meaning | Do **not** treat as |
|---|---|---|
| `found` | Definitive positive signal (e.g. `(@user)` in og:title, API 200 profile) | — |
| `not_found` | Definitive negative (HTTP 404, platform “doesn’t exist” copy) | — |
| `unknown` | Shell, challenge, login interstitial, or ambiguous HTML | **`not_found`** |
| `error` | Network/TLS/client failure | `not_found` |

**`unknown` ≠ missing account.** That distinction is load-bearing for Instagram.

### Platform signals (summary)

| Platform | Method | Strong `found` signal |
|---|---|---|
| Instagram | GET `www.instagram.com/{user}/` | `(@username)` in title / og:title; og:description with counts |
| GitHub | REST `api.github.com/users/{user}` | HTTP 200 JSON |
| Reddit | `reddit.com/user/{user}/about.json` | `data.name` / id |
| YouTube | `youtube.com/@{user}` | channel title / og |
| TikTok | `tiktok.com/@{user}` | `@user` in og/title |
| X/Twitter | `x.com/{user}` | often **unknown** logged-out; cookies later |
| Threads | `threads.net/@{user}` | `@user` in og/title |

Implemented in `execution/social_probe.py`.

---

## 5. Tools: when to use which

### `username_check` (preferred for major socials)

```text
username_check(target="roowus")
# optional: platforms=["instagram","github","threads"]
```

- Only first-party probes  
- Fast relative to full Sherlock  
- Returns found / not_found / unknown with evidence  
- Verified live example: `@roowus` → Instagram (display name + follower line),
  GitHub, Threads  

### `sherlock` (breadth)

```text
sherlock(target="roowus")
```

1. Runs CLI wide sweep (1–3 minutes; overall timeout default **240s**, not the
   30s HTTP default — that bug caused false “unavailable” timeouts).  
2. Strips known-bad mirror URLs (imginn, nitter, …).  
3. Runs the same first-party cross-check as `username_check`.  
4. Merges first-party `found` URLs into the profile list; drops Sherlock URLs
   for platforms first-party marks `not_found`.  

### `github` (deep identity, not just “exists”)

Profile `email` is **often null** even when commits leak a real address.

Example (public data): user `roowus` has `"email": null` on
`/users/roowus`, but commits on `Lewis-BSE-Portfolio` / `gh-pages` carry
`From: roowus <lewishelh@gmail.com>`.

So `github` now:

1. Loads profile + repos  
2. Mines recent commits on default + `gh-pages`/`pages` (author-filtered)  
3. Ranks emails (personal before `users.noreply.github.com`)  
4. Scrapes README/`index.md` on those branches for **YouTube embed IDs**  
5. Emits entities: email, avatar `image_url`, youtube URLs, repos  

**Rate limit:** unauthenticated GitHub is **60 req/hr**. Commit mining uses
several calls. Set `CAIRN_GITHUB_KEY` (PAT) → 5,000/hr. Mining stops early once
a non-noreply email is found; surfaces a clear note if rate-limited mid-scan.

### `holehe` (email → platforms)

- Flag is **`--only-used`** (not the old wrong `--only-known`).  
- Also `--no-color --no-clear -NP -T 10`.  
- Overall process timeout ~**180s** (not 30s HTTP).  
- Auto-installs via allowlisted `uv tool install holehe`.  

---

## 6. Investigator loop guidance (username path)

Recommended order for a handle:

```text
1. username_check(handle)          # major platforms, reliable
2. github(handle)                  # emails, repos, YT embeds, avatar
3. web_search / generate_dorks     # corroboration
4. scrape_url on strong hits
5. sherlock(handle)                # optional long-tail only
6. holehe(email)                   # if an email appeared
```

Do **not** lead with Sherlock for “does Instagram exist?” — lead with
`username_check`.

System prompt (`reasoning/system_prompt.py`) encodes this order.

---

## 7. External CLIs (auto-install)

`sherlock` / `holehe` binaries:

- Auto-install at REPL startup (`ensure_missing_cli_tools`)  
- Auto-install on first use (`run_cli_tool`)  
- Allowlist only: `uv tool install sherlock-project` / `holehe`  
- User should **never** need a manual install step  

See [configuration.md § self-installing CLIs](configuration.md#self-installing-external-clis-you-do-nothing).

---

## 8. Still missing (honest roadmap)

| Capability | Why not done | Next step |
|---|---|---|
| Reverse image on avatars | No plugin yet | Free-first reverse-image plugin; avatar already an entity |
| YouTube **video** analysis | Only embed URL extraction today | `yt-dlp` metadata plugin; optional frame/ASR later |
| Deep Instagram posts / graph | Logged-out HTML is metadata-only | Cookie session + Playwright tier |
| X reliable without cookies | Logged-out interstitial | agent-reach cookie channel |
| Facebook / LinkedIn | Hard SPA + login | Playwright tier or skip |

“Make the AI do what I do manually” for those = **tier B/C** (your session /
browser), not smarter User-Agent strings alone.

---

## 9. Worked counter-example: `@roowus`

| Check | Old result | Why | New result |
|---|---|---|---|
| Sherlock Instagram | miss | imginn `410` | first-party **found** (name + counts) |
| GitHub profile email | none | `email: null` on API | **commit-mined** personal email + noreply |
| Portfolio YouTube | “open manually” | not extracted | embed IDs from `gh-pages/index.md` |
| Sherlock full run timeout | “unavailable after auto-install” | process budget was **30s** | overall timeout **240s** + clearer errors |

---

## 10. Operator checklist

```bash
# Recommended keys for deep recon
# GitHub PAT → commit mining won't die at 60/hr
echo 'CAIRN_GITHUB_KEY=ghp_...' >> ~/.cairn/.env
# Brave → web_search that isn't anti-bot blocked
echo 'CAIRN_BRAVE_KEY=...' >> ~/.cairn/.env

cairn
# then:
#   username_check on <handle>
#   github on <handle>
#   sherlock only if you need the long tail
```

### Interpreting results

- Trust **`username_check` / first-party** over Sherlock for IG/GitHub/Reddit/…  
- **`unknown`** → don’t claim absence; retry or escalate to browser/cookies  
- **GitHub without PAT** → may skip commit emails when rate-limited; re-run with key  
- Esc still cancels long Sherlock runs without leaving the REPL  

---

## 11. Design principles (summary)

1. **Incognito is the baseline** for “is logged-out access possible?”  
2. **First-party URL > third-party mirror** for existence.  
3. **Browser-shaped HTTP** closes most of the gap for public metadata.  
4. **`unknown` is a first-class status** — never collapse to not_found.  
5. **Your cookies / Playwright** are the legitimate “look human” path for
   walls — not proxy farms.  
6. **Sherlock = breadth; username_check = truth on majors.**  
7. **Profile fields lie by omission** (GitHub email) — mine commits and docs.  
