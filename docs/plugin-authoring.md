# Authoring a Plugin

## 1. Scaffold

```bash
uv run scripts/new_plugin.py identity my_lookup --desc "Look up a thing"
# -> creates src/cairn/plugins/identity/my_lookup.py
```

The plugin's primary input field is `target` — it becomes a **positional** CLI
argument (`cairn plugin my-lookup <target>`); any extra input fields become
`--flags`.

Optional extra fields may use either a static default (`limit: int = 15`) or
`Field(default_factory=...)` (e.g. a mutable list). Both are treated as optional
in the CLI and the agent tool schema — `_apply_signature` materializes
`default_factory` so Typer / PydanticAI don't mark the field required.

## 2. Implement `run()`

Edit the generated file. Use the shared `http_client(ctx)` helper for HTTP (it
reuses the injected browser-like client, or builds and closes a temporary one),
or `ctx.key("logical")` for an API key. Always return a `PluginOutput` with a
concise `summary_markdown` and any `entities`.

```python
from cairn.execution.http_util import http_client

async def run(self, inp, ctx):
    async with http_client(ctx) as http:
        r = await http.get(f"https://example.test/{inp.target}")
        r.raise_for_status()
        data = r.json()
        return MyOutput(
            source="my_lookup",
            summary_markdown=f"**{inp.target}** — found {len(data)} records.",
            entities=[Entity(type="thing", value=inp.target)],
        )
```

## 3. Shelling out (anti command-injection)

If your plugin wraps a CLI binary, go through the shared runner — it uses
`create_subprocess_exec` with list args, never a shell string:

```python
from cairn.execution.subprocess_util import run_subprocess

stdout, _ = await run_subprocess(["holehe", inp.target], timeout=ctx.timeout)
```

## 4. Mark a key requirement (optional)

For a paid source, set `requires_key = "virustotal"`. The plugin is then
auto-excluded until `CAIRN_VIRUSTOTAL_KEY` is set:

```python
class VirusTotalPlugin(BasePlugin[...]):
    name = "virustotal"
    category = "identity"
    requires_key = "virustotal"
```

## 5. Test

Add `tests/plugins/test_my_lookup.py` mocking `httpx` with
[`respx`](https://github.com/lundberg/respx). For a real call, mark it
`@pytest.mark.network`.

## 6. Done

Restart the REPL — the plugin is auto-discovered. No registration code needed.
