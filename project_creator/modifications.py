"""Customizable and safe modifications for Google Drive files."""

# Assisted-by: Cursor

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .drive import build_service, build_sheets_service, _GET_KWARGS

DEFAULT_SHEET_INPUT_OPTION = "RAW"


def format_value(val: Any, variables: dict[str, Any]) -> Any:
    """Recursively search and format strings inside any data structure with variables dict."""
    if isinstance(val, str):
        # If the string is exactly a single variable placeholder, return its original type
        match = re.match(r"^\{([a-zA-Z0-9_]+)\}$", val)
        if match:
            key = match.group(1)
            if key in variables:
                return variables[key]

        # Otherwise, perform standard substring interpolation
        def repl(match):
            key = match.group(1)
            return str(variables.get(key, match.group(0)))

        return re.sub(r"\{([a-zA-Z0-9_]+)\}", repl, val)
    elif isinstance(val, list):
        return [format_value(item, variables) for item in val]
    elif isinstance(val, dict):
        return {k: format_value(v, variables) for k, v in val.items()}
    return val


def get_modifications_dir(config: dict[str, Any]) -> Path:
    """Resolve modifications directory path from config, or default to ~/.config/project_creator/modifications."""
    path_str = config.get("modifications_dir")
    if path_str:
        return Path(path_str).expanduser().resolve()
    from .auth import CONFIG_DIR
    return CONFIG_DIR / "modifications"


def ensure_default_modifications(modifications_dir: Path) -> None:
    """Create default modifications YAML files if they do not exist."""
    modifications_dir.mkdir(parents=True, exist_ok=True)

    sow_yaml = modifications_dir / "purchase_summary_sow.yaml"
    if not sow_yaml.exists():
        sow_yaml.write_text(
            "# Modifications for the Purchase Summary & SOW Google Sheet\n"
            "modifications:\n"
            "  - range: \"'2. SoW'!C1\"\n"
            "    value: \"{gfa_url}\"\n"
        )

    gfa_yaml = modifications_dir / "gfa.yaml"
    if not gfa_yaml.exists():
        gfa_yaml.write_text(
            "# Modifications for the GFA Google Sheet\n"
            "modifications:\n"
            "  - range: \"'New P&L Summary'!C12\"\n"
            "    value: \"{project}\"\n"
            "  - range: \"'New P&L Summary'!E6\"\n"
            "    value: \"New SOW\"\n"
            "  - range: \"'New P&L Summary'!A16\"\n"
            "    value: true\n"
            "  - range: \"'New P&L Summary'!C9\"\n"
            "    value: \"Iberia\"\n"
        )


def apply_modifications(
    creds: Any,
    file_id: str,
    file_key: str,
    variables: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Apply safe configuration modifications to a Google Drive file (Sheets, Slides, Docs)."""
    modifications_dir = get_modifications_dir(config)
    ensure_default_modifications(modifications_dir)

    mod_file = modifications_dir / f"{file_key}.yaml"
    if not mod_file.exists():
        return

    try:
        with open(mod_file, "r") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        from rich.console import Console
        Console().print(
            f"[yellow]⚠ Warning: Failed to parse modification file {mod_file}: {exc}[/yellow]"
        )
        return

    if not data or "modifications" not in data:
        return

    mods = data["modifications"]
    if not isinstance(mods, list):
        from rich.console import Console
        Console().print(
            f"[yellow]⚠ Warning: 'modifications' key in {mod_file} must be a list[/yellow]"
        )
        return

    drive_service = build_service(creds)

    try:
        meta = drive_service.files().get(
            fileId=file_id, fields="mimeType", **_GET_KWARGS
        ).execute()
        mime_type = meta.get("mimeType", "")
    except Exception as exc:
        from rich.console import Console
        Console().print(
            f"[yellow]⚠ Warning: Failed to fetch metadata for file {file_id}: {exc}[/yellow]"
        )
        return

    sheets_service = None
    slides_service = None
    docs_service = None
    sheet_updates = []

    for mod in mods:
        if not isinstance(mod, dict):
            continue

        formatted_mod = format_value(mod, variables)

        if mime_type == "application/vnd.google-apps.spreadsheet":
            range_val = formatted_mod.get("range")
            value_val = formatted_mod.get("value")
            if range_val is not None and value_val is not None:
                if isinstance(value_val, list):
                    if len(value_val) > 0 and isinstance(value_val[0], list):
                        values_grid = value_val
                    else:
                        values_grid = [value_val]
                else:
                    values_grid = [[value_val]]

                input_option = formatted_mod.get("input_option", DEFAULT_SHEET_INPUT_OPTION)
                sheet_updates.append({
                    "range": range_val,
                    "values": values_grid,
                    "input_option": input_option,
                })

        elif mime_type == "application/vnd.google-apps.presentation":
            find_str = formatted_mod.get("find")
            replace_str = formatted_mod.get("replace") or formatted_mod.get("replace_with")

            if find_str is not None and replace_str is not None:
                if slides_service is None:
                    from googleapiclient.discovery import build
                    slides_service = build("slides", "v1", credentials=creds)

                body = {
                    "requests": [
                        {
                            "replaceAllText": {
                                "containsText": {
                                    "text": str(find_str),
                                    "matchCase": True,
                                },
                                "replaceText": str(replace_str),
                            }
                        }
                    ]
                }
                try:
                    slides_service.presentations().batchUpdate(
                        presentationId=file_id, body=body
                    ).execute()
                except Exception as exc:
                    from rich.console import Console
                    Console().print(
                        f"[yellow]⚠ Warning: Failed to replace text in presentation {file_id}: {exc}[/yellow]"
                    )

        elif mime_type == "application/vnd.google-apps.document":
            find_str = formatted_mod.get("find")
            replace_str = formatted_mod.get("replace") or formatted_mod.get("replace_with")

            if find_str is not None and replace_str is not None:
                if docs_service is None:
                    from googleapiclient.discovery import build
                    docs_service = build("docs", "v1", credentials=creds)

                body = {
                    "requests": [
                        {
                            "replaceAllText": {
                                "containsText": {
                                    "text": str(find_str),
                                    "matchCase": True,
                                },
                                "replaceText": str(replace_str),
                            }
                        }
                    ]
                }
                try:
                    docs_service.documents().batchUpdate(
                        documentId=file_id, body=body
                    ).execute()
                except Exception as exc:
                    from rich.console import Console
                    Console().print(
                        f"[yellow]⚠ Warning: Failed to replace text in document {file_id}: {exc}[/yellow]"
                    )

    if sheet_updates:
        if sheets_service is None:
            sheets_service = build_sheets_service(creds)

        updates_by_option: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for update in sheet_updates:
            option = update.pop("input_option", DEFAULT_SHEET_INPUT_OPTION)
            updates_by_option[option].append(update)

        for input_option, data in updates_by_option.items():
            try:
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=file_id,
                    body={
                        "valueInputOption": input_option,
                        "data": data,
                    },
                ).execute()
            except Exception as exc:
                from rich.console import Console
                Console().print(
                    f"[yellow]⚠ Warning: Failed to batch update spreadsheet {file_id} "
                    f"with {input_option}: {exc}[/yellow]"
                )
