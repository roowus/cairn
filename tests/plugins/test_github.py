"""GitHub plugin (mocked)."""

from __future__ import annotations

import httpx
import respx

from cairn.execution.base import PluginContext
from cairn.plugins.identity.github import GithubInput, GithubPlugin, _normalize_login

_PROFILE = {
    "login": "torvalds",
    "name": "Linus Torvalds",
    "type": "User",
    "company": None,
    "blog": "",
    "location": "Portland, OR",
    "email": "torvalds@example.com",
    "bio": None,
    "public_repos": 7,
    "public_gists": 0,
    "followers": 200000,
    "following": 0,
    "created_at": "2011-01-03T18:22:43Z",
    "updated_at": "2024-01-01T00:00:00Z",
    "html_url": "https://github.com/torvalds",
}
_REPOS = [
    {
        "name": "linux",
        "full_name": "torvalds/linux",
        "stargazers_count": 180000,
        "language": "C",
        "html_url": "https://github.com/torvalds/linux",
        "description": "kernel",
        "updated_at": "2024-01-01",
        "default_branch": "master",
    },
]


@respx.mock
async def test_github_parses_profile_and_repos():
    respx.get("https://api.github.com/users/torvalds").mock(
        return_value=httpx.Response(200, json=_PROFILE)
    )
    respx.get("https://api.github.com/users/torvalds/repos").mock(
        return_value=httpx.Response(200, json=_REPOS)
    )
    out = await GithubPlugin().run(
        GithubInput(target="torvalds", mine_commit_emails=False),
        PluginContext(http=None),
    )
    assert out.login == "torvalds"
    assert out.email == "torvalds@example.com"
    assert out.followers == 200000
    assert out.repos and out.repos[0].full_name == "torvalds/linux"
    assert "torvalds/linux" in out.summary_markdown
    # email + repo captured as graph entities
    types_values = {(e.type, e.value) for e in out.entities}
    assert ("email", "torvalds@example.com") in types_values
    assert ("github_repo", "torvalds/linux") in types_values


@respx.mock
async def test_github_mines_commit_emails_and_youtube():
    profile = {**_PROFILE, "email": None}  # profile email hidden
    respx.get("https://api.github.com/users/torvalds").mock(
        return_value=httpx.Response(200, json=profile)
    )
    respx.get("https://api.github.com/users/torvalds/repos").mock(
        return_value=httpx.Response(200, json=_REPOS)
    )
    commits = [
        {
            "sha": "abc",
            "author": {"login": "torvalds"},
            "commit": {
                "author": {"name": "Linus", "email": "hidden@example.com"},
            },
        },
        {
            "sha": "def",
            "author": {"login": "someone-else"},
            "commit": {
                "author": {"name": "Other", "email": "other@example.com"},
            },
        },
    ]
    respx.get(url__regex=r"https://api\.github\.com/repos/torvalds/linux/commits.*").mock(
        return_value=httpx.Response(200, json=commits)
    )
    respx.get(url__regex=r"https://raw\.githubusercontent\.com/torvalds/linux/.*").mock(
        return_value=httpx.Response(
            200,
            text='see <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>',
        )
    )
    out = await GithubPlugin().run(GithubInput(target="torvalds"), PluginContext(http=None))
    assert out.email is None
    assert "hidden@example.com" in out.commit_emails
    assert "other@example.com" not in out.commit_emails
    assert "Emails from commits" in out.summary_markdown
    assert "dQw4w9WgXcQ" in out.youtube_ids
    types_values = {(e.type, e.value) for e in out.entities}
    assert ("email", "hidden@example.com") in types_values


@respx.mock
async def test_github_url_target_is_normalized():
    # full URL → still hits /users/torvalds (proves normalization)
    route = respx.get("https://api.github.com/users/torvalds").mock(
        return_value=httpx.Response(200, json=_PROFILE)
    )
    respx.get("https://api.github.com/users/torvalds/repos").mock(
        return_value=httpx.Response(200, json=[])
    )
    out = await GithubPlugin().run(
        GithubInput(target="https://github.com/torvalds", include_repos=False),
        PluginContext(http=None),
    )
    assert route.called
    assert out.login == "torvalds"


@respx.mock
async def test_github_404_is_clean():
    respx.get("https://api.github.com/users/nobody-xyz").mock(return_value=httpx.Response(404))
    out = await GithubPlugin().run(GithubInput(target="nobody-xyz"), PluginContext(http=None))
    assert "no such user" in out.summary_markdown


@respx.mock
async def test_github_rate_limit_is_handled():
    respx.get("https://api.github.com/users/torvalds").mock(
        return_value=httpx.Response(403, headers={"X-RateLimit-Remaining": "0"})
    )
    out = await GithubPlugin().run(GithubInput(target="torvalds"), PluginContext(http=None))
    assert "rate limit" in out.summary_markdown.lower()


def test_normalize_login_variants():
    assert _normalize_login("torvalds") == "torvalds"
    assert _normalize_login("https://github.com/torvalds") == "torvalds"
    assert _normalize_login("https://github.com/torvalds/linux") == "torvalds"
    assert _normalize_login("git@github.com:torvalds/linux.git") == "torvalds"
    assert _normalize_login("github.com/torvalds") == "torvalds"
