"""Entity detection and extraction from unstructured text.

The pivotable substrate of the investigator loop. When a plugin scrapes content
(web pages, search snippets, paste dumps), it calls :func:`extract_entities` to
pull out emails, usernames, IPs, domains, URLs, phone numbers, and crypto
addresses, then adds them to its ``PluginOutput.entities`` so they flow into the
graph and become next-step targets the agent can pivot onto — exactly the
"scrape a profile → find other identities in the posts/comments" move.

Pure stdlib; no upward imports (this is the ``core`` layer).
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_URL = re.compile(r"https?://[^\s<>\"')]+")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BTC = re.compile(r"\bbc1[a-zA-HJ-NP-Z0-9]{20,89}\b|\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
_ETH = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
# phone: require a leading + or 7+ contiguous digits with separators (heuristic)
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
_DOMAIN = re.compile(r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b")

_TRIM = ".,;:)]}>\"'"


@dataclass(frozen=True)
class ExtractedEntity:
    """A single entity pulled from text: a type tag + the raw value."""

    type: str
    value: str


def extract_entities(text: str, *, max_per_type: int = 50) -> list[ExtractedEntity]:
    """Extract pivotable entities from ``text``, deduplicated, order-stable.

    Types: ``email``, ``url``, ``ip``, ``crypto_btc``, ``crypto_eth``,
    ``phone``, ``domain``. Domains that are part of an already-captured email or
    URL are skipped to avoid noise.
    """
    found: list[ExtractedEntity] = []
    seen: set[tuple[str, str]] = set()

    def _add(etype: str, raw: str) -> None:
        val = raw.strip().strip(_TRIM)
        if not val:
            return
        key = (etype, val.lower())
        if len([e for e in found if e.type == etype]) >= max_per_type:
            return
        if key in seen:
            return
        seen.add(key)
        found.append(ExtractedEntity(etype, val))

    for m in _EMAIL.finditer(text):
        _add("email", m.group(0))
    for m in _URL.finditer(text):
        _add("url", m.group(0))
    for m in _IPV4.finditer(text):
        try:
            ipaddress.ip_address(m.group(0))
        except ValueError:
            continue
        _add("ip", m.group(0))
    for m in _BTC.finditer(text):
        _add("crypto_btc", m.group(0))
    for m in _ETH.finditer(text):
        _add("crypto_eth", m.group(0))
    for m in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 7 <= len(digits) <= 15:
            _add("phone", m.group(0).strip())
    emails_urls = {e.value for e in found if e.type in ("email", "url")}
    for m in _DOMAIN.finditer(text):
        d = m.group(0).strip().strip(_TRIM)
        if any(d.lower() in eu.lower() for eu in emails_urls):
            continue
        _add("domain", d)
    return found
