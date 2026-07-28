"""Agentic file/exec tools — Claude Code-level workspace control.

These plugins give the brain read/write/list/download/run access inside the
workspace (cwd + scratch dir). They relax the *execution-permission* layer
(Layer A) while the *anti-injection* layer (Layer B) is preserved structurally:
every result flows back wrapped in ``<untrusted_external_data>`` via the audited
``_tool`` closure in :mod:`cairn.orchestration.tool_adapter`, exactly like every
other plugin. See :mod:`cairn.execution.workspace` for the boundary + permission
gate + env-scrub primitives.

Install capability is NOT duplicated here — the existing ``install_cli`` plugin
(:mod:`cairn.plugins.identity.install_cli`) covers the whole analyzer allowlist
once tools are added to :data:`cairn.execution.cli_tools._TOOLS`.
"""
