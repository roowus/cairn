"""generate_dorks — build Google dork queries for a target (offline, free, no key).

Given a name / username / handle, emits the canonical OSINT dorks (``site:``
restrictions, ``filetype:pdf``, ``resume OR cv``, ``leaked OR breach``, etc.) as
both raw query strings and ready-to-open Google search URLs. The agent typically
feeds these into ``web_search`` to actually execute them — the
``site:instagram.com "username"`` move that starts a layered investigation.

Pure string generation; no network. Adapted from the dork templates used by
OpenOSINT and other OSINT tooling.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput

# site: targets — the platforms worth restricting a search to for a person/handle.
_SITES = [
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "github.com",
    "reddit.com",
    "tiktok.com",
    "youtube.com",
]


class GenerateDorksInput(PluginInput):
    """``target`` is a name, username, or handle to dork."""

    #: extra OR-terms to append, e.g. "email", "phone", "password".
    extra_terms: str = ""
    #: include the site-restricted dorks (default True).
    site_dorks: bool = True


class GenerateDorksOutput(PluginOutput):
    dorks: list[str] = Field(default_factory=list)  # raw query strings
    urls: list[str] = Field(default_factory=list)  # ready-to-open Google search URLs


class GenerateDorksPlugin(BasePlugin[GenerateDorksInput, GenerateDorksOutput]):
    name = "generate_dorks"
    category = "identity"
    requires_key = None
    input_model = GenerateDorksInput
    output_model = GenerateDorksOutput

    __doc__ = (
        "Generate Google dork queries for a target (name/username): site:-restricted searches "
        "(linkedin/twitter/instagram/github/etc.), filetype:pdf, resume/cv, leaked/breach. "
        "Offline — feed the dorks into web_search to run them."
    )

    async def run(self, inp: GenerateDorksInput, ctx: PluginContext) -> GenerateDorksOutput:
        t = inp.target.strip().strip('"')
        extra = inp.extra_terms.strip()
        dorks = _build_dorks(t, site_dorks=inp.site_dorks, extra=extra)
        urls = [f"https://www.google.com/search?q={quote_plus(d)}" for d in dorks]
        out = GenerateDorksOutput(source=self.name, dorks=dorks, urls=urls)
        out.summary_markdown = _summary(t, dorks)
        out.entities = [Entity(type="username", value=t), Entity(type="person", value=t)]
        return out


def _build_dorks(target: str, *, site_dorks: bool, extra: str) -> list[str]:
    q = f'"{target}"'
    if extra:
        q = f'{q} {extra}'
    dorks: list[str] = []
    if site_dorks:
        for site in _SITES:
            dorks.append(f'{q} site:{site}')
    dorks += [
        f"{q} filetype:pdf",
        f'{q} inurl:profile',
        f"{q} resume OR cv",
        f"{q} leaked OR breach OR dump",
        f'intitle:"{target}"',
        f'{q} -site:linkedin.com -site:facebook.com',
    ]
    return dorks


def _summary(target: str, dorks: list[str]) -> str:
    lines = [f"**{target}** — {len(dorks)} dork(s) generated:"]
    for d in dorks:
        lines.append(f"- `{d}`")
    lines.append("Run these via `web_search` (or open the URLs) to get live results.")
    return "\n".join(lines)
