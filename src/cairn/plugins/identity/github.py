"""github — GitHub user/org/repo recon via the public REST API (free, no key).

Endpoint: ``https://api.github.com/users/{login}`` — no API key required (60
requests/hour unauthenticated). Set ``CAIRN_GITHUB_KEY`` to a personal access
token to lift this to 5,000/hr.

Important: the profile ``email`` field is *optional and usually null* even when
the user has committed with a real address. This plugin therefore also mines
recent commit author emails from the target's public repos (default branch +
``gh-pages`` / ``pages`` when present) — that is how addresses like
``name@gmail.com`` surface in real investigations.
"""

from __future__ import annotations

import re
from collections import Counter

import httpx
from pydantic import BaseModel, Field

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)
from cairn.execution.http_util import http_client

_YT = re.compile(
    r"(?:youtube\.com/embed/|youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})",
    re.I,
)
_NOREPLY = re.compile(r"@users\.noreply\.github\.com$", re.I)


def _normalize_login(target: str) -> str:
    """Accept a bare login, a github.com URL, or a git-clone URL → just the login."""
    t = target.strip()
    if "://" in t:
        t = t.split("://", 1)[1]
    if "@" in t:
        t = t.split("@", 1)[-1]
    t = t.removeprefix("github.com:").removeprefix("github.com/")
    t = t.lstrip("/")
    seg = t.split("/")[0]
    return seg or target.strip()


def _capture_rate_limit(out: GithubOutput, r: httpx.Response) -> None:
    """Read GitHub's X-RateLimit-* headers into the output for the usage report."""
    rem = r.headers.get("X-RateLimit-Remaining")
    if rem and rem.isdigit():
        out.rate_limit_remaining = int(rem)
    reset = r.headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit():
        out.rate_limit_reset = int(reset)


class GithubRepo(BaseModel):
    name: str
    full_name: str
    stars: int
    language: str | None
    url: str
    description: str | None
    updated: str | None
    default_branch: str | None = None


class GithubInput(PluginInput):
    """``target`` is a GitHub username or organization (URLs accepted)."""

    include_repos: bool = True
    repo_limit: int = 8
    mine_commit_emails: bool = Field(
        default=True,
        description=(
            "Scan recent commits on the target's public repos for author emails "
            "(profile email is often null even when commits leak a real address)."
        ),
    )
    commit_scan_repos: int = Field(
        default=3,
        ge=1,
        le=20,
        description="How many recently-updated repos to scan for commit emails.",
    )
    commits_per_branch: int = Field(
        default=12,
        ge=1,
        le=50,
        description="Commits to fetch per branch tip.",
    )


class GithubOutput(PluginOutput):
    login: str | None = None
    name: str | None = None
    type: str | None = None  # User | Organization
    company: str | None = None
    blog: str | None = None
    location: str | None = None
    email: str | None = None  # profile email (often null)
    bio: str | None = None
    twitter_username: str | None = None
    avatar_url: str | None = None
    public_repos: int | None = None
    public_gists: int | None = None
    followers: int | None = None
    following: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    html_url: str | None = None
    repos: list[GithubRepo] = Field(default_factory=list)
    # Emails mined from commits attributed to this login (profile email first if set).
    commit_emails: list[str] = Field(default_factory=list)
    commit_names: list[str] = Field(default_factory=list)
    youtube_ids: list[str] = Field(default_factory=list)


class GithubPlugin(BasePlugin[GithubInput, GithubOutput]):
    name = "github"
    category = "identity"
    requires_key = None  # free unauthenticated; token is optional
    input_model = GithubInput
    output_model = GithubOutput
    cost = CostSpec(
        unit="calls/hr",
        note="60/hr unauth → 5k/hr with CAIRN_GITHUB_KEY; commit mining uses extra calls",
    )

    __doc__ = (
        "Look up a GitHub user/org: profile, blog, avatar, follower counts, recent "
        "repos, **commit-mined emails** (profile email is often hidden), and YouTube "
        "embed IDs from READMEs. Free (60/hr); set CAIRN_GITHUB_KEY for 5k/hr."
    )

    async def run(self, inp: GithubInput, ctx: PluginContext) -> GithubOutput:
        login = _normalize_login(inp.target)
        async with http_client(ctx) as http:
            headers = {"Accept": "application/vnd.github+json", "User-Agent": ctx.user_agent}
            token = ctx.key("github")
            if token:
                headers["Authorization"] = f"Bearer {token}"

            r = await http.get(f"https://api.github.com/users/{login}", headers=headers)
            if r.status_code == 404:
                return GithubOutput(
                    source=self.name,
                    summary_markdown=f"**{inp.target}** — GitHub: no such user/org (`{login}`).",
                    entities=[Entity(type="github_login", value=login)],
                )
            if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
                return GithubOutput(
                    source=self.name,
                    summary_markdown=(
                        f"**{inp.target}** — GitHub rate limit hit (60/hr unauthenticated). "
                        "Set CAIRN_GITHUB_KEY to a personal access token for 5,000/hr."
                    ),
                    entities=[Entity(type="github_login", value=login)],
                )
            r.raise_for_status()
            u = r.json()

            repos: list[GithubRepo] = []
            raw_repos: list[dict] = []
            if inp.include_repos:
                rr = await http.get(
                    f"https://api.github.com/users/{login}/repos",
                    params={
                        "sort": "updated",
                        "per_page": min(max(inp.repo_limit, 1), 100),
                        "type": "owner",
                    },
                    headers=headers,
                )
                if rr.status_code == 200 and isinstance(rr.json(), list):
                    raw_repos = rr.json()
                    for repo in raw_repos:
                        repos.append(
                            GithubRepo(
                                name=repo.get("name", ""),
                                full_name=repo.get("full_name", ""),
                                stars=repo.get("stargazers_count", 0),
                                language=repo.get("language"),
                                url=repo.get("html_url", ""),
                                description=repo.get("description"),
                                updated=repo.get("updated_at"),
                                default_branch=repo.get("default_branch"),
                            )
                        )

            email_counts: Counter[str] = Counter()
            name_counts: Counter[str] = Counter()
            youtube: list[str] = []
            mine_note = ""

            if inp.mine_commit_emails and raw_repos:
                mine_note = await _mine_commit_identity(
                    http,
                    headers,
                    login=login,
                    profile_name=(u.get("name") or "") or "",
                    repos=raw_repos[: inp.commit_scan_repos],
                    commits_per_branch=inp.commits_per_branch,
                    email_counts=email_counts,
                    name_counts=name_counts,
                    youtube=youtube,
                )

            profile_email = u.get("email")
            commit_emails = [e for e, _ in email_counts.most_common()]
            # Prefer putting a non-noreply real email first in the summary.
            ranked = _rank_emails(profile_email, commit_emails)

            out = GithubOutput(
                source=self.name,
                login=u.get("login"),
                name=u.get("name"),
                type=u.get("type"),
                company=u.get("company"),
                blog=u.get("blog"),
                location=u.get("location"),
                email=profile_email,
                bio=u.get("bio"),
                twitter_username=u.get("twitter_username"),
                avatar_url=u.get("avatar_url"),
                public_repos=u.get("public_repos"),
                public_gists=u.get("public_gists"),
                followers=u.get("followers"),
                following=u.get("following"),
                created_at=u.get("created_at"),
                updated_at=u.get("updated_at"),
                html_url=u.get("html_url"),
                repos=repos,
                commit_emails=ranked,
                commit_names=[n for n, _ in name_counts.most_common()],
                youtube_ids=sorted(set(youtube)),
            )

            out.summary_markdown = _summary(out, inp.target, mine_note=mine_note)
            out.entities = _entities(out)
            _capture_rate_limit(out, r)
            return out


def _rank_emails(profile: str | None, mined: list[str]) -> list[str]:
    seen: list[str] = []
    for e in ([profile] if profile else []) + mined:
        if not e or e in seen:
            continue
        seen.append(e)
    # real addresses before noreply
    seen.sort(key=lambda x: (1 if _NOREPLY.search(x) else 0, x.lower()))
    return seen


async def _mine_commit_identity(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    login: str,
    profile_name: str,
    repos: list[dict],
    commits_per_branch: int,
    email_counts: Counter[str],
    name_counts: Counter[str],
    youtube: list[str],
) -> str:
    """Mine emails/names/YouTube. Returns a short note (e.g. rate-limit) for the summary."""
    login_l = login.lower()
    pname_l = profile_name.lower().strip()
    note = ""
    raw_headers = {"User-Agent": headers.get("User-Agent", "cairn")}

    for repo in repos:
        # Stop early once we have a real (non-noreply) email — saves rate limit.
        if any(not _NOREPLY.search(e) for e in email_counts):
            break

        full = repo.get("full_name") or f"{login}/{repo.get('name', '')}"
        default = repo.get("default_branch") or "main"
        # Prefer pages branch first for student portfolios; then default.
        branches = []
        for b in ("gh-pages", "pages", default):
            if b and b not in branches:
                branches.append(b)

        for branch in branches:
            cr = await http.get(
                f"https://api.github.com/repos/{full}/commits",
                params={"sha": branch, "per_page": commits_per_branch, "author": login},
                headers=headers,
            )
            if cr.status_code == 403 and cr.headers.get("X-RateLimit-Remaining") == "0":
                note = (
                    "Commit email mining hit GitHub's unauthenticated rate limit "
                    "(60/hr). Set CAIRN_GITHUB_KEY for 5,000/hr and re-run."
                )
                return note
            if cr.status_code == 404:
                continue
            if cr.status_code != 200 or not isinstance(cr.json(), list):
                continue
            for c in cr.json():
                _ingest_commit(
                    c,
                    login_l=login_l,
                    pname_l=pname_l,
                    email_counts=email_counts,
                    name_counts=name_counts,
                )

        # README / portfolio index often embed YouTube milestone videos.
        for br in branches:
            for path in ("index.md", "README.md", "readme.md", "docs/index.md"):
                raw = await http.get(
                    f"https://raw.githubusercontent.com/{full}/{br}/{path}",
                    headers=raw_headers,
                )
                if raw.status_code == 200 and raw.text:
                    youtube.extend(_YT.findall(raw.text))

    return note


def _ingest_commit(
    c: dict,
    *,
    login_l: str,
    pname_l: str,
    email_counts: Counter[str],
    name_counts: Counter[str],
) -> None:
    gh_author = c.get("author") or {}
    gh_login = (gh_author.get("login") or "").lower()
    commit = c.get("commit") or {}
    author = commit.get("author") or {}
    email = (author.get("email") or "").strip()
    name = (author.get("name") or "").strip()

    # Prefer commits clearly tied to this user.
    tied = False
    if gh_login and gh_login == login_l:
        tied = True
    elif not gh_login:
        # Unlinked commit — match by profile name / login heuristics only.
        nl = name.lower()
        if nl == login_l or (pname_l and nl == pname_l):
            tied = True
        el = email.lower()
        if el.startswith(f"{login_l}@") or f"+{login_l}@" in el:
            tied = True

    if not tied:
        return
    if email:
        email_counts[email] += 1
    if name:
        name_counts[name] += 1


def _summary(out: GithubOutput, target: str, *, mine_note: str = "") -> str:
    disp = out.name or out.login or target
    lines = [f"**{disp}** — GitHub ({out.type or 'User'})"]
    facts = [
        ("Login", out.login),
        ("Company", out.company),
        ("Location", out.location),
        ("Profile email", out.email),
        ("Blog", out.blog),
        ("Twitter/X", out.twitter_username),
        ("Bio", out.bio),
        ("Avatar", out.avatar_url),
        ("Public repos", out.public_repos),
        ("Public gists", out.public_gists),
        ("Followers", out.followers),
        ("Following", out.following),
        ("Joined", out.created_at),
        ("Profile", out.html_url),
    ]
    for label, val in facts:
        if val not in (None, ""):
            lines.append(f"- {label}: {val}")
    if out.commit_emails:
        lines.append("- **Emails from commits** (profile email is often hidden):")
        for e in out.commit_emails:
            kind = "noreply" if _NOREPLY.search(e) else "personal/work"
            lines.append(f"  - `{e}` ({kind})")
    if out.commit_names:
        lines.append(f"- Commit author names seen: {', '.join(out.commit_names)}")
    if out.youtube_ids:
        lines.append("- YouTube embeds found in repo docs:")
        for yid in out.youtube_ids:
            lines.append(f"  - https://www.youtube.com/watch?v={yid}")
    if out.repos:
        lines.append("- Recent repos:")
        for repo in out.repos:
            lang = f" [{repo.language}]" if repo.language else ""
            br = f" @{repo.default_branch}" if repo.default_branch else ""
            lines.append(f"  - {repo.full_name}{br} (★{repo.stars}){lang} — {repo.url}")
    if not out.email and not out.commit_emails:
        lines.append(
            "- Email: none found on profile or recent commits "
            "(user may force-push with noreply-only, or commits are private)."
        )
    if mine_note:
        lines.append(f"- Note: {mine_note}")
    return "\n".join(lines)


def _entities(out: GithubOutput) -> list[Entity]:
    ents = [
        Entity(
            type="github_login",
            value=out.login or "",
            attrs={
                "type": out.type,
                "followers": out.followers,
                "public_repos": out.public_repos,
                "created_at": out.created_at,
                "avatar_url": out.avatar_url,
            },
        )
    ]
    if out.name:
        ents.append(Entity(type="person_name", value=out.name))
    for e in out.commit_emails:
        ents.append(
            Entity(
                type="email",
                value=e,
                attrs={"source": "github_commit" if e != out.email else "github_profile"},
            )
        )
    if out.email and out.email not in out.commit_emails:
        ents.append(Entity(type="email", value=out.email, attrs={"source": "github_profile"}))
    if out.blog:
        blog = out.blog if out.blog.startswith("http") else f"https://{out.blog}"
        ents.append(Entity(type="url", value=blog))
    if out.avatar_url:
        ents.append(Entity(type="image_url", value=out.avatar_url, attrs={"kind": "avatar"}))
    if out.twitter_username:
        ents.append(Entity(type="username", value=out.twitter_username, attrs={"platform": "x"}))
    for yid in out.youtube_ids:
        ents.append(
            Entity(
                type="url",
                value=f"https://www.youtube.com/watch?v={yid}",
                attrs={"platform": "youtube", "video_id": yid},
            )
        )
    for repo in out.repos:
        ents.append(Entity(type="github_repo", value=repo.full_name, attrs={"stars": repo.stars}))
    return ents
