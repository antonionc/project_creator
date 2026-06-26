"""Click-based CLI for the Red Hat Proposal Creator."""

# Assisted-by: Cursor

from __future__ import annotations  # enables X | Y union syntax on Python 3.9

import webbrowser
from datetime import datetime, date, timedelta

from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .auth import ensure_config_permissions, get_credentials, CONFIG_DIR
from .config import (
    CONFIG_PATH,
    load_config,
    save_config,
    validate_config,
)
from .drive import (
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
    write_cell,
    find_file_by_name,
    add_commenter_permission,
)
from .modifications import apply_modifications
from .gmail import build_gmail_service, wait_for_gfa_email
from .gfa_form import fill_gfa_form
import time

console = Console()

_MONTH_ABBREVS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="project-creator")
def main() -> None:
    """Red Hat Proposal Creator — automates Google Drive proposal setup."""


# ---------------------------------------------------------------------------
# setup command
# ---------------------------------------------------------------------------

@main.command()
def setup() -> None:
    """Interactive first-time configuration wizard.

    Guides you through authorizing Google Drive access and configuring
    template file IDs. Run this once before using 'create'.
    """
    console.print(
        Panel.fit(
            "[bold red]Red Hat Proposal Creator[/bold red]\n[dim]First-time setup[/dim]",
            border_style="red",
        )
    )

    ensure_config_permissions()
    config = load_config()

    # ── 1. Check credentials.json ──────────────────────────────────────────
    creds_path = CONFIG_DIR / "credentials.json"
    if not creds_path.exists():
        console.print(
            "\n[yellow]⚠[/yellow]  [bold]credentials.json not found.[/bold]\n\n"
            "Download your OAuth 2.0 credentials from Google Cloud Console and\n"
            f"save the file here:\n\n  [bold]{creds_path}[/bold]\n\n"
            "See [bold]README.md[/bold] for step-by-step instructions, then re-run setup."
        )
        raise SystemExit(1)

    console.print("\n[green]✔[/green]  credentials.json found.")
    ensure_config_permissions()

    # ── 2. Authorize with Google ───────────────────────────────────────────
    console.print("\n[bold]Authorizing with Google...[/bold]")
    try:
        creds = get_credentials()
        service = build_service(creds)
        about = service.about().get(fields="user").execute()
        email = about.get("user", {}).get("emailAddress", "unknown")
        console.print(f"[green]✔[/green]  Authorized as: [bold]{email}[/bold]")
    except Exception as exc:
        console.print(f"[red]✗[/red]  Authorization failed: {exc}")
        raise SystemExit(1)

    # ── 3. Template file IDs ───────────────────────────────────────────────
    console.print(
        "\n[bold]Template configuration[/bold]\n"
        "[dim]Open each template file in Google Drive; the file ID is in the URL:\n"
        "  drive.google.com/file/d/[bold]FILE_ID[/bold]/edit\n"
        "You can paste the full URL — the ID will be extracted automatically.[/dim]\n"
    )

    proposal_raw = Prompt.ask(
        "  Proposal template (ID or URL)",
        default=config["templates"].get("proposal", ""),
    )
    if proposal_raw:
        config["templates"]["proposal"] = parse_file_id(proposal_raw)

    sow_raw = Prompt.ask(
        "  Purchase Summary & SOW template (ID or URL)",
        default=config["templates"].get("purchase_summary_sow", ""),
    )
    if sow_raw:
        config["templates"]["purchase_summary_sow"] = parse_file_id(sow_raw)

    cu_raw = Prompt.ask(
        "  CU Calculator template (ID or URL, optional)",
        default=config["templates"].get("cu_calculator", ""),
    )
    if cu_raw:
        config["templates"]["cu_calculator"] = parse_file_id(cu_raw)

    gfa_url = Prompt.ask(
        "  GFA form URL",
        default=config["templates"].get("gfa_form_url", "https://red.ht/gfa"),
    )
    config["templates"]["gfa_form_url"] = gfa_url

    # ── 4. Optional search scope ───────────────────────────────────────────
    console.print(
        "\n[bold]Search scope[/bold] [dim](optional)[/dim]\n"
        "[dim]Restrict account folder searches to a specific Shared Drive or parent folder.\n"
        "Leave blank to search across all of your Google Drive.[/dim]\n"
    )
    root_raw = Prompt.ask(
        "  Search root (folder ID or URL, optional)",
        default=config.get("search_root_id", ""),
    )
    config["search_root_id"] = parse_file_id(root_raw) if root_raw.strip() else ""

    # ── 5. GFA defaults ────────────────────────────────────────────────────
    console.print(
        "\n[bold]GFA Defaults[/bold]\n"
    )
    gfa_config = config.get("gfa", {})
    default_geo = Prompt.ask(
        "  Default GEO for GFA form",
        default=gfa_config.get("default_geo", "EMEA"),
    )
    auto_submit_raw = Prompt.ask(
        "  Submit form automatically? (y/N)",
        default="y" if gfa_config.get("submit_automatically") else "n",
    )
    
    if "gfa" not in config:
        config["gfa"] = {}
    config["gfa"]["default_geo"] = default_geo
    config["gfa"]["submit_automatically"] = auto_submit_raw.lower().startswith("y")

    save_config(config)
    console.print(
        f"\n[green]✔[/green]  Configuration saved to [bold]{CONFIG_PATH}[/bold]\n"
        "\nYou're all set! Run [bold]project-creator create[/bold] to create your first proposal."
    )


# ---------------------------------------------------------------------------
# create command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--account", "-a", default=None, help="Customer account name.")
@click.option("--project", "-p", default=None, help="Project name.")
@click.option("--opportunity-id", "-o", default=None, help="Opportunity number for GFA form.")
@click.option("--year", "-y", default=None, help="Year (e.g. 2026). Defaults to current year.")
@click.option("--month", "-m", default=None, help="Month abbreviation (e.g. Apr). Defaults to current month.")
@click.option("--skip-gfa", is_flag=True, default=False, help="Skip the GFA form step.")
@click.option("--gfa-url", default=None, help="Use an existing GFA URL/ID instead of submitting the form.")
@click.option("--cu-calculator", is_flag=True, default=False, help="Copy the CU calculator template file.")
def create(
    account: str | None,
    project: str | None,
    opportunity_id: str | None,
    year: str | None,
    month: str | None,
    skip_gfa: bool,
    gfa_url: str | None,
    cu_calculator: bool,
) -> None:
    """Create a new proposal folder in Google Drive.

    Interactively collects the account name, project name, year, and month,
    then:

    \b
    1. Searches Drive for the customer account folder (creates if missing).
    2. Creates Proposals/<year>/<project (Mon YY)> within it.
    3. Copies the Proposal and Purchase Summary & SOW templates.
    4. Opens the GFA form, then renames the result and adds a shortcut.
    """
    console.print(
        Panel.fit(
            "[bold red]Red Hat Proposal Creator[/bold red]",
            border_style="red",
        )
    )

    # ── Load and validate config ───────────────────────────────────────────
    config = load_config()
    errors = validate_config(config)
    if errors:
        console.print("[red]✗  Configuration incomplete:[/red]")
        for err in errors:
            console.print(f"   • {err}")
        console.print("\nRun [bold]project-creator setup[/bold] to configure.")
        raise SystemExit(1)

    if cu_calculator and not config["templates"].get("cu_calculator"):
        console.print("[red]✗  Configuration incomplete:[/red]")
        console.print("   • templates.cu_calculator is not set — run 'project-creator setup' to configure")
        raise SystemExit(1)

    now = datetime.now()
    default_month = _MONTH_ABBREVS[now.month]

    # ── Gather inputs ──────────────────────────────────────────────────────
    console.print()
    if not account:
        account = Prompt.ask("  [bold]Account name[/bold]")
    if not project:
        project = Prompt.ask("  [bold]Project name[/bold]")
    if not opportunity_id:
        # Prompt only if missing, default to project
        opportunity_id = Prompt.ask("  [bold]Opportunity number[/bold]", default=project)
    if not year:
        year = Prompt.ask("  [bold]Year[/bold]", default=str(now.year))
    if not month:
        month = Prompt.ask("  [bold]Month[/bold]", default=default_month)

    month = month.strip().capitalize()

    # ── Connect to Drive ───────────────────────────────────────────────────
    console.print("\n[dim]Connecting to Google Drive...[/dim]")
    try:
        creds = get_credentials()
        service = build_service(creds)
        sheets_service = build_sheets_service(creds)
        gmail_service = build_gmail_service(creds)
    except FileNotFoundError as exc:
        console.print(f"[red]✗[/red]  {exc}")
        raise SystemExit(1)
    except Exception as exc:
        console.print(f"[red]✗[/red]  Failed to connect to Google Drive: {exc}")
        raise SystemExit(1)

    # ── Find (or create) account folder ───────────────────────────────────
    account_folder_id = _resolve_account_folder(service, account, config)
    if account_folder_id is None:
        raise SystemExit(0)

    # ── Build folder hierarchy ─────────────────────────────────────────────
    folder_label = f"{project} ({month} {year})"
    console.print(
        f"\n[cyan]→[/cyan]  Building [bold]Proposals/{year}/{folder_label}[/bold]"
    )
    try:
        project_folder_id = build_proposal_folder(
            service, account, project, year, month, account_folder_id
        )
    except Exception as exc:
        console.print(f"[red]✗[/red]  Could not create folder structure: {exc}")
        raise SystemExit(1)

    console.print(
        f"[green]✔[/green]  Folder ready: [bold]Proposals/{year}/{folder_label}[/bold]"
    )

    # ── File base name (used for all three files) ──────────────────────────
    file_base = f"{account} - {project} ({month} {year})"

    variables = {
        "account": account,
        "project": project,
        "opportunity_id": opportunity_id,
        "year": year,
        "month": month,
        "file_base": file_base,
        "gfa_url": "",
    }

    # ── Copy Proposal template ─────────────────────────────────────────────
    proposal_file_id = _copy_template(
        service,
        file_id=config["templates"]["proposal"],
        name=f"{file_base} - Proposal",
        parent_id=project_folder_id,
        label="Proposal",
    )
    if proposal_file_id:
        console.print("[cyan]→[/cyan]  Applying modifications to Proposal...")
        try:
            apply_modifications(creds, proposal_file_id, "proposal", variables, config)
        except Exception as exc:
            console.print(f"[yellow]⚠[/yellow]  Could not modify Proposal: {exc}")

    # Copy Purchase Summary & SOW template
    sow_file_id = _copy_template(
        service,
        file_id=config["templates"]["purchase_summary_sow"],
        name=f"{file_base} - Purchase Summary & SOW",
        parent_id=project_folder_id,
        label="Purchase Summary & SOW",
    )

    # Copy CU Calculator template
    if cu_calculator:
        cu_file_id = _copy_template(
            service,
            file_id=config["templates"]["cu_calculator"],
            name=f"{file_base} - CU Calculator",
            parent_id=project_folder_id,
            label="CU Calculator",
        )
        if cu_file_id:
            console.print("[cyan]→[/cyan]  Applying modifications to CU Calculator...")
            try:
                apply_modifications(creds, cu_file_id, "cu_calculator", variables, config)
            except Exception as exc:
                console.print(f"[yellow]⚠[/yellow]  Could not modify CU Calculator: {exc}")

    # GFA workflow
    if not skip_gfa:
        _handle_gfa(
            creds,
            service,
            sheets_service,
            gmail_service,
            config,
            file_base,
            project_folder_id,
            sow_file_id,
            project,
            account,
            opportunity_id,
            variables,
            gfa_url,
        )
    else:
        console.print("[dim]GFA step skipped (--skip-gfa).[/dim]")
        if sow_file_id:
            console.print("[cyan]→[/cyan]  Applying modifications to Purchase Summary & SOW...")
            try:
                apply_modifications(creds, sow_file_id, "purchase_summary_sow", variables, config)
            except Exception as exc:
                console.print(f"[yellow]⚠[/yellow]  Could not modify Purchase Summary & SOW: {exc}")

    # ── Done ───────────────────────────────────────────────────────────────
    folder_url = get_folder_url(project_folder_id)
    console.print(f"\n[bold green]✔  All done![/bold green]")
    console.print(f"   [link={folder_url}]{folder_url}[/link]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_account_folder(service, account: str, config: dict) -> str | None:
    """Search Drive for the account folder; let the user pick or create one.

    Returns the folder ID, or None if the user aborted.
    """
    root_id: str | None = config.get("search_root_id") or None

    console.print(
        f"\n[cyan]⌕[/cyan]  Searching for account folder [bold]\"{account}\"[/bold]..."
    )
    matches = search_folders(service, account, parent_id=root_id)

    if not matches:
        console.print(f"  [yellow]No folder found for \"{account}\".[/yellow]")
        if not Confirm.ask("  Create a new account folder?", default=True):
            console.print("[dim]Aborted.[/dim]")
            return None

        parent_raw = Prompt.ask(
            "  Parent folder ID or URL for the new folder",
            default=root_id or "",
        )
        if not parent_raw.strip():
            console.print("[red]✗[/red]  A parent folder is required.")
            return None

        parent_id = parse_file_id(parent_raw)
        folder_id = get_or_create_folder(service, account, parent_id)
        console.print(
            f"[green]✔[/green]  Created account folder: [bold]{account}[/bold]"
        )
        return folder_id

    if len(matches) == 1:
        m = matches[0]
        console.print(f"  Found: [bold]{m['path']}[/bold]")
        if not Confirm.ask("  Use this folder?", default=True):
            console.print("[dim]Aborted.[/dim]")
            return None
        return m["id"]

    # Multiple matches — let the user choose
    console.print("  Multiple folders found:\n")
    table = Table(show_header=False, box=None, padding=(0, 2))
    for i, m in enumerate(matches, start=1):
        table.add_row(f"[cyan][{i}][/cyan]", m["path"])
    console.print(table)

    choice = Prompt.ask(
        "\n  Select folder",
        default="1",
        choices=[str(i) for i in range(1, len(matches) + 1)],
    )
    selected = matches[int(choice) - 1]
    console.print(f"[green]✔[/green]  Using: [bold]{selected['path']}[/bold]")
    return selected["id"]


def _copy_template(
    service,
    file_id: str,
    name: str,
    parent_id: str,
    label: str,
) -> Optional[str]:
    """Copy a template file, log the result, and return the new file ID (or None on error). Skip if exists."""
    existing_id = find_file_by_name(service, name, parent_id)
    if existing_id:
        console.print(f"[green]✔[/green]  {label} exists: [bold]{name}[/bold]")
        return existing_id

    console.print(f"[cyan]→[/cyan]  Copying {label} template...")
    try:
        new_id = copy_file(service, file_id, name, parent_id)
        console.print(f"[green]✔[/green]  Copied:  [bold]{name}[/bold]")
        return new_id
    except Exception as exc:
        console.print(f"[red]✗[/red]  Failed to copy {label} template: {exc}")
        return None


def _handle_gfa(
    creds,
    service,
    sheets_service,
    gmail_service,
    config: dict,
    file_base: str,
    project_folder_id: str,
    sow_file_id: Optional[str],
    project: str,
    account: str,
    opportunity_id: str,
    variables: dict[str, Any],
    existing_gfa_url: Optional[str] = None,
) -> None:
    """Open the GFA form, wait for the email, then rename + shortcut + write cells."""
    gfa_form_url = config["templates"].get("gfa_form_url", "https://red.ht/gfa")
    gfa_name = f"{file_base} - GFA"

    # Check if GFA shortcut already exists in the project folder
    existing_gfa_sc = find_file_by_name(service, gfa_name, project_folder_id)
    if existing_gfa_sc:
        console.print(f"[green]✔[/green]  GFA shortcut exists: [bold]{gfa_name}[/bold]")
        return

    if existing_gfa_url:
        console.print(f"\n[cyan]→[/cyan] Using provided GFA URL: {existing_gfa_url}")
        gfa_input = existing_gfa_url
    else:
        # Fill form via playwright
        today = date.today()
        try:
            from dateutil.relativedelta import relativedelta
            term_start = today.replace(day=1) + relativedelta(months=1)
            term_end = term_start + relativedelta(years=1) - timedelta(days=1)
        except ImportError:
            # Fallback if dateutil is missing for some reason
            month = today.month + 1 if today.month < 12 else 1
            year = today.year if today.month < 12 else today.year + 1
            term_start = date(year, month, 1)
            term_end = date(year + 1, month, 1) - timedelta(days=1)

        geo = config.get("gfa", {}).get("default_geo", "EMEA")
        auto_submit = config.get("gfa", {}).get("submit_automatically", False)

        console.print(f"\n[cyan]→[/cyan] Opening GFA form (Browser Automation)")
        
        start_time = int(time.time())

        fill_gfa_form(
            form_url=gfa_form_url,
            account=account,
            opportunity_id=opportunity_id,
            geo=geo,
            term_start=term_start,
            term_end=term_end,
            auto_submit=auto_submit,
        )

        gfa_url_fetched = wait_for_gfa_email(
            gmail_service,
            account=account,
            opportunity_id=opportunity_id,
            start_time=start_time,
        )

        if gfa_url_fetched:
            console.print(f"\n[green]✔[/green]  Found GFA email: {gfa_url_fetched}")
            gfa_input = gfa_url_fetched
        else:
            console.print("\n[yellow]⚠[/yellow]  Email not received within timeout.")
            gfa_input = Prompt.ask("  Paste GFA sheet URL or file ID (or Enter to skip)", default="")

    if not gfa_input.strip():
        console.print(
            "[dim]  GFA step skipped. Add the shortcut to the proposal folder manually.[/dim]"
        )
        return

    gfa_file_id = parse_file_id(gfa_input.strip())
    gfa_url = f"https://docs.google.com/spreadsheets/d/{gfa_file_id}/edit"

    # Rename original
    try:
        rename_file(service, gfa_file_id, gfa_name)
        console.print(f"[green]✔[/green]  Renamed: [bold]{gfa_name}[/bold]")
    except Exception as exc:
        console.print(
            f"[yellow]⚠[/yellow]  Could not rename GFA file "
            f"(continuing anyway): {exc}"
        )

    # Create shortcut in proposal folder
    try:
        create_shortcut(service, gfa_file_id, gfa_name, project_folder_id)
        console.print(
            f"[green]✔[/green]  Shortcut: [bold]{gfa_name}[/bold] → original"
        )
    except Exception as exc:
        console.print(f"[red]✗[/red]  Failed to create GFA shortcut: {exc}")

    # Share GFA file with domain (Red Hat)
    try:
        domain = config.get("gfa", {}).get("domain", "redhat.com")
        add_commenter_permission(service, gfa_file_id, domain)
        console.print(
            f"[green]✔[/green]  Permissions: commenter access granted to anyone in [bold]{domain}[/bold] with the link"
        )
    except Exception as exc:
        console.print(
            f"[yellow]⚠[/yellow]  Could not update access permissions on GFA file (continuing anyway): {exc}"
        )


    variables["gfa_url"] = gfa_url

    # Write GFA URL in the Purchase Summary & SOW sheet
    if sow_file_id:
        console.print("[cyan]→[/cyan]  Applying modifications to Purchase Summary & SOW...")
        try:
            apply_modifications(creds, sow_file_id, "purchase_summary_sow", variables, config)
            console.print(
                "[green]✔[/green]  Purchase Summary & SOW customized."
            )
        except Exception as exc:
            console.print(
                f"[yellow]⚠[/yellow]  Could not customize Purchase Summary & SOW sheet: {exc}"
            )

    # Customize the GFA sheet
    console.print("[cyan]→[/cyan]  Customizing GFA sheet...")
    try:
        apply_modifications(creds, gfa_file_id, "gfa", variables, config)
        console.print(
            "[green]✔[/green]  GFA customized."
        )
    except Exception as exc:
        console.print(f"[yellow]⚠[/yellow]  Could not customize GFA sheet: {exc}")
