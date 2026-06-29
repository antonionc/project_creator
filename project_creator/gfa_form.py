"""Automates GFA Google Form submission using Playwright."""

# Assisted-by: Cursor

from datetime import date
from pathlib import Path
import re

from playwright.sync_api import sync_playwright, Page
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from .verbose import is_verbose

console = Console()

CHROME_PROFILE_DIR = Path.home() / ".project_creator_chrome"


def ensure_chrome_profile_permissions() -> Path:
    """Ensure the Playwright Chrome profile directory has restrictive permissions."""
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    CHROME_PROFILE_DIR.chmod(0o700)
    return CHROME_PROFILE_DIR


def fill_gfa_form(
    form_url: str,
    account: str,
    opportunity_id: str,
    geo: str,
    term_start: date,
    term_end: date,
    auto_submit: bool = False,
) -> None:
    """Fills the GFA form using a persistent Chrome browser instance."""

    # Use a dedicated profile directory for Project Creator to prevent DevTools
    # conflicts with the system default Chrome profile.
    user_data_dir = ensure_chrome_profile_permissions()

    # Check if we should pause for review
    if not auto_submit:
        _show_review_table(account, opportunity_id, geo, term_start, term_end)

    with sync_playwright() as p:
        try:
            # We use the actual user's Chrome profile so they don't have to log in to Google
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=False,
                args=["--profile-directory=Default"]
            )
        except Exception as exc:
            console.print(
                f"[red]✗[/red] Could not launch Chrome: {exc}\n"
                "Please ensure no conflicting Chrome instances are tying up the debugging port."
            )
            return

        console.print(
            "\n[dim]Note: Project Creator uses a dedicated Chrome profile. "
            "You may need to log in to Google the first time.[/dim]"
        )

        if is_verbose():
            console.print(f"[dim]DEBUG: Context launched. {len(context.pages)} pages detected in context.[/dim]")
        if context.pages:
            for i, p in enumerate(context.pages):
                if is_verbose():
                    console.print(f"[dim]DEBUG: Page {i}: {p.url}[/dim]")
            page = context.pages[-1]
            if is_verbose():
                console.print(f"[dim]DEBUG: Bringing page {len(context.pages)-1} to front.[/dim]")
            page.bring_to_front()
        else:
            if is_verbose():
                console.print("[dim]DEBUG: No pages in context. Creating new page.[/dim]")
            page = context.new_page()

        console.print(f"\n[cyan]→[/cyan] Opening GFA form...")
        if is_verbose():
            console.print(f"[dim]DEBUG: Attempting to navigate to {form_url}[/dim]")
        try:
            response = page.goto(form_url, wait_until="domcontentloaded", timeout=15000)
            if is_verbose():
                console.print(f"[dim]DEBUG: Navigation response: {response.status if response else 'None'}[/dim]")
        except Exception as e:
            if is_verbose():
                console.print(f"[red]DEBUG: Error during navigation: {e}[/red]")

        console.print("[cyan]→[/cyan] Filling form fields...")

        if is_verbose():
            try:
                questions_text = page.locator("div[role='listitem']").all_inner_texts()
                console.print("[dim]DEBUG: Found the following form questions:[/dim]")
                for q_text in questions_text:
                    q_title = q_text.split('\n')[0] if q_text else 'Unknown'
                    console.print(f"[dim]  - {q_title}[/dim]")
            except Exception as e:
                console.print(f"[dim]DEBUG: Failed to extract question titles: {e}[/dim]")

        try:
            # Provide input to the DOM
            # Google Form DOM structure relies on role="listitem" for questions

            # Record email checkbox (often prepended to the form if email collection is enabled)
            _check_checkbox(page, "Record .* as the email")

            # Opportunity number
            _fill_text_input(page, "Opportunity", opportunity_id)

            # Customer/Partner name
            _fill_text_input(page, "Account|Customer|Partner", account)

            # GEO dropdown
            _select_dropdown(page, "Geo|Region", geo)

            # Dates
            _fill_date(page, "Term Start", term_start)
            _fill_date(page, "Term End", term_end)

            if not auto_submit:
                if not Confirm.ask("\n[bold]Review the browser window. Submit GFA form?[/bold]"):
                    console.print("[dim]Submission cancelled.[/dim]")
                    context.close()
                    return

            console.print("[cyan]→[/cyan] Submitting form...")
            submit_btn = page.locator("div[role='button']").filter(has_text="Submit")
            if submit_btn.count() > 0:
                submit_btn.first.click()
            else:
                page.get_by_role("button", name="Submit").click()

            # Wait for confirmation page
            page.wait_for_selector("text=Your response has been recorded", timeout=15000)
            console.print("[green]✔[/green] Form submitted successfully.")

        except Exception as exc:
            console.print(f"[red]✗[/red] Error interacting with the form: {exc}")
            console.print("  [dim]The Google Form layout may have changed, or elements are missing.[/dim]")
        finally:
            # Minor delay to assure submission completes
            page.wait_for_timeout(2000)
            context.close()


def _fill_text_input(page: Page, label_regex: str, value: str):
    """Attempts to find a text input by its surrounding label text and fills it."""
    if not value:
        return
    try:
        # Search for a listitem (question container) containing the label regex
        question = page.locator("div[role='listitem']").filter(has_text=re.compile(label_regex, re.IGNORECASE))
        input_el = question.locator("input[type='text']")
        if input_el.count() > 0:
            input_el.first.fill(value)
        else:
            # Fallback
            question.locator("textarea").first.fill(value)
    except Exception as e:
        console.print(f"  [yellow]⚠[/yellow] Could not fill '{label_regex}': {e}")


def _select_dropdown(page: Page, label_regex: str, option: str):
    """Selects an option from a Google Forms dropdown."""
    if not option:
        return
    try:
        question = page.locator("div[role='listitem']").filter(has_text=re.compile(label_regex, re.IGNORECASE))
        dropdown = question.locator("div[role='listbox']")
        if dropdown.count() > 0:
            dropdown.first.click()
            page.wait_for_timeout(800)  # wait for animation
            # Find the option inside the dropdown overlay
            page.locator("div[role='option']").filter(has_text=re.compile(option, re.IGNORECASE)).first.click()
            page.wait_for_timeout(300)
    except Exception as e:
        console.print(f"  [yellow]⚠[/yellow] Could not select dropdown for '{label_regex}': {e}")


def _fill_date(page: Page, label_regex: str, d: date):
    """Fills a Google Forms date input."""
    if not d:
        return
    try:
        question = page.locator("div[role='listitem']").filter(has_text=re.compile(label_regex, re.IGNORECASE))
        date_input = question.locator("input[type='date']")
        if date_input.count() > 0:
            date_input.first.fill(d.strftime("%Y-%m-%d"))
        else:
            page.get_by_label(re.compile(label_regex, re.IGNORECASE)).first.fill(d.strftime("%m/%d/%Y"))
    except Exception as e:
        console.print(f"  [yellow]⚠[/yellow] Could not fill date for '{label_regex}': {e}")


def _check_checkbox(page: Page, label_regex: str):
    """Checks a Google Forms checkbox if one matches the label."""
    try:
        if is_verbose():
            console.print(f"[dim]DEBUG: Scanning for checkbox matching '{label_regex}'[/dim]")
        checkboxes = page.get_by_role("checkbox")
        count = checkboxes.count()
        if is_verbose():
            console.print(f"[dim]DEBUG: Found {count} total checkboxes on page.[/dim]")

        found = False
        for i in range(count):
            cb = checkboxes.nth(i)
            # Check aria-label first, fallback to inner text
            acc_name = cb.get_attribute("aria-label") or ""
            inner_text = cb.inner_text() or ""

            if is_verbose():
                console.print(f"[dim]DEBUG: Checkbox {i} -> ARIA: '{acc_name}', Text: '{inner_text}'[/dim]")

            if re.search(label_regex, acc_name, re.IGNORECASE) or re.search(label_regex, inner_text, re.IGNORECASE):
                found = True
                is_checked = cb.get_attribute("aria-checked") == "true"
                if not is_checked:
                    if is_verbose():
                        console.print(f"[dim]DEBUG: Checkbox {i} matches and is unchecked. Clicking it![/dim]")
                    # Click visually centered or force click to avoid interception
                    cb.click(force=True)
                    page.wait_for_timeout(300)
                elif is_verbose():
                    console.print(f"[dim]DEBUG: Checkbox {i} matches but is already checked.[/dim]")
                break

        if not found and is_verbose():
            console.print(f"[yellow]DEBUG: Warning - No checkbox matched '{label_regex}'[/yellow]")

    except Exception as e:
        console.print(f"  [yellow]⚠[/yellow] Could not click checkbox for '{label_regex}': {e}")


def _show_review_table(account: str, opportunity_id: str, geo: str, term_start: date, term_end: date):
    """Displays a pre-submission review table."""
    table = Table(title="GFA Pre-Submission Review", show_header=False, box=None)
    table.add_row("Account:", f"[bold]{account}[/bold]")
    table.add_row("Opportunity #:", f"[bold]{opportunity_id}[/bold]")
    table.add_row("GEO:", f"[bold]{geo}[/bold]")
    table.add_row("Term Start:", f"[bold]{term_start.strftime('%m/%d/%Y')}[/bold]")
    table.add_row("Term End:", f"[bold]{term_end.strftime('%m/%d/%Y')}[/bold]")
    console.print()
    console.print(table)
