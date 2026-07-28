"""crt.sh — certificate transparency subdomain discovery (free, no key)."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginInput, PluginOutput


class CrtshInput(PluginInput):
    """`target` is a domain (e.g. example.com)."""

    limit: int = 50


class CrtshOutput(PluginOutput):
    subdomains: list[str] = Field(default_factory=list)


class CrtshPlugin(BasePlugin[CrtshInput, CrtshOutput]):
    name = "crtsh"
    category = "infrastructure"
    requires_key = None
    input_model = CrtshInput
    output_model = CrtshOutput

    __doc__ = (
        "Find subdomains of a domain (target) via the crt.sh certificate-transparency log. Free."
    )

    async def run(self, inp: CrtshInput, ctx: PluginContext) -> CrtshOutput:
        # CT queries are routinely slow; give this free endpoint more headroom.
        timeout = max(ctx.timeout, 60.0)
        http = ctx.http or httpx.AsyncClient(
            timeout=timeout, proxy=ctx.proxy, follow_redirects=True
        )
        base = inp.target.lstrip("*.").lstrip(".")
        try:
            r = await http.get(
                "https://crt.sh/",
                params={"q": f"%.{base}", "output": "json"},
                headers={"Accept": "application/json"},
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            return CrtshOutput(
                source=self.name,
                summary_markdown=(
                    f"**{inp.target}** — crt.sh unreachable: {type(exc).__name__} "
                    f"(CT queries are often slow; retry or raise timeout)."
                ),
                entities=[Entity(type="domain", value=inp.target)],
            )
        except httpx.HTTPError as exc:
            return CrtshOutput(
                source=self.name,
                summary_markdown=(
                    f"**{inp.target}** — crt.sh unreachable: {type(exc).__name__}: {exc}"
                ),
                entities=[Entity(type="domain", value=inp.target)],
            )

        if r.status_code != 200:
            return CrtshOutput(
                source=self.name,
                summary_markdown=(
                    f"**{inp.target}** — crt.sh unavailable (HTTP {r.status_code})."
                ),
                entities=[Entity(type="domain", value=inp.target)],
            )
        if not r.text.strip():
            return CrtshOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — crt.sh: 0 subdomains.",
                entities=[Entity(type="domain", value=inp.target)],
            )
        try:
            rows: list[dict[str, Any]] = r.json()
        except ValueError:
            return CrtshOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — crt.sh: response was not valid JSON.",
                entities=[Entity(type="domain", value=inp.target)],
            )
        if not rows:
            return CrtshOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — crt.sh: 0 subdomains.",
                entities=[Entity(type="domain", value=inp.target)],
            )

        found: set[str] = set()
        for row in rows:
            for name_field in ("name_value", "common_name"):
                val = row.get(name_field)
                if not val:
                    continue
                for line in str(val).splitlines():
                    name = line.strip().lstrip("*.").lower()
                    if name and name.endswith(base) and name != base:
                        found.add(name)
        subdomains = sorted(found)[: inp.limit]
        if not subdomains:
            summary = f"**{inp.target}** — crt.sh: 0 subdomains."
        else:
            preview = ", ".join(subdomains[:20])
            extra = f" (+{len(subdomains) - 20} more)" if len(subdomains) > 20 else ""
            summary = f"**{inp.target}** — crt.sh: {len(subdomains)} subdomains: {preview}{extra}"
        return CrtshOutput(
            source=self.name,
            summary_markdown=summary,
            subdomains=subdomains,
            entities=[Entity(type="domain", value=inp.target)]
            + [Entity(type="domain", value=s) for s in subdomains],
        )
