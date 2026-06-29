"""OAuth2 authentication for Google Drive API."""

# Assisted-by: Cursor

import json
from pathlib import Path
from typing import Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .token_store import delete_token_json, load_token_json, save_token_json, uses_keychain_storage

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CONFIG_DIR = Path.home() / ".config" / "project_creator"
_CREDS_PATH = CONFIG_DIR / "credentials.json"
_TOKEN_PATH = CONFIG_DIR / "token.json"


def ensure_config_permissions() -> None:
    """Ensure the config directory and secret files have restrictive permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    if _CREDS_PATH.exists():
        _CREDS_PATH.chmod(0o600)
    if _TOKEN_PATH.exists():
        _TOKEN_PATH.chmod(0o600)


def get_credentials() -> Credentials:
    """Return valid OAuth2 credentials, running the browser flow if needed.

    Credentials are cached in the macOS Keychain (on macOS) or
    ~/.config/project_creator/token.json and automatically refreshed on
    subsequent calls.

    Raises:
        FileNotFoundError: if credentials.json has not been placed in CONFIG_DIR.
    """
    if not _CREDS_PATH.exists():
        raise FileNotFoundError(
            f"Google OAuth credentials not found at:\n  {_CREDS_PATH}\n\n"
            "Please download credentials.json from Google Cloud Console and place it\n"
            "in that directory, then run:  project-creator setup\n\n"
            "See README.md for step-by-step instructions."
        )

    ensure_config_permissions()

    creds: Optional[Credentials] = None
    token_json = load_token_json(_TOKEN_PATH)

    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                delete_token_json(_TOKEN_PATH)
                raise RuntimeError(
                    "OAuth scopes have changed or token is invalid.\n"
                    "Your stored OAuth token has been removed.\n"
                    "Please run:  project-creator setup  to re-authenticate."
                )
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        save_token_json(_TOKEN_PATH, creds.to_json())
        ensure_config_permissions()

    return creds
