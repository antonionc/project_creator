"""OAuth2 authentication for Google Drive API."""

from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]

CONFIG_DIR = Path.home() / ".config" / "project_creator"
_CREDS_PATH = CONFIG_DIR / "credentials.json"
_TOKEN_PATH = CONFIG_DIR / "token.json"


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

    creds: Optional[Credentials] = None

    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        # Persist token for future runs
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.chmod(0o700)
        _TOKEN_PATH.write_text(creds.to_json())
        _TOKEN_PATH.chmod(0o600)

    return creds
