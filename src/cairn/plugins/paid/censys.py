"""Censys v2 (key-gated) — host services & certificates.

The key is ``<API_ID>:<API_SECRET>`` (HTTP Basic auth).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from cairn.execution.base import (
    BasePlugin,
    CostSpec,
    Entity,
    PluginContext,
    PluginInput,
    PluginOutput,
)
from cairn.execution.http_util import http_client


class CensysInput(PluginInput):
    """`target` is an IP address."""


class CensysOutput(PluginOutput):
    services: list[str] = Field(default_factory=list)
    asn: str | None = None
    location: str | None = None


class CensysPlugin(BasePlugin[CensysInput, CensysOutput]):
    name = "censys"
    category = "identity"
    requires_key = "censys"
    input_model = CensysInput
    output_model = CensysOutput
    cost = CostSpec(unit="credits", per_call=1.0, paid=True, note="v2 host lookup; search quota")

    __doc__ = (
        "Censys host view for an IP (target): services, ASN, location. Requires "
        "CAIRN_CENSYS_KEY (id:secret)."
    )

    async def run(self, inp: CensysInput, ctx: PluginContext) -> CensysOutput:
        raw = ctx.key("censys") or ""
        api_id, _, secret = raw.partition(":")
        async with http_client(ctx) as http:
            r = await http.get(
                f"https://search.censys.io/api/v2/hosts/{inp.target}",
                auth=(api_id, secret),
            )
            if r.status_code == 404:
                return CensysOutput(
                    source=self.name,
                    summary_markdown=f"**{inp.target}** — Censys: no data.",
                    entities=[Entity(type="ip", value=inp.target)],
                )
            r.raise_for_status()
            result: dict[str, Any] = (r.json().get("result") or {}).get("services", [])
            services = sorted({s.get("service_name", "?") for s in result if isinstance(s, dict)})
            summary = f"**{inp.target}** — Censys\n- Services: {', '.join(services) or 'none'}\n"
            return CensysOutput(
                source=self.name,
                summary_markdown=summary,
                services=services,
                entities=[Entity(type="ip", value=inp.target)],
            )
