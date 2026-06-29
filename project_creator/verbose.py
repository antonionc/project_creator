"""Verbose/debug output control for the CLI."""

# Assisted-by: Cursor

from __future__ import annotations

import os

_verbose_enabled = False


def set_verbose(enabled: bool) -> None:
    """Enable or disable verbose output for the current process."""
    global _verbose_enabled
    _verbose_enabled = enabled


def is_verbose() -> bool:
    """Return True when verbose output is enabled via flag or environment."""
    if _verbose_enabled:
        return True
    return os.environ.get("PROJECT_CREATOR_DEBUG", "").lower() in ("1", "true", "yes")
