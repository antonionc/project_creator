"""Configuration management for project-creator."""

from __future__ import annotations  # enables built-in generics on Python 3.9

from pathlib import Path
from typing import Any, Dict, List

import yaml

CONFIG_DIR = Path.home() / ".config" / "project_creator"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

_DEFAULT_CONFIG: Dict[str, Any] = {
    "templates": {
        "proposal": "",
        "purchase_summary_sow": "",
        "gfa_form_url": "https://red.ht/gfa",
    },
    "search_root_id": "",
}


def load_config() -> Dict[str, Any]:
    """Load config from disk, merging with defaults for any missing keys."""
    if not CONFIG_PATH.exists():
        return _deep_merge({}, _DEFAULT_CONFIG)

    with open(CONFIG_PATH) as fh:
        loaded = yaml.safe_load(fh) or {}

    return _deep_merge(loaded, _DEFAULT_CONFIG)


def save_config(config: Dict[str, Any]) -> None:
    """Persist config to ~/.config/project_creator/config.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    with open(CONFIG_PATH, "w") as fh:
        yaml.dump(config, fh, default_flow_style=False, allow_unicode=True)
    CONFIG_PATH.chmod(0o600)


def validate_config(config: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable validation errors (empty means valid)."""
    errors: List[str] = []
    templates = config.get("templates", {})

    if not templates.get("proposal"):
        errors.append(
            "templates.proposal is not set — run 'project-creator setup' to configure"
        )
    if not templates.get("purchase_summary_sow"):
        errors.append(
            "templates.purchase_summary_sow is not set — run 'project-creator setup' to configure"
        )

    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: Dict, defaults: Dict) -> Dict:
    """Return *base* with any keys missing from it filled in from *defaults*."""
    result = dict(defaults)
    for key, value in base.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(value, result[key])
        else:
            result[key] = value
    return result
