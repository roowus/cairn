"""generate_dorks — build Google dork queries for a target (offline, free, no key).

Given a name / username / handle (person-focused default) OR a domain with a
``category`` (org/attack-surface dork corpus), emits the canonical OSINT dorks
(``site:`` restrictions, ``filetype:pdf``, ``resume OR cv``, ``leaked OR breach``,
plus a 9-category org corpus — exposed files / admin panels / secret leakage /
cloud & shadow-IT / docs / vuln indicators / internal tools / backups /
sector-specific) as both raw query strings and ready-to-open Google search URLs.
The agent typically feeds these into ``web_search`` to actually execute them.

Pure string generation; no network. The default set adapts the dork templates
used by OpenOSINT; the category corpus is ported from Claude-OSINT arsenal §18
(MIT) and trimmed to free-first (no paid search backends).
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

# Org/attack-surface dork corpus (Claude-OSINT arsenal §18). {t} = the target
# (usually a domain). 9 categories; each template is one dork.
_CATEGORY_DORKS: dict[str, list[str]] = {
    "files": [
        "site:{t} filetype:pdf",
        "site:{t} filetype:docx",
        "site:{t} filetype:doc",
        "site:{t} filetype:xlsx",
        "site:{t} filetype:csv",
        "site:{t} filetype:conf",
        "site:{t} filetype:txt",
        "site:{t} filetype:log",
    ],
    "admin": [
        "site:{t} inurl:admin",
        "site:{t} inurl:login",
        "site:{t} inurl:signin",
        "site:{t} inurl:dashboard",
        'site:{t} intitle:"admin"',
        "site:{t} inurl:wp-admin",
        "site:{t} inurl:cpanel",
        "site:{t} inurl:console",
    ],
    "secrets": [
        'site:{t} "api_key"',
        'site:{t} "aws_secret_access_key"',
        'site:{t} "BEGIN RSA PRIVATE KEY"',
        'site:{t} ext:env "DB_PASSWORD"',
        'site:{t} "authorization: bearer"',
        'site:{t} "AKIA"',
        'site:{t} "xox"',
        'site:{t} "client_secret"',
    ],
    "cloud": [
        'site:s3.amazonaws.com "{t}"',
        'site:blob.core.windows.net "{t}"',
        'site:storage.googleapis.com "{t}"',
        'site:github.com "{t}" "config"',
        'site:postman.com "{t}"',
        '"{t}" "AKIA" OR "xox"',
        'site:gitlab.com "{t}"',
        'site:pastebin.com "{t}"',
    ],
    "docs": [
        'site:{t} filetype:pptx',
        'site:{t} filetype:pdf "confidential"',
        'site:{t} "internal use only"',
        'site:{t} "do not distribute"',
        'site:{t} inurl:shared',
        'site:{t} filetype:pdf "draft"',
    ],
    "vulns": [
        'site:{t} inurl:id=',
        'site:{t} "SQL syntax"',
        'site:{t} "stack trace"',
        'site:{t} "Warning: mysql"',
        'site:{t} "You have an error in your SQL"',
        'site:{t} "Fatal error"',
        'site:{t} "thinkphp"',
        'site:{t} "laravel"',
    ],
    "internal": [
        "site:{t} inurl:jenkins",
        "site:{t} inurl:gitlab",
        "site:{t} inurl:phpmyadmin",
        "site:{t} inurl:actuator",
        "site:{t} inurl:elasticsearch",
        "site:{t} inurl:grafana",
        "site:{t} inurl:kibana",
        "site:{t} inurl:swagger",
    ],
    "backups": [
        "site:{t} ext:bak",
        "site:{t} ext:old",
        "site:{t} ext:backup",
        "site:{t} ext:swp",
        "site:{t} ext:sql",
        "site:{t} ext:tar",
        "site:{t} ext:zip",
        'site:{t} "dump.sql"',
    ],
    "sector": [
        'site:{t} filetype:pdf "HIPAA"',
        'site:{t} "PCI-DSS"',
        'site:{t} "SOX"',
        'site:{t} "GDPR"',
        'site:{t} filetype:pdf "invoice"',
        'site:{t} "proprietary and confidential"',
    ],
}
_CATEGORIES = list(_CATEGORY_DORKS.keys())


class GenerateDorksInput(PluginInput):
    """``target`` is a name/username/handle (default) or a domain (with ``category``)."""

    #: extra OR-terms to append to the person-focused default set, e.g. "email".
    extra_terms: str = ""
    #: include the site-restricted dorks (default True; person set only).
    site_dorks: bool = True
    #: org/attack-surface corpus category (domain target): one of the 9 categories
    #: or "all". Empty = the person-focused default set.
    category: str = Field(
        default="",
        description=(
            "Org dork corpus category "
            "(files|admin|secrets|cloud|docs|vulns|internal|backups|sector|all); "
            "empty = person set."
        ),
    )


class GenerateDorksOutput(PluginOutput):
    dorks: list[str] = Field(default_factory=list)  # raw query strings
    urls: list[str] = Field(default_factory=list)  # ready-to-open Google search URLs


class GenerateDorksPlugin(BasePlugin[GenerateDorksInput, GenerateDorksOutput]):
    name = "generate_dorks"
    category = "identity"
    requires_key = None
    detectability = "low"  # offline string generation — no network
    input_model = GenerateDorksInput
    output_model = GenerateDorksOutput

    __doc__ = (
        "Generate Google dork queries for a target. Person set (default): site:-"
        "restricted searches (linkedin/twitter/instagram/github/etc.), filetype:pdf, "
        "resume/cv, leaked/breach. Org set (category=files|admin|secrets|cloud|docs|"
        "vulns|internal|backups|sector|all, domain target): a 9-category attack-surface "
        "dork corpus. Offline — feed the dorks into web_search to run them."
    )

    async def run(self, inp: GenerateDorksInput, ctx: PluginContext) -> GenerateDorksOutput:
        t = inp.target.strip().strip('"')
        dorks = _build_dorks(
            t,
            site_dorks=inp.site_dorks,
            extra=inp.extra_terms.strip(),
            category=inp.category.strip(),
        )
        urls = [f"https://www.google.com/search?q={quote_plus(d)}" for d in dorks]
        out = GenerateDorksOutput(source=self.name, dorks=dorks, urls=urls)
        out.summary_markdown = _summary(t, dorks, inp.category.strip())
        out.entities = [Entity(type="username", value=t), Entity(type="person", value=t)]
        return out


def _build_dorks(
    target: str, *, site_dorks: bool, extra: str, category: str = ""
) -> list[str]:
    if category:
        cats = _CATEGORIES if category == "all" else [category]
        out: list[str] = []
        for cat in cats:
            for tpl in _CATEGORY_DORKS.get(cat, []):
                out.append(tpl.format(t=target))
        # dedupe, preserve order
        seen: set[str] = set()
        dedup: list[str] = []
        for d in out:
            if d not in seen:
                seen.add(d)
                dedup.append(d)
        return dedup

    q = f'"{target}"'
    if extra:
        q = f"{q} {extra}"
    dorks: list[str] = []
    if site_dorks:
        for site in _SITES:
            dorks.append(f"{q} site:{site}")
    dorks += [
        f"{q} filetype:pdf",
        f"{q} inurl:profile",
        f"{q} resume OR cv",
        f"{q} leaked OR breach OR dump",
        f'intitle:"{target}"',
        f"{q} -site:linkedin.com -site:facebook.com",
    ]
    return dorks


def _summary(target: str, dorks: list[str], category: str) -> str:
    scope = f" (category: {category})" if category else ""
    lines = [f"**{target}**{scope} — {len(dorks)} dork(s) generated:"]
    for d in dorks:
        lines.append(f"- `{d}`")
    lines.append("Run these via `web_search` (or open the URLs) to get live results.")
    return "\n".join(lines)
