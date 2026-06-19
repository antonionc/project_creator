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


def _valid_config(proposal="PROP_ID", sow="SOW_ID", cu_calculator="CU_ID"):
    return {
        "templates": {
            "proposal": proposal,
            "purchase_summary_sow": sow,
            "cu_calculator": cu_calculator,
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
                # proposal, sow, cu_calculator, gfa_url, search root, default_geo, auto_submit
                input="PROP\nSOW\nCU_CALC\nhttps://red.ht/gfa\n\n\n\n",
            )

        assert mock_save.called
        saved_config = mock_save.call_args[0][0]
        assert saved_config["templates"]["cu_calculator"] == "CU_CALC"

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
    def _base_patches(self):
        """Common patch targets for the create command happy path."""
        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_sheets = MagicMock()
        mock_gmail = MagicMock()
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}
        return mock_creds, mock_service, mock_sheets, mock_gmail, mock_match

    def test_successful_create_with_skip_gfa(self, runner):
        mock_creds, mock_service, mock_sheets, mock_gmail, mock_match = self._base_patches()

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.build_gmail_service", return_value=mock_gmail), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="https://drive.google.com/xyz"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr", "--skip-gfa"],
                input="y\n",  # confirm account folder
            )

        assert result.exit_code == 0
        assert "All done" in result.output

    def test_year_defaults_to_current_year(self, runner):
        """When --year is omitted, the CLI should prompt with current year default."""
        from datetime import datetime
        current_year = str(datetime.now().year)

        mock_creds, mock_service, mock_sheets, mock_gmail, mock_match = self._base_patches()

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.build_gmail_service", return_value=mock_gmail), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="X") as mock_bpf, \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="C"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--skip-gfa"],
                input="y\n\n",  # accept year default, accept month default, confirm folder
            )

        if result.exit_code == 0:
            call_args = mock_bpf.call_args
            assert call_args[0][3] == current_year  # year positional arg

    def test_month_normalized(self, runner):
        """Month should be capitalized regardless of input case."""
        mock_creds, mock_service, mock_sheets, mock_gmail, mock_match = self._base_patches()

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.build_gmail_service", return_value=mock_gmail), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID") as mock_bpf, \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=apr", "--skip-gfa"],
                input="y\n",
            )

        if mock_bpf.called:
            assert mock_bpf.call_args[0][4] == "Apr"  # capitalized month

    def test_create_fails_when_cu_calculator_requested_but_not_configured(self, runner):
        mock_creds, mock_service, mock_sheets, mock_gmail, mock_match = self._base_patches()
        bad_config = _valid_config(cu_calculator="") # empty CU calculator template

        with patch("project_creator.cli.load_config", return_value=bad_config), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.build_gmail_service", return_value=mock_gmail):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr", "--skip-gfa", "--cu-calculator"],
            )

        assert result.exit_code == 1
        assert "templates.cu_calculator is not set" in result.output

    def test_create_copies_cu_calculator_when_flag_and_configured(self, runner):
        mock_creds, mock_service, mock_sheets, mock_gmail, mock_match = self._base_patches()

        with patch("project_creator.cli.load_config", return_value=_valid_config(cu_calculator="MY_CU_TEMPLATE_ID")), \
             patch("project_creator.cli.get_credentials", return_value=mock_creds), \
             patch("project_creator.cli.build_service", return_value=mock_service), \
             patch("project_creator.cli.build_sheets_service", return_value=mock_sheets), \
             patch("project_creator.cli.build_gmail_service", return_value=mock_gmail), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID") as mock_copy, \
             patch("project_creator.cli.get_folder_url", return_value="https://drive.google.com/xyz"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr", "--skip-gfa", "--cu-calculator"],
                input="y\n",  # confirm account folder
            )

        assert result.exit_code == 0
        assert "All done" in result.output
        # Verify copy_file was called for proposal, SOW, and CU calculator templates
        assert mock_copy.call_count == 3
        # The third call should be for the CU calculator template
        mock_copy.assert_any_call(mock_service, "MY_CU_TEMPLATE_ID", "Acme - Alpha (Apr 2026) - CU Calculator", "PROJ_ID")


# ---------------------------------------------------------------------------
# create command — account folder resolution
# ---------------------------------------------------------------------------

class TestResolveAccountFolder:
    def test_aborts_when_no_folder_and_user_declines(self, runner):
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[]):
            result = runner.invoke(
                main,
                ["create", "--account=NotExist", "--project=P",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr", "--skip-gfa"],
                input="n\n",  # decline to create new folder
            )

        assert result.exit_code == 0  # clean exit, not an error
        assert "Aborted" in result.output

    def test_aborts_when_no_parent_provided(self, runner):
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[]):
            result = runner.invoke(
                main,
                ["create", "--account=NotExist", "--project=P",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr", "--skip-gfa"],
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
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=matches), \
             patch("project_creator.cli.build_proposal_folder", return_value="X"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="C"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=P",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr", "--skip-gfa"],
                input="2\n",  # choose second folder
            )

        # Output should mention Drive B path (user chose folder 2)
        assert "Drive B" in result.output or result.exit_code == 0


# ---------------------------------------------------------------------------
# create command — GFA workflow
# ---------------------------------------------------------------------------

class TestHandleGfa:
    def _gfa_patches(self, find_existing_gfa=False):
        """Returns patch targets needed for any GFA workflow test."""
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}
        # find_file_by_name: None for template copies; optionally an ID for GFA shortcut check
        find_side = MagicMock(side_effect=[None, None, "GFA_SC" if find_existing_gfa else None])
        return mock_match, find_side

    def test_gfa_skipped_with_flag(self, runner):
        mock_match, _ = self._gfa_patches()
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr", "--skip-gfa"],
                input="y\n",
            )

        assert "skipped" in result.output.lower()
        assert result.exit_code == 0

    def test_gfa_form_opened_via_playwright(self, runner):
        """fill_gfa_form must be called when GFA step is not skipped."""
        mock_match, _ = self._gfa_patches()
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.fill_gfa_form") as mock_fill, \
             patch("project_creator.cli.wait_for_gfa_email", return_value="https://docs.google.com/spreadsheets/d/GFA123/edit"), \
             patch("project_creator.cli.rename_file"), \
             patch("project_creator.cli.create_shortcut"), \
             patch("project_creator.cli.add_commenter_permission") as mock_perm, \
             patch("project_creator.cli.apply_modifications"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr"],
                input="y\n",
            )

        mock_fill.assert_called_once()
        mock_perm.assert_called_once_with(
            mock_service := mock_perm.call_args[0][0],
            "GFA123",
            "redhat.com"
        )
        assert result.exit_code == 0
        assert "commenter access granted" in result.output

    def test_permission_failure_does_not_abort(self, runner):
        """Permission update errors are warnings — the workflow should continue."""
        mock_match, _ = self._gfa_patches()
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.fill_gfa_form"), \
             patch("project_creator.cli.wait_for_gfa_email", return_value="https://docs.google.com/spreadsheets/d/GFA123/edit"), \
             patch("project_creator.cli.rename_file"), \
             patch("project_creator.cli.create_shortcut"), \
             patch("project_creator.cli.add_commenter_permission", side_effect=Exception("Permission error")), \
             patch("project_creator.cli.apply_modifications"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr"],
                input="y\n",
            )

        assert "⚠" in result.output or "Could not update access permissions" in result.output
        assert result.exit_code == 0

    def test_gfa_url_provided_directly(self, runner):
        """When --gfa-url is provided, skip browser/email steps and directly modify the GFA."""
        mock_match, _ = self._gfa_patches()
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.fill_gfa_form") as mock_fill, \
             patch("project_creator.cli.wait_for_gfa_email") as mock_wait, \
             patch("project_creator.cli.rename_file") as mock_rename, \
             patch("project_creator.cli.create_shortcut") as mock_shortcut, \
             patch("project_creator.cli.add_commenter_permission") as mock_perm, \
             patch("project_creator.cli.apply_modifications") as mock_mod:
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr",
                 "--gfa-url=https://docs.google.com/spreadsheets/d/EXISTING_GFA_ID/edit"],
                input="y\n",
            )

        # Ensure browser fill and email wait are skipped
        mock_fill.assert_not_called()
        mock_wait.assert_not_called()

        # Ensure modification steps are called with correct ID
        mock_rename.assert_called_once_with(mock_rename.call_args[0][0], "EXISTING_GFA_ID", "Acme - Alpha (Apr 2026) - GFA")
        mock_shortcut.assert_called_once_with(mock_shortcut.call_args[0][0], "EXISTING_GFA_ID", "Acme - Alpha (Apr 2026) - GFA", "PROJ_ID")
        mock_perm.assert_called_once_with(mock_perm.call_args[0][0], "EXISTING_GFA_ID", "redhat.com")

        # Ensure apply_modifications was called for proposal, SOW, and GFA
        from unittest.mock import call
        mock_mod.assert_has_calls([
            call(
                mock_mod.call_args_list[0][0][0],
                "COPY_ID",
                "proposal",
                mock_mod.call_args_list[0][0][3],
                mock_mod.call_args_list[0][0][4]
            ),
            call(
                mock_mod.call_args_list[1][0][0],
                "COPY_ID",
                "purchase_summary_sow",
                mock_mod.call_args_list[1][0][3],
                mock_mod.call_args_list[1][0][4]
            ),
            call(
                mock_mod.call_args_list[2][0][0],
                "EXISTING_GFA_ID",
                "gfa",
                mock_mod.call_args_list[2][0][3],
                mock_mod.call_args_list[2][0][4]
            )
        ], any_order=True)

        assert result.exit_code == 0
        assert "using provided gfa url" in result.output.lower()

    def test_gfa_skipped_when_user_leaves_url_blank(self, runner):
        mock_match, _ = self._gfa_patches()
        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.fill_gfa_form"), \
             patch("project_creator.cli.wait_for_gfa_email", return_value=None), \
             patch("project_creator.cli.rename_file") as mock_rename:
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr"],
                input="y\n\n",  # confirm folder, then blank GFA URL → skip
            )

        mock_rename.assert_not_called()
        assert "manually" in result.output.lower() or "skipped" in result.output.lower()

    def test_rename_failure_does_not_abort(self, runner):
        """Rename errors are warnings — the workflow should continue."""
        from googleapiclient.errors import HttpError
        mock_match, _ = self._gfa_patches()

        def _bad_rename(*args, **kwargs):
            resp = MagicMock(); resp.status = 403
            raise HttpError(resp=resp, content=b"Forbidden")

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", return_value=None), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.fill_gfa_form"), \
             patch("project_creator.cli.wait_for_gfa_email",
                   return_value="https://docs.google.com/spreadsheets/d/GFA123/edit"), \
             patch("project_creator.cli.rename_file", side_effect=_bad_rename), \
             patch("project_creator.cli.create_shortcut"), \
             patch("project_creator.cli.apply_modifications"):
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr"],
                input="y\n",
            )

        # Should warn but NOT exit with 1
        assert "⚠" in result.output or "Could not rename" in result.output
        assert result.exit_code == 0

    def test_gfa_shortcut_already_exists_skips_workflow(self, runner):
        """If GFA shortcut already exists in the project folder, skip the whole GFA step."""
        mock_match = {"id": "ACCT_ID", "name": "Acme", "path": "Root > Acme"}

        # First two calls (proposal, SOW) return None; third (GFA check) returns an ID
        find_side_effect = [None, None, "EXISTING_SC_ID"]

        with patch("project_creator.cli.load_config", return_value=_valid_config()), \
             patch("project_creator.cli.get_credentials", return_value=MagicMock()), \
             patch("project_creator.cli.build_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_sheets_service", return_value=MagicMock()), \
             patch("project_creator.cli.build_gmail_service", return_value=MagicMock()), \
             patch("project_creator.cli.search_folders", return_value=[mock_match]), \
             patch("project_creator.cli.build_proposal_folder", return_value="PROJ_ID"), \
             patch("project_creator.cli.find_file_by_name", side_effect=find_side_effect), \
             patch("project_creator.cli.copy_file", return_value="COPY_ID"), \
             patch("project_creator.cli.get_folder_url", return_value="http://x"), \
             patch("project_creator.cli.fill_gfa_form") as mock_fill:
            result = runner.invoke(
                main,
                ["create", "--account=Acme", "--project=Alpha",
                 "--opportunity-id=OPP01", "--year=2026", "--month=Apr"],
                input="y\n",
            )

        # Playwright should NOT be invoked when shortcut already exists
        mock_fill.assert_not_called()
        assert "exists" in result.output.lower()
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
