"""Configuration management for project-creator."""

# Assisted-by: Cursor

from __future__ import annotations  # enables built-in generics on Python 3.9

import re
import stat
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import yaml

CONFIG_DIR = Path.home() / ".config" / "project_creator"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

DEFAULT_GFA_DOMAIN = "redhat.com"
DEFAULT_DOMAIN_ALLOW_LIST = ["redhat.com"]

_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
_ALLOWED_GFA_FORM_HOSTS = frozenset({"red.ht", "docs.google.com", "forms.gle"})

_DEFAULT_CONFIG: Dict[str, Any] = {
    "templates": {
        "proposal": "",
        "purchase_summary_sow": "",
        "cu_calculator": "",
        "gfa_form_url": "https://red.ht/gfa",
    },
    "search_root_id": "",
    "modifications_dir": "",
    "gfa": {
        "domain": DEFAULT_GFA_DOMAIN,
        "domain_allow_list": list(DEFAULT_DOMAIN_ALLOW_LIST),
    },
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

    gfa_form_url = templates.get("gfa_form_url", "")
    if gfa_form_url and not _is_valid_gfa_form_url(gfa_form_url):
        errors.append(
            "templates.gfa_form_url must be an HTTPS URL on an allowed host "
            "(red.ht, docs.google.com, forms.gle)"
        )

    modifications_dir = config.get("modifications_dir", "")
    if modifications_dir:
        errors.extend(_validate_modifications_dir(modifications_dir))

    gfa_config = config.get("gfa") or {}
    allow_list = get_domain_allow_list(config)
    if not allow_list:
        errors.append("gfa.domain_allow_list must contain at least one domain")

    for domain in allow_list:
        if not _is_valid_domain(domain):
            errors.append(f"gfa.domain_allow_list entry is invalid: {domain!r}")

    domain = str(gfa_config.get("domain", DEFAULT_GFA_DOMAIN)).lower().strip()
    if domain and not _is_valid_domain(domain):
        errors.append(f"gfa.domain is invalid: {domain!r}")
    elif domain and allow_list and domain not in allow_list:
        errors.append(
            f"gfa.domain '{domain}' is not in gfa.domain_allow_list "
            f"({', '.join(allow_list)})"
        )

    return errors


def get_domain_allow_list(config: Dict[str, Any]) -> List[str]:
    """Return normalized GFA domain allow-list from config."""
    gfa_config = config.get("gfa") or {}
    allow_list = gfa_config.get("domain_allow_list")
    if isinstance(allow_list, list) and allow_list:
        return [
            str(domain).lower().strip()
            for domain in allow_list
            if str(domain).strip()
        ]
    return list(DEFAULT_DOMAIN_ALLOW_LIST)


def is_domain_allowed(config: Dict[str, Any], domain: str) -> bool:
    """Return True if *domain* is permitted by the configured allow-list."""
    normalized = domain.lower().strip()
    return normalized in get_domain_allow_list(config)


def _is_valid_domain(domain: str) -> bool:
    return bool(domain and _DOMAIN_RE.fullmatch(domain))


def _is_valid_gfa_form_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    return parsed.hostname in _ALLOWED_GFA_FORM_HOSTS


def _validate_modifications_dir(path_str: str) -> List[str]:
    errors: List[str] = []
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        errors.append(f"modifications_dir does not exist: {path}")
        return errors
    if not path.is_dir():
        errors.append(f"modifications_dir is not a directory: {path}")
        return errors

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o022:
        errors.append(
            f"modifications_dir must not be group- or world-writable: {path}"
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
