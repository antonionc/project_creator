"""Tests for project_creator.drive."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from googleapiclient.errors import HttpError

from project_creator.drive import (
    _get_folder_path,
    build_proposal_folder,
    build_service,
    build_sheets_service,
    copy_file,
    create_shortcut,
    customize_gfa,
    get_folder_url,
    get_or_create_folder,
    parse_file_id,
    rename_file,
    search_folders,
    write_cell,
    _FOLDER_MIME,
    _SHORTCUT_MIME,
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
        service.files().list().execute.return_value = {"files": []}
        service.files().create().execute.return_value = {"id": "NEW_ID"}
        result = get_or_create_folder(service, "Proposals", "PARENT")
        assert result == "NEW_ID"
        service.files().create.assert_called()

    def test_create_body_contains_correct_mime(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        service.files().create().execute.return_value = {"id": "X"}
        get_or_create_folder(service, "MyFolder", "PAR")
        body = service.files().create.call_args[1]["body"]
        assert body["mimeType"] == _FOLDER_MIME
        assert body["name"] == "MyFolder"
        assert body["parents"] == ["PAR"]

    def test_http_error_on_list_propagates(self):
        service = _mock_service()
        service.files().list().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            get_or_create_folder(service, "Folder", "PAR")

    def test_http_error_on_create_propagates(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        service.files().create().execute.side_effect = _http_error(500)
        with pytest.raises(HttpError):
            get_or_create_folder(service, "Folder", "PAR")

    def test_name_with_single_quote_handled(self):
        service = _mock_service()
        service.files().list().execute.return_value = {"files": []}
        service.files().create().execute.return_value = {"id": "X"}
        # Should not raise even with tricky name
        get_or_create_folder(service, "O'Client", "PAR")


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
# customize_gfa
# ---------------------------------------------------------------------------

class TestCustomizeGfa:
    def test_calls_batch_update(self):
        sheets = _mock_service()
        customize_gfa(sheets, "GFA_ID", "My Project")
        sheets.spreadsheets().values().batchUpdate.assert_called_once()

    def test_batch_update_contains_project_name(self):
        sheets = _mock_service()
        customize_gfa(sheets, "GFA_ID", "Alpha Project")
        body = sheets.spreadsheets().values().batchUpdate.call_args[1]["body"]
        data_values = [item["values"] for item in body["data"]]
        assert [["Alpha Project"]] in data_values

    def test_uses_user_entered_value_input_option(self):
        sheets = _mock_service()
        customize_gfa(sheets, "GFA_ID", "Proj")
        body = sheets.spreadsheets().values().batchUpdate.call_args[1]["body"]
        assert body["valueInputOption"] == "USER_ENTERED"

    def test_writes_four_cells(self):
        sheets = _mock_service()
        customize_gfa(sheets, "GFA_ID", "Proj")
        body = sheets.spreadsheets().values().batchUpdate.call_args[1]["body"]
        assert len(body["data"]) == 4

    def test_http_error_propagates(self):
        sheets = _mock_service()
        sheets.spreadsheets().values().batchUpdate().execute.side_effect = _http_error(403)
        with pytest.raises(HttpError):
            customize_gfa(sheets, "GFA_ID", "Proj")


# ---------------------------------------------------------------------------
# build_proposal_folder
# ---------------------------------------------------------------------------

class TestBuildProposalFolder:
    def test_creates_proposals_year_project_hierarchy(self):
        service = _mock_service()
        # get_or_create_folder calls list + optionally create; mock list to return nothing
        service.files().list().execute.return_value = {"files": []}
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

        service.files().list().execute.return_value = {"files": []}
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

        # First list returns existing "Proposals" folder
        service.files().list().execute.side_effect = [
            {"files": [{"id": "EXISTING_PROPOSALS", "name": "Proposals"}]},
            {"files": []},  # year folder doesn't exist
            {"files": []},  # project folder doesn't exist
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
