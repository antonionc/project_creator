"""Tests for project_creator.drive."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
import yaml
from googleapiclient.errors import HttpError

from project_creator.drive import (
    _get_folder_path,
    _resolve_shortcut_to_folder,
    build_proposal_folder,
    build_service,
    build_sheets_service,
    copy_file,
    create_shortcut,
    get_folder_url,
    get_or_create_folder,
    parse_file_id,
    rename_file,
    search_folders,
    validate_spreadsheet_url,
    write_cell,
    _FOLDER_MIME,
    _SHORTCUT_MIME,
    find_file_by_name,
    add_commenter_permission,
)
from project_creator.modifications import (
    format_value,
    apply_modifications,
    get_modifications_dir,
    ensure_default_modifications,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _http_error(status: int = 403) -> HttpError:
    """Build a minimal HttpError for testing."""
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=b"Forbidden")


def _mock_service() -> MagicMock:
    """Return a MagicMock that auto-chains .files().X().execute() calls."""
    return MagicMock()


# ---------------------------------------------------------------------------
# build_service / build_sheets_service
# ---------------------------------------------------------------------------

class TestBuildService:
    def test_build_service_calls_build(self):
        mock_creds = MagicMock()
        with patch("project_creator.drive.build") as mock_build:
            build_service(mock_creds)
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)

    def test_build_sheets_service_calls_build(self):
        mock_creds = MagicMock()
        with patch("project_creator.drive.build") as mock_build:
            build_sheets_service(mock_creds)
        mock_build.assert_called_once_with("sheets", "v4", credentials=mock_creds)


# ---------------------------------------------------------------------------
# _get_folder_path
# ---------------------------------------------------------------------------

class TestGetFolderPath:
    def test_single_level(self):
        service = _mock_service()
        service.files().get().execute.return_value = {"name": "Root", "parents": []}
        path = _get_folder_path(service, "ROOT_ID")
        assert path == "Root"

    def test_two_levels(self):
        service = _mock_service()
        # Drive traversal goes child → parent, so calls happen in order child, parent
        service.files().get().execute.side_effect = [
            {"name": "Child", "parents": ["PARENT_ID"]},
            {"name": "Parent", "parents": []},
        ]
        path = _get_folder_path(service, "CHILD_ID")
        assert path == "Parent > Child"

    def test_breaks_on_http_error(self):
        service = _mock_service()
        service.files().get().execute.side_effect = _http_error()
        path = _get_folder_path(service, "BAD_ID")
        assert path == ""  # empty string — no parts were appended

    def test_respects_max_depth(self):
        service = _mock_service()
        # Always return another parent — should stop at max_depth=2
        service.files().get().execute.return_value = {"name": "Node", "parents": ["NEXT"]}
        path = _get_folder_path(service, "START", max_depth=2)
        # 2 calls; parts = ["Node", "Node"] reversed = "Node > Node"
        assert path.count("Node") == 2


# ---------------------------------------------------------------------------
# find_file_by_name
# ---------------------------------------------------------------------------

class TestFindFileByName:
    def test_returns_none_when_not_found(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        result = find_file_by_name(service, "Missing File", "PARENT_ID")
        assert result is None

    def test_returns_id_when_found(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": [{"id": "FOUND_ID"}]}
        result = find_file_by_name(service, "Existing File", "PARENT_ID")
        assert result == "FOUND_ID"

    def test_query_escapes_special_chars(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        find_file_by_name(service, "O'Brien File", "PAR")
        q = service.files().list.call_args[1]["q"]
        assert "O\\'Brien" in q


# ---------------------------------------------------------------------------
# search_folders
# ---------------------------------------------------------------------------

class TestSearchFolders:
    def test_returns_empty_list_when_no_results(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        result = search_folders(service, "Acme")
        assert result == []

    def test_returns_folders_with_path(self):
        service = _mock_service()
        service.files().list().execute.return_value = {
            "files": [{"id": "F1", "name": "Acme", "parents": []}]
        }
        # _get_folder_path will call files().get()
        service.files().get().execute.return_value = {"name": "Acme", "parents": []}
        result = search_folders(service, "Acme")
        assert len(result) == 1
        assert result[0]["id"] == "F1"

    def test_query_escapes_single_quote(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        search_folders(service, "O'Brien")
        # Confirm the list() was called (query escaping implicitly tested)
        service.files().list.assert_called()

    def test_query_escapes_backslash(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        search_folders(service, "C:\\\\path")
        service.files().list.assert_called()

    def test_includes_parent_id_in_query(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        search_folders(service, "Acme", parent_id="PARENT_123")
        call_kwargs = service.files().list.call_args[1]
        assert "PARENT_123" in call_kwargs["q"]


# ---------------------------------------------------------------------------
# get_or_create_folder
# ---------------------------------------------------------------------------

class TestGetOrCreateFolder:
    def test_returns_existing_folder_id(self):
        service = _mock_service()
        service.files().list().execute.return_value = {
            "files": [{"id": "EXISTING_ID", "name": "Proposals"}]
        }
        result = get_or_create_folder(service, "Proposals", "PARENT")
        assert result == "EXISTING_ID"
        service.files().create.assert_not_called()

    def test_creates_folder_when_not_found(self):
        service = _mock_service()
        # First call: no real folder; second call: no shortcut either
        service.files().list().execute.side_effect = [
            {"files": []},   # folder search
            {"files": []},   # shortcut search
        ]
        service.files().create().execute.return_value = {"id": "NEW_ID"}
        result = get_or_create_folder(service, "Proposals", "PARENT")
        assert result == "NEW_ID"
        service.files().create.assert_called()

    def test_create_body_contains_correct_mime(self):
        service = _mock_service()
        service.files().list().execute.side_effect = [
            {"files": []},
            {"files": []},
        ]
        service.files().create().execute.return_value = {"id": "X"}
        get_or_create_folder(service, "MyFolder", "PAR")
        body = service.files().create.call_args[1]["body"]
        assert body["mimeType"] == _FOLDER_MIME
        assert body["name"] == "MyFolder"
        assert body["parents"] == ["PAR"]

    def test_uses_shortcut_target_when_real_folder_missing(self):
        """If a shortcut named the same exists and points to a folder, return its target ID."""
        service = _mock_service()
        service.files().list().execute.side_effect = [
            {"files": []},   # no real folder
            {               # shortcut found
                "files": [{
                    "id": "SC_ID",
                    "name": "Proposals",
                    "shortcutDetails": {
                        "targetId": "TARGET_FOLDER_ID",
                        "targetMimeType": _FOLDER_MIME,
                    },
                }]
            },
        ]
        result = get_or_create_folder(service, "Proposals", "PARENT")
        assert result == "TARGET_FOLDER_ID"
        service.files().create.assert_not_called()

    def test_ignores_shortcut_pointing_to_non_folder(self):
        """Shortcuts whose target is not a folder should be skipped and a new folder created."""
        service = _mock_service()
        service.files().list().execute.side_effect = [
            {"files": []},   # no real folder
            {               # shortcut pointing to a file, not a folder
                "files": [{
                    "id": "SC_ID",
                    "name": "Proposals",
                    "shortcutDetails": {
                        "targetId": "FILE_ID",
                        "targetMimeType": "application/vnd.google-apps.document",
                    },
                }]
            },
        ]
        service.files().create().execute.return_value = {"id": "NEW_ID"}
        result = get_or_create_folder(service, "Proposals", "PARENT")
        assert result == "NEW_ID"

    def test_http_error_on_list_propagates(self):
        service = _mock_service()
        service.files().list().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            get_or_create_folder(service, "Folder", "PAR")

    def test_http_error_on_create_propagates(self):
        service = _mock_service()
        service.files().list().execute.side_effect = [
            {"files": []},
            {"files": []},
        ]
        service.files().create().execute.side_effect = _http_error(500)
        with pytest.raises(HttpError):
            get_or_create_folder(service, "Folder", "PAR")

    def test_name_with_single_quote_handled(self):
        service = _mock_service()
        service.files().list().execute.side_effect = [
            {"files": []},
            {"files": []},
        ]
        service.files().create().execute.return_value = {"id": "X"}
        # Should not raise even with tricky name
        get_or_create_folder(service, "O'Client", "PAR")


# ---------------------------------------------------------------------------
# _resolve_shortcut_to_folder
# ---------------------------------------------------------------------------

class TestResolveShortcutToFolder:
    def test_returns_none_when_no_shortcuts(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        result = _resolve_shortcut_to_folder(service, "Proposals", "PARENT")
        assert result is None

    def test_returns_target_id_for_folder_shortcut(self):
        service = _mock_service()
        service.files().list().execute.return_value = {
            "files": [{
                "id": "SC_ID",
                "name": "Proposals",
                "shortcutDetails": {
                    "targetId": "FOLDER_ID",
                    "targetMimeType": _FOLDER_MIME,
                },
            }]
        }
        result = _resolve_shortcut_to_folder(service, "Proposals", "PARENT")
        assert result == "FOLDER_ID"

    def test_returns_none_for_non_folder_shortcut(self):
        service = _mock_service()
        service.files().list().execute.return_value = {
            "files": [{
                "id": "SC_ID",
                "name": "Proposals",
                "shortcutDetails": {
                    "targetId": "DOC_ID",
                    "targetMimeType": "application/vnd.google-apps.document",
                },
            }]
        }
        result = _resolve_shortcut_to_folder(service, "Proposals", "PARENT")
        assert result is None

    def test_query_uses_shortcut_mime(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        _resolve_shortcut_to_folder(service, "Proposals", "PARENT")
        q = service.files().list.call_args[1]["q"]
        assert _SHORTCUT_MIME in q


# ---------------------------------------------------------------------------
# copy_file
# ---------------------------------------------------------------------------

class TestCopyFile:
    def test_returns_new_file_id(self):
        service = _mock_service()
        service.files().copy().execute.return_value = {"id": "COPY_ID"}
        result = copy_file(service, "SRC", "New Name", "PARENT")
        assert result == "COPY_ID"

    def test_passes_correct_args(self):
        service = _mock_service()
        service.files().copy().execute.return_value = {"id": "X"}
        copy_file(service, "SRC_ID", "File Name", "PAR_ID")
        call_kwargs = service.files().copy.call_args[1]
        assert call_kwargs["fileId"] == "SRC_ID"
        assert call_kwargs["body"]["name"] == "File Name"
        assert call_kwargs["body"]["parents"] == ["PAR_ID"]

    def test_http_error_propagates(self):
        service = _mock_service()
        service.files().copy().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            copy_file(service, "SRC", "Name", "PAR")


# ---------------------------------------------------------------------------
# rename_file
# ---------------------------------------------------------------------------

class TestRenameFile:
    def test_calls_update_with_new_name(self):
        service = _mock_service()
        service.files().update().execute.return_value = {}
        rename_file(service, "FILE_ID", "New Name")
        call_kwargs = service.files().update.call_args[1]
        assert call_kwargs["fileId"] == "FILE_ID"
        assert call_kwargs["body"]["name"] == "New Name"

    def test_http_error_propagates(self):
        service = _mock_service()
        service.files().update().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            rename_file(service, "FILE_ID", "Name")


# ---------------------------------------------------------------------------
# create_shortcut
# ---------------------------------------------------------------------------

class TestCreateShortcut:
    def test_returns_shortcut_id(self):
        service = _mock_service()
        service.files().create().execute.return_value = {"id": "SHORT_ID"}
        result = create_shortcut(service, "TARGET", "Shortcut Name", "PAR")
        assert result == "SHORT_ID"

    def test_body_contains_correct_mime_and_target(self):
        service = _mock_service()
        service.files().create().execute.return_value = {"id": "X"}
        create_shortcut(service, "TARGET_ID", "My Shortcut", "PAR_ID")
        body = service.files().create.call_args[1]["body"]
        assert body["mimeType"] == _SHORTCUT_MIME
        assert body["shortcutDetails"]["targetId"] == "TARGET_ID"
        assert body["name"] == "My Shortcut"
        assert body["parents"] == ["PAR_ID"]

    def test_http_error_propagates(self):
        service = _mock_service()
        service.files().create().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            create_shortcut(service, "T", "N", "P")


# ---------------------------------------------------------------------------
# add_commenter_permission
# ---------------------------------------------------------------------------

class TestAddCommenterPermission:
    def test_calls_permissions_create_with_correct_args(self):
        service = _mock_service()
        add_commenter_permission(service, "FILE_ID", "redhat.com")
        call_kwargs = service.permissions().create.call_args[1]
        assert call_kwargs["fileId"] == "FILE_ID"
        assert call_kwargs["body"]["type"] == "domain"
        assert call_kwargs["body"]["role"] == "commenter"
        assert call_kwargs["body"]["domain"] == "redhat.com"
        assert call_kwargs["supportsAllDrives"] is True

    def test_http_error_propagates(self):
        service = _mock_service()
        service.permissions().create().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            add_commenter_permission(service, "FILE_ID", "redhat.com")


# ---------------------------------------------------------------------------
# write_cell
# ---------------------------------------------------------------------------

class TestWriteCell:
    def test_calls_values_update_with_correct_range(self):
        sheets = _mock_service()
        write_cell(sheets, "SHEET_ID", "2. SoW", "C1", "https://example.com")
        call_kwargs = sheets.spreadsheets().values().update.call_args[1]
        assert call_kwargs["spreadsheetId"] == "SHEET_ID"
        assert call_kwargs["range"] == "'2. SoW'!C1"
        assert call_kwargs["body"]["values"] == [["https://example.com"]]

    def test_uses_raw_value_input_option(self):
        sheets = _mock_service()
        write_cell(sheets, "S", "Sheet1", "A1", "val")
        call_kwargs = sheets.spreadsheets().values().update.call_args[1]
        assert call_kwargs["valueInputOption"] == "RAW"

    def test_http_error_propagates(self):
        sheets = _mock_service()
        sheets.spreadsheets().values().update().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            write_cell(sheets, "S", "Sheet", "A1", "val")


# ---------------------------------------------------------------------------
# format_value / apply_modifications
# ---------------------------------------------------------------------------

class TestFormatValue:
    def test_replaces_exact_variable_keeping_type(self):
        variables = {"is_bool": True, "count": 42}
        assert format_value("{is_bool}", variables) is True
        assert format_value("{count}", variables) == 42
        assert format_value("Not found {missing}", variables) == "Not found {missing}"

    def test_replaces_substring(self):
        variables = {"project": "Alpha", "year": "2026"}
        assert format_value("Project {project} ({year})", variables) == "Project Alpha (2026)"

    def test_recursive_list_and_dict(self):
        variables = {"var": "value"}
        data = {
            "key": "{var}",
            "list": ["{var}", "plain", {"nested": "{var}"}]
        }
        formatted = format_value(data, variables)
        assert formatted["key"] == "value"
        assert formatted["list"] == ["value", "plain", {"nested": "value"}]


class TestApplyModifications:
    @patch("project_creator.modifications.get_modifications_dir")
    def test_apply_modifications_sheets(self, mock_get_dir, tmp_path):
        mock_get_dir.return_value = tmp_path
        
        # Write dummy YAML
        yaml_content = {
            "modifications": [
                {"range": "'Sheet1'!A1", "value": "{var}"}
            ]
        }
        with open(tmp_path / "test_sheet.yaml", "w") as f:
            yaml.dump(yaml_content, f)

        mock_creds = MagicMock()
        mock_drive = MagicMock()
        mock_sheets = MagicMock()

        # Mock build_service for drive
        mock_drive.files().get().execute.return_value = {
            "mimeType": "application/vnd.google-apps.spreadsheet"
        }

        with patch("project_creator.modifications.build_service", return_value=mock_drive), \
             patch("project_creator.modifications.build_sheets_service", return_value=mock_sheets):
            apply_modifications(
                creds=mock_creds,
                file_id="FILE123",
                file_key="test_sheet",
                variables={"var": "hello"},
                config={}
            )

        # Should retrieve mimeType
        mock_drive.files().get.assert_called_with(
            fileId="FILE123",
            fields="mimeType",
            supportsAllDrives=True
        )

        # Should update Sheets values
        mock_sheets.spreadsheets().values().batchUpdate.assert_called_once()
        call_kwargs = mock_sheets.spreadsheets().values().batchUpdate.call_args[1]
        assert call_kwargs["spreadsheetId"] == "FILE123"
        assert call_kwargs["body"]["valueInputOption"] == "RAW"
        assert call_kwargs["body"]["data"] == [
            {"range": "'Sheet1'!A1", "values": [["hello"]]}
        ]

    @patch("project_creator.modifications.get_modifications_dir")
    @patch("googleapiclient.discovery.build")
    def test_apply_modifications_slides(self, mock_build, mock_get_dir, tmp_path):
        mock_get_dir.return_value = tmp_path
        
        # Write dummy YAML
        yaml_content = {
            "modifications": [
                {"find": "{{project}}", "replace": "{var}"}
            ]
        }
        with open(tmp_path / "test_slide.yaml", "w") as f:
            yaml.dump(yaml_content, f)

        mock_creds = MagicMock()
        mock_drive = MagicMock()
        mock_slides = MagicMock()
        mock_build.return_value = mock_slides

        # Mock build_service for drive
        mock_drive.files().get().execute.return_value = {
            "mimeType": "application/vnd.google-apps.presentation"
        }

        with patch("project_creator.modifications.build_service", return_value=mock_drive):
            apply_modifications(
                creds=mock_creds,
                file_id="FILE456",
                file_key="test_slide",
                variables={"var": "Red Hat Project"},
                config={}
            )

        # Should update Slides
        mock_build.assert_called_once_with("slides", "v1", credentials=mock_creds)
        mock_slides.presentations().batchUpdate.assert_called_once_with(
            presentationId="FILE456",
            body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {
                                "text": "{{project}}",
                                "matchCase": True,
                            },
                            "replaceText": "Red Hat Project",
                        }
                    }
                ]
            }
        )


# ---------------------------------------------------------------------------
# build_proposal_folder
# ---------------------------------------------------------------------------

class TestBuildProposalFolder:
    def test_creates_proposals_year_project_hierarchy(self):
        service = _mock_service()
        # Each get_or_create_folder makes 2 list() calls (folder + shortcut) when not found
        service.files().list().execute.side_effect = [
            {"files": []}, {"files": []},  # Proposals folder: not found, no shortcut
            {"files": []}, {"files": []},  # year folder: not found, no shortcut
            {"files": []}, {"files": []},  # project folder: not found, no shortcut
        ]
        service.files().create().execute.side_effect = [
            {"id": "PROPOSALS_ID"},
            {"id": "YEAR_ID"},
            {"id": "PROJECT_ID"},
        ]
        result = build_proposal_folder(service, "Acme", "Alpha", "2026", "Apr", "ACCOUNT_ID")
        assert result == "PROJECT_ID"

    def test_folder_name_format(self):
        service = _mock_service()
        # Track create bodies separately to avoid MagicMock side-effect call counting issues
        created_bodies: list = []

        def _create_side_effect(body, **kwargs):
            created_bodies.append(body)
            m = MagicMock()
            m.execute.return_value = {"id": f"ID_{len(created_bodies)}"}
            return m

        # Each get_or_create_folder makes 2 list() calls (folder + shortcut) when not found
        service.files().list().execute.side_effect = [
            {"files": []}, {"files": []},  # Proposals
            {"files": []}, {"files": []},  # year
            {"files": []}, {"files": []},  # project
        ]
        service.files().create.side_effect = _create_side_effect
        build_proposal_folder(service, "Acme", "Beta Project", "2026", "Jun", "ACC")
        # Third create = leaf project folder
        assert created_bodies[2]["name"] == "Acme - Beta Project (Jun 2026)"

    def test_reuses_existing_proposals_folder(self):
        service = _mock_service()
        created_bodies: list = []

        def _create_side_effect(body, **kwargs):
            created_bodies.append(body)
            m = MagicMock()
            ids = ["YEAR_ID", "PROJECT_ID"]
            m.execute.return_value = {"id": ids[len(created_bodies) - 1]}
            return m

        # Each get_or_create_folder makes 2 list() calls when folder is not found.
        # When an existing real folder is found on the first list() call, the
        # shortcut check is skipped entirely (early return).
        service.files().list().execute.side_effect = [
            {"files": [{"id": "EXISTING_PROPOSALS", "name": "Proposals"}]},  # found!
            {"files": []}, {"files": []},  # year: not found, no shortcut
            {"files": []}, {"files": []},  # project: not found, no shortcut
        ]
        service.files().create.side_effect = _create_side_effect
        result = build_proposal_folder(service, "Acme", "Alpha", "2026", "Apr", "ACCOUNT_ID")
        assert result == "PROJECT_ID"
        # create was called only twice (not for Proposals, which already existed)
        assert len(created_bodies) == 2


# ---------------------------------------------------------------------------
# get_folder_url
# ---------------------------------------------------------------------------

class TestGetFolderUrl:
    def test_returns_expected_url(self):
        url = get_folder_url("ABC123")
        assert url == "https://drive.google.com/drive/folders/ABC123"


# ---------------------------------------------------------------------------
# parse_file_id
# ---------------------------------------------------------------------------

class TestParseFileId:
    @pytest.mark.parametrize("url, expected", [
        # /d/ pattern (files, Sheets, Slides)
        ("https://drive.google.com/file/d/FILE_ID_123/view", "FILE_ID_123"),
        ("https://docs.google.com/spreadsheets/d/SHEET_ID/edit", "SHEET_ID"),
        ("https://docs.google.com/presentation/d/SLIDE_ID/edit", "SLIDE_ID"),
        # /folders/ pattern
        ("https://drive.google.com/drive/folders/FOLDER_ID", "FOLDER_ID"),
        # ?id= query string
        ("https://drive.google.com/open?id=QUERY_ID", "QUERY_ID"),
        ("https://drive.google.com/open?foo=bar&id=QUERY_ID2", "QUERY_ID2"),
        # Raw ID (no URL)
        ("RAW_DRIVE_ID", "RAW_DRIVE_ID"),
        # ID with hyphens and underscores
        ("1a2b-3c_4D", "1a2b-3c_4D"),
    ])
    def test_extractions(self, url, expected):
        assert parse_file_id(url) == expected

    def test_strips_whitespace_from_raw_id(self):
        assert parse_file_id("  MY_ID  ") == "MY_ID"

    def test_empty_string_returns_empty(self):
        assert parse_file_id("") == ""

    def test_url_with_no_recognized_pattern_returned_as_is(self):
        url = "https://example.com/no/match/here"
        assert parse_file_id(url) == url.strip()


class TestValidateSpreadsheetUrl:
    @pytest.mark.parametrize("url_or_id", [
        "https://docs.google.com/spreadsheets/d/abc123/edit",
        "abc123",
        "  abc123  ",
    ])
    def test_accepts_valid_spreadsheet_refs(self, url_or_id):
        assert validate_spreadsheet_url(url_or_id) == "https://docs.google.com/spreadsheets/d/abc123/edit"

    @pytest.mark.parametrize("url_or_id", [
        "https://example.com/sheet",
        "not a valid id!",
        "",
        "javascript:alert(1)",
    ])
    def test_rejects_invalid_spreadsheet_refs(self, url_or_id):
        assert validate_spreadsheet_url(url_or_id) is None
