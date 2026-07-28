#!/usr/bin/env python3
"""Scaffold a new Cairn plugin.

Usage:
    uv run scripts/new_plugin.py identity breach_report
    uv run scripts/new_plugin.py paid virustotal --key virustotal

Writes a plugin module under src/cairn/plugins/<category>/<name>.py and
prints next steps.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VALID_CATEGORIES = ("identity", "infrastructure", "web", "paid")

TEMPLATE_FREE = '''"""{name}: {desc}."""
from __future__ import annotations

import httpx
from pydantic import BaseModel

from cairn.execution.base import BasePlugin, Entity, PluginContext, PluginOutput


class {Cls}Input(BaseModel):
    target: str


class {Cls}Output(PluginOutput):
    # add typed result fields here
    pass


class {Cls}Plugin(BasePlugin["{Cls}Input", "{Cls}Output"]):
    name = "{name}"
    category = "{category}"
    requires_key = None
    input_model = {Cls}Input
    output_model = {Cls}Output

    __doc__ = "{desc}."

    async def run(self, inp: "{Cls}Input", ctx: PluginContext) -> "{Cls}Output":
        http = ctx.http or httpx.AsyncClient(timeout=ctx.timeout, proxy=ctx.proxy)
        # TODO: implement the lookup against a free, unauthenticated API.
        return {Cls}Output(
            source="{name}",
            summary_markdown=f"**{{inp.target}}** — {desc} (not yet implemented).",
            entities=[Entity(type="unknown", value=inp.target)],
        )
'''

TEMPLATE_PAID = TEMPLATE_FREE  # same skeleton; set requires_key below


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def class_name(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name)
    return "".join(p.capitalize() for p in parts if p)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a Cairn plugin.")
    ap.add_argument("category", choices=VALID_CATEGORIES)
    ap.add_argument("name", help="snake_case plugin name, e.g. shodan_internetdb")
    ap.add_argument("--key", help="logical key name (required for 'paid')", default=None)
    ap.add_argument("--desc", default="OSINT lookup")
    args = ap.parse_args()

    name = slugify(args.name)
    cls = class_name(args.name)
    requires_key = "None"
    if args.category == "paid":
        key = args.key or name.replace("_", "")
        requires_key = f'"{key}"'

    src = Path(__file__).resolve().parent.parent / "src" / "cairn" / "plugins" / args.category
    src.mkdir(parents=True, exist_ok=True)
    (src.parent / "__init__.py").touch(exist_ok=True)
    (src / "__init__.py").touch(exist_ok=True)
    path = src / f"{name}.py"

    if path.exists():
        print(f"ERROR: {path} already exists", file=sys.stderr)
        return 1

    body = TEMPLATE_FREE.format(name=name, cls=cls, category=args.category, desc=args.desc)
    body = body.replace("requires_key = None", f"requires_key = {requires_key}")
    path.write_text(body, encoding="utf-8")

    print(f"Created: {path}")
    print("Next: implement run(), then add it to tests/plugins/.")
    print("It is auto-discovered — no registration code needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
