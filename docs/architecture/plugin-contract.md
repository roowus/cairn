# Plugin Contract

A plugin is one Python class that performs a single, deterministic intelligence
lookup. Plugins are auto-discovered — you do not register them anywhere.

## Types (`src/cairn/execution/base.py`)

- **`PluginContext`** — per-call runtime context injected by the runner:
  `timeout`, `proxy`, `user_agent`, `keys` (logical name → `SecretStr`),
  and an optional shared `httpx.AsyncClient`. Never logged wholesale.
- **`PluginInput`** / **`PluginOutput`** — Pydantic models. `PluginInput` has a
  `target`; `PluginOutput` carries `source`, `summary_markdown`, and an optional
  `entities: list[Entity]` for graph capture.
- **`Entity`** — `{type, value, attrs}`: a graph node (e.g. `ip`, `domain`,
  `email`, `asn`).
- **`BasePlugin[I, O]`** — the ABC every plugin implements.

## Class shape

```python
class BasePlugin(ABC, Generic[I, O]):
    name: ClassVar[str]  # "shodan_internetdb"
    category: ClassVar[str]  # "identity" | "infrastructure" | "web"
    requires_key: ClassVar[str | None] = None  # None = free; else logical key name
    input_model: ClassVar[type[I]]
    output_model: ClassVar[type[O]]

    async def run(self, inp: I, ctx: PluginContext) -> O: ...
    def available(self, ctx: PluginContext) -> bool: ...
```

`available()` returns `False` when `requires_key` is set but the key is absent.
Unavailable plugins are **silently excluded** from the agent's tool list and
from `cairn plugin list` — they never crash the run. Setting the key makes the
plugin appear on the next launch with zero code change.

## Discovery

- **In-tree:** place the module under `src/cairn/plugins/<category>/`. The
  registry walks `cairn.plugins.*` via `pkgutil`, imports each module, and
  registers every concrete `BasePlugin` subclass.
- **Out-of-tree:** a third-party package exposes a plugin via the
  `cairn.plugins` entry-point group in its own `pyproject.toml`.

## How a plugin becomes a tool

`cairn.orchestration.tool_adapter` wraps each available plugin as a PydanticAI
tool. PydanticAI derives the JSON schema from the function's `PluginInput`
annotation. The adapter calls `plugin.run`, writes the audit row, captures
entities, and wraps the summary in `<untrusted_external_data>` — so individual
plugins stay simple and the security invariant lives in one place.

The same registry also powers the headless CLI: `cairn plugin <name> ...` runs
any plugin directly, bypassing the LLM.
