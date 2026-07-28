"""Logging setup with Rich rendering."""

from __future__ import annotations

import logging

from rich.logging import RichHandler

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logging once with a Rich handler. Idempotent."""
    global _CONFIGURED
    logger = logging.getLogger("cairn")
    if not _CONFIGURED:
        handler = RichHandler(show_time=True, show_path=False, markup=True, rich_tracebacks=True)
        handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
        logger.addHandler(handler)
        logger.propagate = False
        _CONFIGURED = True
    logger.setLevel(level.upper())
    return logger


def get_logger(name: str = "cairn") -> logging.Logger:
    return logging.getLogger(name)
