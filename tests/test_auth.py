"""Tests for project_creator.auth."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from google.auth.exceptions import RefreshError

import project_creator.auth as auth_module
from project_creator.auth import get_credentials, SCOPES


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect auth module paths to a temporary directory."""
    config_dir = tmp_path / ".config" / "project_creator"
    creds_path = config_dir / "credentials.json"
    token_path = config_dir / "token.json"
    monkeypatch.setattr(auth_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(auth_module, "_CREDS_PATH", creds_path)
    monkeypatch.setattr(auth_module, "_TOKEN_PATH", token_path)
    return config_dir, creds_path, token_path


def _write_file(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# get_credentials — missing credentials.json
# ---------------------------------------------------------------------------

class TestGetCredentialsMissingFile:
    def test_raises_file_not_found_when_no_credentials_json(self, tmp_auth):
        _, creds_path, _ = tmp_auth
        assert not creds_path.exists()
        with pytest.raises(FileNotFoundError, match="credentials.json"):
            get_credentials()

    def test_error_message_contains_path(self, tmp_auth):
        _, creds_path, _ = tmp_auth
        with pytest.raises(FileNotFoundError) as exc_info:
            get_credentials()
        assert str(creds_path) in str(exc_info.value)


# ---------------------------------------------------------------------------
# get_credentials — valid cached token
# ---------------------------------------------------------------------------

class TestGetCredentialsValidToken:
    def test_returns_cached_valid_creds(self, tmp_auth):
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        _write_file(token_path, '{"token": "tok"}')

        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch("project_creator.auth.Credentials.from_authorized_user_file", return_value=mock_creds):
            result = get_credentials()

        assert result is mock_creds

    def test_does_not_call_refresh_when_valid(self, tmp_auth):
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        _write_file(token_path, '{"token": "tok"}')

        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch("project_creator.auth.Credentials.from_authorized_user_file", return_value=mock_creds):
            get_credentials()

        mock_creds.refresh.assert_not_called()


# ---------------------------------------------------------------------------
# get_credentials — expired token with refresh_token → refresh
# ---------------------------------------------------------------------------

class TestGetCredentialsExpiredToken:
    def test_refreshes_expired_creds(self, tmp_auth):
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        _write_file(token_path, '{"token": "old"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "REFRESH"
        mock_creds.to_json.return_value = '{"token": "new"}'

        with patch("project_creator.auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
             patch("project_creator.auth.Request") as mock_request:
            result = get_credentials()

        mock_creds.refresh.assert_called_once()
        assert result is mock_creds

    def test_persists_refreshed_token(self, tmp_auth):
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        _write_file(token_path, '{"token": "old"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "REFRESH"
        mock_creds.to_json.return_value = '{"token": "new"}'

        with patch("project_creator.auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
             patch("project_creator.auth.Request"):
            get_credentials()

        assert token_path.exists()
        assert token_path.read_text() == '{"token": "new"}'

    def test_token_file_has_restricted_permissions(self, tmp_auth):
        import stat
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        _write_file(token_path, '{"token": "old"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "REFRESH"
        mock_creds.to_json.return_value = '{"token": "new"}'

        with patch("project_creator.auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
             patch("project_creator.auth.Request"):
            get_credentials()

        mode = stat.S_IMODE(token_path.stat().st_mode)
        assert mode == 0o600


# ---------------------------------------------------------------------------
# get_credentials — RefreshError during token refresh
# ---------------------------------------------------------------------------

class TestGetCredentialsRefreshError:
    def test_refresh_error_deletes_token_and_raises_runtime(self, tmp_auth):
        """A RefreshError during refresh should delete the stale token and raise RuntimeError."""
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        _write_file(token_path, '{"token": "stale"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "REFRESH"
        mock_creds.refresh.side_effect = RefreshError("token revoked")

        with patch("project_creator.auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
             patch("project_creator.auth.Request"):
            with pytest.raises(RuntimeError, match="setup"):
                get_credentials()

        # token.json must be deleted so the user can re-authenticate cleanly
        assert not token_path.exists()


# ---------------------------------------------------------------------------
# get_credentials — no token file, no refresh_token → OAuth flow
# ---------------------------------------------------------------------------

class TestGetCredentialsBrowserFlow:
    def test_runs_browser_flow_when_no_token(self, tmp_auth):
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        # token_path does NOT exist

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "fresh"}'

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch("project_creator.auth.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow):
            result = get_credentials()

        mock_flow.run_local_server.assert_called_once_with(port=0)
        assert result is mock_creds

    def test_passes_scopes_to_flow(self, tmp_auth):
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = "{}"

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch("project_creator.auth.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow) as mock_factory:
            get_credentials()

        mock_factory.assert_called_once_with(str(creds_path), SCOPES)

    def test_creds_with_no_refresh_token_triggers_flow(self, tmp_auth):
        """Expired creds without a refresh_token must fall through to browser flow."""
        config_dir, creds_path, token_path = tmp_auth
        _write_file(creds_path)
        _write_file(token_path, '{"token": "stale"}')

        # Expired, but no refresh_token
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = None  # ← no refresh token
        mock_creds.to_json.return_value = '{"token": "new"}'

        fresh_creds = MagicMock()
        fresh_creds.to_json.return_value = '{"token": "new"}'

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fresh_creds

        with patch("project_creator.auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
             patch("project_creator.auth.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow):
            result = get_credentials()

        mock_flow.run_local_server.assert_called_once()
        assert result is fresh_creds
