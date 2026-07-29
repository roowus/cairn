"""holehe plugin — parsing of holehe v1.61 stdout (pure parse, no network).

holehe v1.61 ends every run with a legend line
``[+] Email used, [-] Email not used, [x] Rate limit, [!] Error`` whose first
token ("Email") must NOT be captured as a platform. The fixture below mirrors the
raw v1.61 output (flags match the plugin: --only-used --no-color --no-clear -NP).
"""

from __future__ import annotations

from cairn.execution.base import PluginContext
from cairn.plugins.identity.holehe import _FOUND, HoleheInput, HolehePlugin

# Raw holehe v1.61 stdout for a throwaway address (example.com is RFC 2606
# reserved, so this is no one's real mailbox). Includes the stray "[+] Email
# used" legend and a [+] line carrying a recovery email, to prove only the bare
# domain of each real site is captured.
HOLEHE_V1_61_STDOUT = b"""\
*************************
   target@example.com
*************************
[+] adobe.com
[+] blizzard.com
[+] github.com email: alt@recovery.org
[+] spotify.com

[+] Email used, [-] Email not used, [x] Rate limit, [!] Error
4 websites checked in 38.5 seconds
"""


async def test_holehe_extracts_domains_not_email_legend(monkeypatch):
    """run() returns only real domains; the legend's "Email" never survives.

    Also guards the invocation: ``-NP``/``--no-password-recovery`` must NOT be
    passed — those probes are holehe's core detection, and skipping them makes it
    fast-fail every site (~0.4s) and report "no platforms" (the false-negative
    regression that reopened this issue).
    """
    captured: list[list[str]] = []

    async def fake_run_cli_tool(*args, **kwargs):
        captured.append(args[1] if len(args) > 1 else kwargs.get("args", []))
        return HOLEHE_V1_61_STDOUT, b""

    monkeypatch.setattr("cairn.plugins.identity.holehe.run_cli_tool", fake_run_cli_tool)

    out = await HolehePlugin().run(
        HoleheInput(target="target@example.com"), PluginContext(http=None)
    )

    assert out.sites == ["adobe.com", "blizzard.com", "github.com", "spotify.com"]
    assert "Email" not in out.sites  # the regression: bogus "Email" platform
    # Regression guard: never re-add the flag that cripples holehe's detection.
    holehe_args = captured[0]
    assert "-NP" not in holehe_args
    assert "--no-password-recovery" not in holehe_args


def test_found_regex_skips_non_domain_tokens():
    """_FOUND matches only domain-shaped [+] tokens (a "." + TLD)."""
    found = {m.group(1) for m in _FOUND.finditer(HOLEHE_V1_61_STDOUT.decode())}

    assert "Email" not in found  # legend word has no dot
    assert "adobe.com" in found
    assert "github.com" in found  # recovery-email suffix is not swallowed
