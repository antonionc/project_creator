"""OAuth2 authentication for Google Drive API."""

# Assisted-by: Cursor

from pathlib import Path
from typing import Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

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

    Credentials are cached in ~/.config/project_creator/token.json and
    automatically refreshed on subsequent calls.

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

    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                _TOKEN_PATH.unlink(missing_ok=True)
                raise RuntimeError(
                    "OAuth scopes have changed or token is invalid.\n"
                    "Your old token.json has been removed.\n"
                    "Please run:  project-creator setup  to re-authenticate."
                )
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        # Persist token for future runs
        _TOKEN_PATH.write_text(creds.to_json())
        ensure_config_permissions()

    return creds
