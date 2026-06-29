"""Tests for project_creator.token_store."""

# Assisted-by: Cursor

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from project_creator import token_store as token_store_module
from project_creator.token_store import (
    KeychainStorageError,
    delete_token_json,
    load_token_json,
    save_token_json,
    uses_keychain_storage,
)


@pytest.fixture()
def token_path(tmp_path: Path) -> Path:
    return tmp_path / "token.json"


class TestUsesKeychainStorage:
    def test_true_on_darwin(self, monkeypatch):
        monkeypatch.setattr(token_store_module.sys, "platform", "darwin")
        assert uses_keychain_storage() is True

    def test_false_on_linux(self, monkeypatch):
        monkeypatch.setattr(token_store_module.sys, "platform", "linux")
        assert uses_keychain_storage() is False


class TestFileTokenStorage:
    def test_load_and_save_on_non_darwin(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: False)

        assert load_token_json(token_path) is None
        save_token_json(token_path, '{"token": "abc"}')
        assert token_path.read_text() == '{"token": "abc"}'
        assert load_token_json(token_path) == '{"token": "abc"}'

    def test_delete_removes_file(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: False)
        token_path.write_text('{"token": "abc"}')

        delete_token_json(token_path)

        assert not token_path.exists()


class TestKeychainTokenStorage:
    def test_save_load_delete_via_keychain(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: True)
        store: dict[str, str] = {}

        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = lambda svc, user: store.get(f"{svc}:{user}")
        mock_keyring.set_password.side_effect = lambda svc, user, pwd: store.__setitem__(f"{svc}:{user}", pwd)
        mock_keyring.delete_password.side_effect = lambda svc, user: store.pop(f"{svc}:{user}", None)
        mock_keyring.errors.PasswordDeleteError = Exception

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            save_token_json(token_path, '{"token": "secure"}')

        assert not token_path.exists()
        assert store["project-creator:google-oauth-token"] == '{"token": "secure"}'

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            assert load_token_json(token_path) == '{"token": "secure"}'

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            delete_token_json(token_path)

        assert store == {}

    def test_migrates_plaintext_token_to_keychain(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: True)
        token_path.write_text('{"token": "legacy"}')
        store: dict[str, str] = {}

        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = lambda svc, user: store.get(f"{svc}:{user}")
        mock_keyring.set_password.side_effect = lambda svc, user, pwd: store.__setitem__(f"{svc}:{user}", pwd)
        mock_keyring.errors.PasswordDeleteError = Exception

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            loaded = load_token_json(token_path)

        assert loaded == '{"token": "legacy"}'
        assert not token_path.exists()
        assert store["project-creator:google-oauth-token"] == '{"token": "legacy"}'

    def test_save_raises_on_keychain_failure(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: True)

        mock_keyring = MagicMock()
        mock_keyring.set_password.side_effect = RuntimeError("keychain locked")
        mock_keyring.errors.PasswordDeleteError = Exception

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with pytest.raises(KeychainStorageError, match="Failed to save"):
                save_token_json(token_path, '{"token": "secure"}')

        assert not token_path.exists()

    def test_load_raises_on_keychain_failure(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: True)

        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = RuntimeError("keychain unavailable")
        mock_keyring.errors.PasswordDeleteError = Exception

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with pytest.raises(KeychainStorageError, match="Failed to read"):
                load_token_json(token_path)

    def test_migration_does_not_delete_plaintext_when_save_fails(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: True)
        token_path.write_text('{"token": "legacy"}')

        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        mock_keyring.set_password.side_effect = RuntimeError("keychain locked")
        mock_keyring.errors.PasswordDeleteError = Exception

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            with pytest.raises(KeychainStorageError, match="Failed to save"):
                load_token_json(token_path)

        assert token_path.read_text() == '{"token": "legacy"}'

    def test_missing_keyring_raises_on_macos(self, token_path, monkeypatch):
        monkeypatch.setattr(token_store_module, "uses_keychain_storage", lambda: True)

        def _raise_import_error():
            raise KeychainStorageError("The 'keyring' package is required on macOS")

        monkeypatch.setattr(token_store_module, "_require_keyring", _raise_import_error)

        with pytest.raises(KeychainStorageError, match="keyring"):
            save_token_json(token_path, '{"token": "secure"}')
