# ADR 0002 — src-layout + uv

**Status:** Accepted

## Context
Pick a package layout and dependency manager for a Python 3.12+ CLI.

## Decision
- **Layout:** `src/cairn/` (src-layout).
- **Manager:** [uv](https://docs.astral.sh/uv) (lockfile committed).

## Rationale
- **src-layout** prevents accidental imports from the repo root during tests
  (a common source of false-positive test passes), separates the import name
  from the repo name, and is what modern tooling expects.
- **uv** is already installed locally; it is dramatically faster than
  pip/poetry, manages the interpreter (auto-fetches 3.12–3.14), and produces a
  reproducible `uv.lock`.

## Consequences
- Devs run `uv sync` and `uv run cairn` instead of activating a venv manually.
- `.python-version` pins the dev interpreter; `requires-python = ">=3.12"`
  keeps the floor conservative against 3.14 wheel-lag risk.
