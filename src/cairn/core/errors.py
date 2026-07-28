"""Cairn exception hierarchy."""

from __future__ import annotations


class CairnError(Exception):
    """Base class for all Cairn errors."""


class ConfigError(CairnError):
    """Configuration is missing or invalid (e.g. no LLM provider configured)."""


class PluginError(CairnError):
    """A plugin failed or is misconfigured."""


class ProviderError(CairnError):
    """The LLM provider could not be constructed from the given settings."""
