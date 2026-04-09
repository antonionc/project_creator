"""Google Drive API wrapper for proposal folder creation."""

from __future__ import annotations

import re
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

_FOLDER_MIME = "application/vnd.google-apps.folder"
_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

# supportsAllDrives is accepted by both files().get() and files().list()
_GET_KWARGS = {
    "supportsAllDrives": True,
}

# includeItemsFromAllDrives is only valid for files().list()
_LIST_KWARGS = {
    "supportsAllDrives": True,
    "includeItemsFromAllDrives": True,
}


# ---------------------------------------------------------------------------
# Service builder
# ---------------------------------------------------------------------------

def build_service(creds: Credentials):
    """Build and return an authenticated Drive v3 service."""
    return build("drive", "v3", credentials=creds)


def build_sheets_service(creds: Credentials):
    """Build and return an authenticated Sheets v4 service."""
    return build("sheets", "v4", credentials=creds)


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------

def _get_folder_path(service, folder_id: str, max_depth: int = 6) -> str:
    """Resolve a human-readable breadcrumb path for *folder_id* by walking parents."""
    parts: list[str] = []
    current_id = folder_id

    for _ in range(max_depth):
        try:
            meta = service.files().get(
                fileId=current_id,
                fields="id,name,parents",
                **_GET_KWARGS,
            ).execute()
        except HttpError:
            break

        parts.append(meta.get("name", "?"))
        parents = meta.get("parents", [])
        if not parents:
            break
        current_id = parents[0]

    parts.reverse()
    return " > ".join(parts)


def search_folders(
    service,
    name: str,
    parent_id: Optional[str] = None,
) -> list[dict]:
    """Search Drive for folders whose name exactly matches *name*.

    Args:
        service:   Authenticated Drive v3 service.
        name:      Folder name to search for (exact match, case-insensitive per Drive).
        parent_id: Optional folder/drive ID to restrict the search scope.

    Returns:
        List of dicts with keys ``id``, ``name``, ``path``.
    """
    escaped = name.replace("'", "\\'")
    q = f"mimeType='{_FOLDER_MIME}' and name='{escaped}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    results = service.files().list(
        q=q,
        fields="files(id,name,parents)",
        corpora="allDrives",
        **_LIST_KWARGS,
    ).execute()

    folders = []
    for f in results.get("files", []):
        path = _get_folder_path(service, f["id"])
        folders.append({"id": f["id"], "name": f["name"], "path": path})

    return folders


def get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return the ID of an existing child folder named *name*, or create it.

    Args:
        service:   Authenticated Drive v3 service.
        name:      Name of the subfolder.
        parent_id: ID of the parent folder.

    Returns:
        Google Drive folder ID (str).
    """
    escaped = name.replace("'", "\\'")
    q = (
        f"mimeType='{_FOLDER_MIME}' and name='{escaped}' "
        f"and '{parent_id}' in parents and trashed=false"
    )

    results = service.files().list(
        q=q,
        fields="files(id,name)",
        **_LIST_KWARGS,
    ).execute()

    existing = results.get("files", [])
    if existing:
        return existing[0]["id"]

    folder = service.files().create(
        body={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]},
        fields="id",
        **_GET_KWARGS,
    ).execute()

    return folder["id"]


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def copy_file(service, file_id: str, name: str, parent_id: str) -> str:
    """Copy *file_id* into *parent_id* with the given *name*.

    Returns:
        ID of the newly created file copy.
    """
    result = service.files().copy(
        fileId=file_id,
        body={"name": name, "parents": [parent_id]},
        fields="id",
        **_GET_KWARGS,
    ).execute()
    return result["id"]


def rename_file(service, file_id: str, new_name: str) -> None:
    """Rename *file_id* in-place. Requires edit permission on the file."""
    service.files().update(
        fileId=file_id,
        body={"name": new_name},
        **_GET_KWARGS,
    ).execute()


def create_shortcut(service, file_id: str, name: str, parent_id: str) -> str:
    """Create a Drive Shortcut in *parent_id* pointing to *file_id*.

    The shortcut is named *name* regardless of the target file's name and
    requires no write access to the target file.

    Returns:
        ID of the newly created shortcut.
    """
    result = service.files().create(
        body={
            "name": name,
            "mimeType": _SHORTCUT_MIME,
            "parents": [parent_id],
            "shortcutDetails": {"targetId": file_id},
        },
        fields="id",
        **_GET_KWARGS,
    ).execute()
    return result["id"]


def write_cell(sheets_service, spreadsheet_id: str, sheet_name: str, cell: str, value: str) -> None:
    """Write *value* to the given *cell* in *sheet_name* of *spreadsheet_id*.

    Args:
        sheets_service:  Authenticated Sheets v4 service.
        spreadsheet_id:  The ID of the target Google Sheet.
        sheet_name:      Exact name of the sheet tab (e.g. ``'2. SoW'``).
        cell:            Cell address, e.g. ``C1``.
        value:           Value to write as plain text.
    """
    range_notation = f"'{sheet_name}'!{cell}"
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_notation,
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------

def build_proposal_folder(
    service,
    account: str,
    project: str,
    year: str,
    month: str,
    account_folder_id: str,
) -> str:
    """Create the full Proposals/<year>/<project (Mon YYYY)> hierarchy.

    Creates any missing intermediate folders (Proposals, year) without
    touching existing ones.

    Args:
        service:           Authenticated Drive v3 service.
        account:           Customer account name (unused in path but kept for clarity).
        project:           Project name.
        year:              Four-digit year string, e.g. "2026".
        month:             Month abbreviation, e.g. "Apr".
        account_folder_id: ID of the top-level account folder in Drive.

    Returns:
        ID of the leaf proposal folder.
    """
    proposals_id = get_or_create_folder(service, "Proposals", account_folder_id)
    year_id = get_or_create_folder(service, year, proposals_id)
    folder_name = f"{project} ({month} {year})"
    project_id = get_or_create_folder(service, folder_name, year_id)
    return project_id


# ---------------------------------------------------------------------------
# URL / ID utilities
# ---------------------------------------------------------------------------

def get_folder_url(folder_id: str) -> str:
    """Return the web URL for a Drive folder given its ID."""
    return f"https://drive.google.com/drive/folders/{folder_id}"


def parse_file_id(url_or_id: str) -> str:
    """Extract a Drive file or folder ID from a URL, or return the input as-is.

    Handles the common URL patterns:
    - https://drive.google.com/file/d/{ID}/...
    - https://drive.google.com/drive/folders/{ID}
    - https://docs.google.com/spreadsheets/d/{ID}/...
    - https://docs.google.com/presentation/d/{ID}/...
    - ?id={ID} query-string format
    """
    patterns = [
        r"/d/([a-zA-Z0-9_-]+)",
        r"/folders/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    # Assume the raw input is already an ID
    return url_or_id.strip()
