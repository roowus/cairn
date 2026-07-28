"""Have I Been Pwned v3 (key-gated) — breach exposure for an email."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)


class HibpInput(PluginInput):
    """`target` is an email address."""

    include_unverified: bool = False


class HibpOutput(PluginOutput):
    breaches: list[str] = Field(default_factory=list)


class HibpPlugin(BasePlugin[HibpInput, HibpOutput]):
    name = "hibp"
    category = "identity"
    requires_key = "hibp"
    input_model = HibpInput
    output_model = HibpOutput
    cost = CostSpec(unit="calls", paid=True, note="paid API key required (one-off purchase)")

    __doc__ = (
        "Check an email (target) for known data breaches via HaveIBeenPwned. Requires "
        "CAIRN_HIBP_KEY."
    )

    async def run(self, inp: HibpInput, ctx: PluginContext) -> HibpOutput:
        key = ctx.key("hibp") or ""
        http = ctx.http or httpx.AsyncClient(
            timeout=ctx.timeout, proxy=ctx.proxy, follow_redirects=True
        )
        r = await http.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{inp.target}",
            params={
                "truncateResponse": "false",
                "includeUnverified": str(inp.include_unverified).lower(),
            },
            headers={"hibp-api-key": key, "user-agent": ctx.user_agent},
        )
        if r.status_code == 404:
            return HibpOutput(
                source=self.name,
                summary_markdown=f"**{inp.target}** — HIBP: no breaches found. ✓",
                entities=[Entity(type="email", value=inp.target)],
            )
        r.raise_for_status()
        data: list[dict[str, Any]] = r.json()
        names = sorted({b.get("Name") or b.get("Title") for b in data if isinstance(b, dict)})
        preview = ", ".join(names)
        summary = f"**{inp.target}** — HIBP: found in {len(names)} breach(es): {preview}"
        return HibpOutput(
            source=self.name,
            summary_markdown=summary,
            breaches=names,
            entities=[Entity(type="email", value=inp.target, attrs={"breach_count": len(names)})],
        )
