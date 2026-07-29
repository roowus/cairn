"""Security helpers: untrusted-data wrapping and secret redaction."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

# Tags that delimit untrusted content handed back to the model. See
# docs/architecture/security.md — the system prompt instructs the model to treat
# the contents as passive observation only.
_OPEN = "<untrusted_external_data"
_CLOSE = "</untrusted_external_data>"


def _attr_escape(s: str) -> str:
    """Escape a string for safe interpolation into a double-quoted XML attribute."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def wrap_untrusted(source: str, target: str, content: str) -> str:
    """Wrap external content so the model cannot mistake it for instructions."""
    # Defensive: strip any already-present untrusted tags from nested content so
    # an attacker can't forge a closing tag to break out of the wrapper.
    cleaned = content.replace(_OPEN, "&lt;untrusted_external_data")
    cleaned = cleaned.replace(_CLOSE, "&lt;/untrusted_external_data&gt;")
    # source/target are interpolated into the opening tag's *attributes*, so they
    # must be attribute-escaped too — not just `content`. A model-authored
    # run_command target can carry the literal closing tag or a double-quote;
    # interpolated raw, that breaks the wrapper and lets text appear OUTSIDE
    # <untrusted_external_data> (a Layer-B / anti-injection bypass). `source` is a
    # fixed plugin name today, but escape it anyway for defense in depth.
    src = _attr_escape(source)
    tgt = _attr_escape(target)
    return f'{_OPEN} source="{src}" target="{tgt}">\n{cleaned}\n{_CLOSE}'


# Common secret shapes we scrub from any text we persist.
_SECRET_PATTERNS = [
    # Generic API keys / bearer tokens.
    re.compile(
        r"(?i)(api[_-]?key|token|secret|bearer|authorization)[\"' :=]+([A-Za-z0-9_\-/+=]{12,})"
    ),
    # AWS access-key IDs: long-term (AKIA) + STS temporary (ASIA) + role/user.
    re.compile(r"(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}"),
    # sk-... style (Anthropic/OpenAI).
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
]


def redact_text(text: str) -> str:
    """Replace likely secret substrings with ``[REDACTED]``."""
    redacted = text
    for pat in _SECRET_PATTERNS:
        redacted = pat.sub(
            lambda m: (
                f"{m.group(1) if m.lastindex else ''}=[REDACTED]" if m.lastindex else "[REDACTED]"
            ),
            redacted,
        )
    return redacted


# Nested archive wrappers (Wayback playback, archive.today, …) put the real
# URL — including any userinfo — inside the *path*, so urlparse sees no
# username/password on the outer URL. Match scheme://user:pass@host (or
# user@host) segments anywhere in the string.
_EMBEDDED_USERINFO = re.compile(
    r"(?P<pre>(?:https?|ftp)://)(?P<userinfo>[^/@\s]+@)(?P<host>[^/\s?#]+)",
    re.IGNORECASE,
)


def _strip_userinfo_netloc(url: str) -> str:
    """Strip userinfo from a single absolute URL via urlparse."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if parsed.username is None and parsed.password is None:
        return url
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        # IPv6 literals need brackets in netloc.
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunparse(
        (parsed.scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def redact_url_userinfo(url: str) -> str:
    """Drop embedded credentials (``user:pass@host``) from a URL.

    Wayback CDX and other archives often return historical URLs with HTTP
    basic-auth userinfo. Those must not reach model summaries, entity graphs,
    or CLI output as pivot fuel. Also handles **nested** archive wrappers where
    the credentialed URL sits in the path, e.g.
    ``http://web.archive.org/web/…/http://user:pass@example.com/``.
    Non-URL strings and URLs without userinfo are returned unchanged.
    """
    if not url or "@" not in url:
        return url
    # First: outer-URL userinfo (http://user:pass@host/...).
    cleaned = _strip_userinfo_netloc(url)
    # Second: any nested scheme://userinfo@host inside path/query (Wayback etc.).
    if "@" in cleaned:
        cleaned = _EMBEDDED_USERINFO.sub(
            lambda m: f"{m.group('pre')}{m.group('host')}", cleaned
        )
    return cleaned


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-looking strings in dicts/lists for safe logging."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if _looks_secret(k) else redact_secrets(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact_secrets(v) for v in value)
    return value


def _looks_secret(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in ("key", "token", "secret", "password", "auth"))
