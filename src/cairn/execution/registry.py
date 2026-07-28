"""Plugin discovery and registry.

Plugins live under ``cairn.plugins.*`` (in-tree) and are auto-imported via
:mod:`pkgutil`. Third-party packages register plugins via the ``cairn.plugins``
entry-point group. Every concrete :class:`~cairn.execution.base.BasePlugin`
subclass is instantiated and registered once.

A plugin module that fails to import (e.g. an optional dependency is missing)
is skipped with a warning — it never breaks discovery.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import pkgutil
import warnings
from typing import Any

from cairn.core.logging import get_logger
from cairn.execution.base import BasePlugin, PluginContext

_log = get_logger("cairn.registry")
_ENTRY_POINT_GROUP = "cairn.plugins"


class PluginRegistry:
    """Maps plugin name -> plugin instance."""

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin[Any, Any]] = {}

    def register(self, plugin: BasePlugin[Any, Any]) -> None:
        if not getattr(plugin, "name", ""):
            raise ValueError(f"plugin {plugin!r} has no name")
        if plugin.name in self._plugins:
            raise ValueError(f"duplicate plugin name: {plugin.name!r}")
        self._plugins[plugin.name] = plugin

    def all(self) -> list[BasePlugin[Any, Any]]:
        return list(self._plugins.values())

    def available(self, ctx: PluginContext) -> list[BasePlugin[Any, Any]]:
        """Plugins the brain may call: key-available AND (not daily-limited unless opted in).

        Key gating lives on the plugin (``available``); the daily-quota
        preference is a policy, enforced here so listing/discovery can still see
        every plugin regardless of the toggle.
        """
        return [
            p
            for p in self._plugins.values()
            if p.available(ctx) and (ctx.allow_daily_limited or not p.daily_limited)
        ]

    def get(self, name: str) -> BasePlugin[Any, Any] | None:
        return self._plugins.get(name)

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: object) -> bool:
        return name in self._plugins


def discover() -> PluginRegistry:
    """Discover and instantiate all available plugins."""
    registry = PluginRegistry()

    # 1) In-tree: import every module under cairn.plugins so subclasses exist.
    import cairn.plugins

    for modinfo in pkgutil.walk_packages(cairn.plugins.__path__, "cairn.plugins."):
        try:
            importlib.import_module(modinfo.name)
        except Exception as exc:  # optional dep missing, etc.
            warnings.warn(f"could not import plugin module {modinfo.name}: {exc}", stacklevel=2)
            _log.warning("skipping plugin module %s: %s", modinfo.name, exc)

    # 2) Collect every concrete BasePlugin subclass found.
    _collect_subclasses(BasePlugin, registry)

    # 3) Out-of-tree plugins via entry points.
    _collect_entry_points(registry)

    _log.info("discovered %d plugin(s): %s", len(registry), sorted(registry._plugins))
    return registry


def _collect_subclasses(cls: type, registry: PluginRegistry) -> None:
    for sub in cls.__subclasses__():
        _collect_subclasses(sub, registry)
        if getattr(sub, "__abstractmethods__", None):
            continue  # still abstract / a base mixin
        if not getattr(sub, "name", ""):
            continue
        if sub.name in registry:
            continue
        try:
            registry.register(sub())
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("failed to instantiate plugin %s: %s", getattr(sub, "name", sub), exc)


def _collect_entry_points(registry: PluginRegistry) -> None:
    try:
        eps = importlib.metadata.entry_points()
        if hasattr(eps, "select"):
            group = eps.select(group=_ENTRY_POINT_GROUP)
        else:  # Python < 3.10 fallback
            group = eps.get(_ENTRY_POINT_GROUP, [])
    except Exception as exc:  # pragma: no cover
        _log.debug("entry point discovery failed: %s", exc)
        return
    for ep in group:
        try:
            obj = ep.load()
            registry.register(obj() if isinstance(obj, type) else obj)
        except Exception as exc:
            _log.warning("failed to load entry point %s: %s", ep.name, exc)
