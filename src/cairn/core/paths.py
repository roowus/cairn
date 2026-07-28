"""Filesystem paths for Cairn.

All paths resolve under the config directory, which defaults to ``~/.cairn``
and can be overridden with the ``CAIRN_CONFIG_DIR`` environment variable. These
are *functions* (not module constants) so tests that point ``CAIRN_CONFIG_DIR``
at a temp directory see the change without re-importing.
"""

from __future__ import annotations

import os
from pathlib import Path

_APP_NAME = "cairn"


def config_dir() -> Path:
    """Resolve the config/data directory (``~/.cairn`` by default)."""
    env = os.environ.get(f"{_APP_NAME.upper()}_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / f".{_APP_NAME}"


def workspace_dir() -> Path:
    """Scratch workspace for agentic file ops (downloads, analyzer artifacts)."""
    return config_dir() / "workspace"


def db_path() -> Path:
    return config_dir() / "cairn.db"


def history_dir() -> Path:
    return config_dir() / "history"


def config_toml_path() -> Path:
    return config_dir() / "config.toml"


def env_path() -> Path:
    return config_dir() / ".env"


def ensure_dirs() -> Path:
    """Create the config/history directories. Returns the config dir."""
    cfg = config_dir()
    (cfg / "history").mkdir(parents=True, exist_ok=True)
    return cfg
