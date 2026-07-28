## Summary

<!-- What does this PR change, and why? One or two sentences. -->

## Type

<!-- check one -->

- [ ] `feat` — new capability
- [ ] `fix` — bug fix
- [ ] `refactor` — no behavior change
- [ ] `docs` — documentation only
- [ ] `test` — tests only
- [ ] `chore` — build / CI / tooling

## Checklist — rules that must not regress

<!-- See CONTRIBUTING.md "Rules that must not regress". These are Cairn's
     load-bearing invariants; tick each one. -->

- [ ] **No upward imports** — `reasoning` imports nothing from `orchestration`/`execution` (`tests/unit/test_layering.py` enforces this).
- [ ] **Hard-stop preserved** — tools return sanitized Markdown summaries, never raw payloads.
- [ ] **No shell strings** — all subprocesses use `create_subprocess_exec` with list args (`execution/subprocess_util.py`).
- [ ] **Untrusted data wrapped** — external content reaching the model goes through `<untrusted_external_data>` (`orchestration/tool_adapter.py`).
- [ ] **Secrets never enter model context** — keys live in `PluginContext.keys` / settings (never in prompts).
- [ ] **No arbitrary install/shell tool for the model** — external CLIs only via the allowlist in `execution/cli_tools.py`.

## Verification

- [ ] `make test` passes (unit, no network)
- [ ] `make lint` (`ruff check .`) is clean
- [ ] `make typecheck` reviewed — non-blocking in CI, but no new `mypy` errors introduced

## Notes

<!-- Anything reviewers should know; link any related issues or design notes. -->
