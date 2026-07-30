"""h1_reference — HackerOne disclosed-reports reference agent (keyless, free).

During recon, surface community-validated techniques from HackerOne Hacktivity:
search disclosed bug-bounty reports by keyword and rank them (top-voted =
best-validated techniques, top-bounty = business-impact framing). **No API key**
— it hits HackerOne's public GraphQL endpoint. Ported from Claude-OSINT's
``h1_reference.py`` (MIT, arsenal §29.3) and adapted to Cairn's plugin contract.

Outputs are structured reports emitted as ``url`` entities (with severity /
program / title attrs) so they join the graph and the brain can pivot on them.
The endpoint is a *third-party index* (HackerOne), so detectability is low; the
brain treats returned titles/URLs as untrusted observation like any tool result.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel, Field

from cairn.execution.base import (
    BasePlugin,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)
from cairn.execution.http_util import http_client

_GRAPHQL_URL = "https://hackerone.com/graphql"
_PAGE_SIZE = 50
_RATE_SLEEP = 0.3  # polite inter-page delay

# H1's GraphQL server crashes on named variables + substate filters + report
# fields (empirical, per the upstream script), so we build inline queries.
_REPORT_FIELDS = (
    "... on HacktivityDocument { id severity_rating total_awarded_amount currency "
    "cwe cve_ids votes team { handle name } reporter { username } "
    "report { _id title url } }"
)


class H1Report(BaseModel):
    title: str
    severity: str = "none"
    bounty: int | None = None
    currency: str = "USD"
    cwe: str = ""
    cves: list[str] = Field(default_factory=list)
    program: str = ""
    reporter: str = ""
    url: str = ""
    votes: int = 0


class H1ReferenceInput(PluginInput):
    """``target`` is a keyword/regex matched against report titles (client-side)."""

    target: str = Field(
        ...,
        description=(
            "Keyword/regex to match in disclosed report titles (e.g. 'SSRF', 'OAuth bypass')."
        ),
    )
    sort: str = Field(
        default="top_voted",
        description="Ranking: 'top_voted' (validated techniques) or 'top_bounty' (impact framing).",
    )
    limit: int = Field(default=10, ge=1, le=50)
    pages: int = Field(default=3, ge=1, le=20, description="Pages to fetch (50/page).")


class H1ReferenceOutput(PluginOutput):
    reports: list[H1Report] = Field(default_factory=list)
    total_fetched: int = 0


class H1ReferencePlugin(BasePlugin[H1ReferenceInput, H1ReferenceOutput]):
    name = "h1_reference"
    category = "web"
    requires_key = None
    detectability = "low"  # third-party index (HackerOne), not the target
    input_model = H1ReferenceInput
    output_model = H1ReferenceOutput

    __doc__ = (
        "Query HackerOne Hacktivity for disclosed reports by keyword (target = "
        "keyword/regex). Keyless/free; ranks by top-voted (validated techniques) "
        "or top-bounty. Returns title/severity/bounty/cwe/url per report as url "
        "entities. Reference for tradecraft/vuln-prioritization; never invents URLs."
    )

    async def run(self, inp: H1ReferenceInput, ctx: PluginContext) -> H1ReferenceOutput:
        sort_field = "total_awarded_amount" if inp.sort == "top_bounty" else "votes"
        kw = re.compile(inp.target, re.IGNORECASE) if inp.target.strip() else None
        headers = {
            "Content-Type": "application/json",
            "User-Agent": ctx.user_agent,
            "Origin": "https://hackerone.com",
            "Referer": "https://hackerone.com/hacktivity",
        }
        nodes: list[dict[str, Any]] = []
        cursor: str | None = None
        async with http_client(ctx, timeout=20.0) as http:
            for page in range(1, inp.pages + 1):
                query = _build_query(sort_field, cursor)
                try:
                    resp = await http.post(_GRAPHQL_URL, json={"query": query}, headers=headers)
                except Exception as exc:
                    return _empty(self.name, f"**h1_reference error**: {exc}")
                if resp.status_code != 200:
                    return _empty(self.name, f"**h1_reference failed**: HTTP {resp.status_code}")
                try:
                    data = resp.json()
                except Exception:
                    return _empty(self.name, "**h1_reference error**: non-JSON response")
                if data.get("errors") or data.get("data") is None:
                    break
                search = data["data"].get("search") or {}
                page_nodes = search.get("nodes", [])
                nodes.extend(page_nodes)
                cursor = (search.get("pageInfo") or {}).get("endCursor")
                if not page_nodes or not cursor:
                    break
                if page < inp.pages:
                    await asyncio.sleep(_RATE_SLEEP)

        reports = [_to_report(n) for n in nodes if n.get("report")]
        if kw:
            reports = [r for r in reports if kw.search(r.title)]
        # client-side sort when we couldn't sort server-side (kept simple: sort-only)
        reports.sort(key=lambda r: r.votes, reverse=True)
        reports = reports[: inp.limit]

        out = H1ReferenceOutput(source=self.name, reports=reports, total_fetched=len(nodes))
        out.entities = [
            Entity(
                type="url",
                value=r.url,
                attrs={"severity": r.severity, "program": r.program, "title": r.title},
            )
            for r in reports
            if r.url
        ]
        out.summary_markdown = _summary(reports, len(nodes), inp.target, inp.sort)
        return out


def _build_query(sort_field: str, after: str | None) -> str:
    after_clause = f', after: "{_escape(after)}"' if after else ""
    return (
        "{ search(index: CompleteHacktivityReportIndex, query: {bool: {}}, "
        f"first: {_PAGE_SIZE}{after_clause}, sort: {{field: \"{sort_field}\", direction: DESC}}) "
        f"{{ total_count pageInfo {{ endCursor }} nodes {{ {_REPORT_FIELDS} }} }} }}"
    )


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _to_report(node: dict[str, Any]) -> H1Report:
    report = node.get("report") or {}
    team = node.get("team") or {}
    reporter = node.get("reporter") or {}
    return H1Report(
        title=report.get("title", "Unknown"),
        severity=(node.get("severity_rating") or "none"),
        bounty=node.get("total_awarded_amount"),
        currency=node.get("currency") or "USD",
        cwe=node.get("cwe") or "",
        cves=list(node.get("cve_ids") or []),
        program=team.get("handle", ""),
        reporter=reporter.get("username", ""),
        url=report.get("url", ""),
        votes=node.get("votes") or 0,
    )


def _summary(reports: list[H1Report], total: int, query: str, sort: str) -> str:
    if not reports:
        return f"No HackerOne reports matched `{query}` (fetched {total})."
    lines = [
        f"**{len(reports)}** HackerOne report(s) for `{query}` (sort: {sort}, fetched {total}):"
    ]
    for i, r in enumerate(reports, 1):
        sev = r.severity.upper()
        bounty = f"${r.bounty:,} {r.currency}" if r.bounty else "no bounty"
        lines.append(
            f"{i}. **[{sev}]** {r.title} — {r.program} ({bounty}, {r.votes} votes)\n   {r.url}"
        )
    return "\n".join(lines)


def _empty(source: str, summary: str) -> H1ReferenceOutput:
    out = H1ReferenceOutput(source=source)
    out.summary_markdown = summary
    return out
