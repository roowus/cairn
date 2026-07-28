# Authoring a Plugin

## 1. Scaffold

```bash
uv run scripts/new_plugin.py identity my_lookup --desc "Look up a thing"
# -> creates src/cairn/plugins/identity/my_lookup.py
```

The plugin's primary input field is `target` — it becomes a **positional** CLI
argument (`cairn plugin my-lookup <target>`); any extra input fields become
`--flags`.

## 2. Implement `run()`

Edit the generated file. Use `ctx.http` (an injected `httpx.AsyncClient`) for
HTTP, or `ctx.key("logical")` for an API key. Always return a
`PluginOutput` with a concise `summary_markdown` and any `entities`.

```python
async def run(self, inp, ctx):
    http = ctx.http or httpx.AsyncClient(timeout=ctx.timeout, proxy=ctx.proxy)
    r = await http.get(f"https://example.test/{inp.target}", headers={"User-Agent": ctx.user_agent})
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
