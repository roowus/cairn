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

from cairn.core.security import redact_url_userinfo

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

    # URLs first so we can (a) skip emails that are only URL userinfo and
    # (b) store credential-stripped URL values in the entity graph.
    url_spans: list[tuple[int, int]] = []
    for m in _URL.finditer(text):
        url_spans.append(m.span())
        _add("url", redact_url_userinfo(m.group(0)))

    def _email_in_url(span: tuple[int, int]) -> bool:
        start, end = span
        return any(u_start <= start and end <= u_end for u_start, u_end in url_spans)

    def _looks_like_userinfo(match: re.Match[str]) -> bool:
        # Free-text ``user:pass@host`` (no scheme) — the email regex only grabs
        # ``pass@host``; a username+colon immediately before is credential-shaped.
        # Exclude URI schemes (``mailto:``, ``http:``, …) so real addresses keep.
        start = match.start()
        if start == 0 or text[start - 1] != ":":
            return False
        j = start - 2
        while j >= 0 and (text[j].isalnum() or text[j] in "._-+"):
            j -= 1
        user = text[j + 1 : start - 1]
        if not user:
            return False
        return user.lower() not in {"mailto", "http", "https", "ftp", "file", "ssh", "git"}

    for m in _EMAIL.finditer(text):
        if _email_in_url(m.span()) or _looks_like_userinfo(m):
            continue
        _add("email", m.group(0))
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
        # Typed-asset enrichment (moat P1): a host with >=3 labels (>=2 dots) is
        # ALSO a subdomain. Additive — the bare "domain" type is kept unchanged so
        # existing pivots/graph keys don't shift; the extra "subdomain" type lets
        # the pivot engine distinguish apex domains from subdomains. A real
        # public-suffix split (apex vs sub) is deferred to the pivot engine.
        if d.count(".") >= 2:
            _add("subdomain", d)
    return found
