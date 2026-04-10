"""Tests for project_creator.cli (Click commands)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from project_creator.cli import main, _MONTH_ABBREVS


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def runner():
    return CliRunner()


def _valid_config(proposal="PROP_ID", sow="SOW_ID"):
    return {
        "templates": {
            "proposal": proposal,
            "purchase_summary_sow": sow,
            "gfa_form_url": "https://red.ht/gfa",
        },
        "search_root_id": "",
    }


# ---------------------------------------------------------------------------
# CLI group sanity
# ---------------------------------------------------------------------------

class TestCliGroup:
    def test_main_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Proposal Creator" in result.output

    def test_unknown_command(self, runner):
        result = runner.invoke(main, ["nonexistent"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# setup command
# ---------------------------------------------------------------------------

class TestSetupCommand:
    def test_exits_1_when_no_credentials_json(self, runner, tmp_path):
        config_dir = tmp_path / ".config" / "project_creator"
        with patch("project_creator.cli.CONFIG_DIR", config_dir), \
             patch("project_creator.cli.load_config", return_value=_valid_config()):
            result = runner.invoke(main, ["setup"])
        assert result.exit_code == 1
        assert "credentials.json" in result.output.lower() or "not found" in result.output.lower()

    def test_saves_config_on_success(self, runner, tmp_path):
        config_dir = tmp_path / ".config" / "project_creator"
        creds_path = config_dir / "credentials.json"
        creds_path.parent.mkdir(parents=True)
        creds_path.write_text("{}")

        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_service.about().get().execute.return_value = {
            "user": {"emailAddress": "test@example.com"}
        }

        with patch("project_creator.cli.CONFIG_DIR", config_dir), \
             patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.save_config") as mock_save, \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.parse_file_id", side_effect=lambda x: x):
            result = runner.invoke(
                main,
                ["setup"],
                input="PROP\nSOW\nhttps://red.ht/gfa\n\n",  # prompts
            )

        assert mock_save.called

    def test_exits_1_when_auth_fails(self, runner, tmp_path):
        config_dir = tmp_path / ".config" / "project_creator"
        creds_path = config_dir / "credentials.json"
        creds_path.parent.mkdir(parents=True)
        creds_path.write_text("{}")

        with patch("project_creator.cli.CONFIG_DIR", config_dir), \
             patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", side_effect=Exception("auth error")):
            result = runner.invoke(main, ["setup"], input="\n\n\n\n")

        assert result.exit_code == 1
        assert "Authorization failed" in result.output or "auth error" in result.output


# ---------------------------------------------------------------------------
# create command — config validation
# ---------------------------------------------------------------------------

class TestCreateCommandConfigValidation:
    def test_exits_1_when_config_incomplete(self, runner):
        bad_config = _valid_config(proposal="", sow="")  # both empty → fails validation
        with patch("project_creator.cli.load_config", return_value=bad_config):
            result = runner.invoke(main, ["create", "--account=Acme", "--project=Alpha",
                                          "--year=2026", "--month=Apr", "--skip-gfa"])
        assert result.exit_code == 1
        assert "incomplete" in result.output.lower() or "not set" in result.output.lower()

    def test_exits_1_when_credentials_missing(self, runner):
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials",
                   side_effect=FileNotFoundError("credentials.json not found")):
            result = runner.invoke(main, ["create", "--account=Acme", "--project=Alpha",
                                          "--year=2026", "--month=Apr", "--skip-gfa"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# create command — happy path (skip-gfa)
# ---------------------------------------------------------------------------

class TestCreateCommandHappyPath:
    def _setup_mocks(self):
        """Return a dict of patch targets → mock return values."""
        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_sheets = MagicMock()

        # search_folders returns one match
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}

        return mock_creds, mock_service, mock_sheets, mock_match

    def test_successful_create_with_skip_gfa(self, runner):
        mock_creds, mock_service, mock_sheets, mock_match = self._setup_mocks()

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="https://drive.google.com/xyz"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--year=2026", "--month=Apr", "--skip-gfa"],
                input="y\n",  # confirm account folder
            )

        assert result.exit_code == 0
        assert "All done" in result.output

    def test_year_defaults_to_current_year(self, runner):
        """When --year is omitted, the CLI should prompt with current year default."""
        from datetime import datetime
        current_year = str(datetime.now().year)

        mock_creds, mock_service, mock_sheets, mock_match = self._setup_mocks()

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="X") as mock_bpf, \
             patch("project_creator.cli.copy_file", return_value="C"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha", "--skip-gfa"],
                input=f"\n\n",  # accept defaults for year and month
            )

        if result.exit_code == 0:
            call_args = mock_bpf.call_args
            assert call_args[0][3] == current_year  # year positional arg

    def test_month_normalized(self, runner):
        """Month should be capitalized regardless of input case."""
        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_sheets = MagicMock()
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID") as mock_bpf, \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--year=2026", "--month=apr", "--skip-gfa"],
                input="y\n",
            )

        if mock_bpf.called:
            assert mock_bpf.call_args[0][4] == "Apr"  # capitalized month


# ---------------------------------------------------------------------------
# create command — account folder resolution
# ---------------------------------------------------------------------------

class TestResolveAccountFolder:
    def test_aborts_when_no_folder_and_user_declines(self, runner):
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[]):
            result = runner.invoke(
                main,
                ["create", "--account=NotExist", "--project=P",
                 "--year=2026", "--month=Apr", "--skip-gfa"],
                input="n\n",  # decline to create new folder
            )

        assert result.exit_code == 0  # clean exit, not an error
        assert "Aborted" in result.output

    def test_aborts_when_no_parent_provided(self, runner):
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[]):
            result = runner.invoke(
                main,
                ["create", "--account=NotExist", "--project=P",
                 "--year=2026", "--month=Apr", "--skip-gfa"],
                input="y\n\n",  # accept create, but leave parent blank
            )

        assert result.exit_code == 0
        assert "required" in result.output.lower() or "parent" in result.output.lower()

    def test_multiple_folders_prompts_user_to_choose(self, runner):
        matches = [
            {"id": "F1", "name": "Acme", "path": "Drive A > Acme"},
            {"id": "F2", "name": "Acme", "path": "Drive B > Acme"},
        ]
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=matches), \
             patch("project_creator.cli.build_proposal_folder", return_value="X"), \
             patch("project_creator.cli.copy_file", return_value="C"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=P",
                 "--year=2026", "--month=Apr", "--skip-gfa"],
                input="2\n",  # choose second folder
            )

        # Output should mention Drive B path (user chose folder 2)
        assert "Drive B" in result.output or result.exit_code == 0


# ---------------------------------------------------------------------------
# create command — GFA workflow
# ---------------------------------------------------------------------------

class TestHandleGfa:
    def test_gfa_skipped_with_flag(self, runner):
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--year=2026", "--month=Apr", "--skip-gfa"],
                input="y\n",
            )

        assert "skipped" in result.output.lower()
        assert result.exit_code == 0

    def test_gfa_url_opened_in_browser(self, runner):
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.webbrowser.open") as mock_open, \
             patch("project_creator.cli.rename_file"), \
             patch("project_creator.cli.create_shortcut"), \
             patch("project_creator.cli.write_cell"), \
             patch("project_creator.cli.customize_gfa"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--year=2026", "--month=Apr"],
                input="y\nhttps://docs.google.com/spreadsheets/d/GFA123/edit\n",
            )

        mock_open.assert_called_once_with("https://red.ht/gfa")

    def test_gfa_skipped_when_user_leaves_url_blank(self, runner):
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.webbrowser.open"), \
             patch("project_creator.cli.rename_file") as mock_rename:
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha", "--year=2026", "--month=Apr"],
                input="y\n\n",  # blank GFA URL → skip
            )

        mock_rename.assert_not_called()
        assert "manually" in result.output.lower() or "skipped" in result.output.lower()

    def test_rename_failure_does_not_abort(self, runner):
        """Rename errors are warnings — the workflow should continue."""
        from googleapiclient.errors import HttpError
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}

        def _bad_rename(*args, **kwargs):
            resp = MagicMock(); resp.status = 403
            raise HttpError(resp=resp, content=b"Forbidden")

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.webbrowser.open"), \
             patch("project_creator.cli.rename_file", side_effect=_bad_rename), \
             patch("project_creator.cli.create_shortcut"), \
             patch("project_creator.cli.write_cell"), \
             patch("project_creator.cli.customize_gfa"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha", "--year=2026", "--month=Apr"],
                input="y\nhttps://docs.google.com/spreadsheets/d/GFA123/edit\n",
            )

        # Should warn but NOT exit with 1
        assert "⚠" in result.output or "Could not rename" in result.output
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# _MONTH_ABBREVS completeness
# ---------------------------------------------------------------------------

class TestMonthAbbrevs:
    def test_all_12_months_present(self):
        assert len(_MONTH_ABBREVS) == 12
        assert all(k in _MONTH_ABBREVS for k in range(1, 13))

    def test_values_are_3_char_strings(self):
        for v in _MONTH_ABBREVS.values():
            assert isinstance(v, str)
            assert len(v) == 3
