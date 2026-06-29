"""OAuth token persistence with optional macOS Keychain encryption."""

# Assisted-by: Cursor

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_KEYRING_SERVICE = "project-creator"
_KEYRING_USERNAME = "google-oauth-token"


def uses_keychain_storage() -> bool:
    """Return True when tokens are stored in the macOS Keychain via keyring."""
    return sys.platform == "darwin"


def load_token_json(token_path: Path) -> Optional[str]:
    """Load OAuth token JSON from Keychain (macOS) or token file."""
    if uses_keychain_storage():
        token_json = _load_from_keychain()
        if token_json is not None:
            return token_json
        if token_path.exists():
            token_json = token_path.read_text()
            save_token_json(token_path, token_json)
            return token_json
        return None

    if token_path.exists():
        return token_path.read_text()
    return None


def save_token_json(token_path: Path, token_json: str) -> None:
    """Persist OAuth token JSON to Keychain (macOS) or token file."""
    if uses_keychain_storage():
        try:
            _save_to_keychain(token_json)
            token_path.unlink(missing_ok=True)
            return
        except Exception:
            pass

    token_path.write_text(token_json)


def delete_token_json(token_path: Path) -> None:
    """Remove stored OAuth token from Keychain and/or token file."""
    if uses_keychain_storage():
        _delete_from_keychain()
    token_path.unlink(missing_ok=True)


def _load_from_keychain() -> Optional[str]:
    try:
        import keyring
    except ImportError:
        return None

    try:
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        return None


def _save_to_keychain(token_json: str) -> None:
    import keyring

    keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, token_json)


def _delete_from_keychain() -> None:
    try:
        import keyring
    except ImportError:
        return

    try:
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        pass
