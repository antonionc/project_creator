# GFA Automation: Form Submission + Email Monitoring

## Overview

Two new automation stages replace the current manual GFA step:

1. **Form submission** — Playwright fills and submits the Red Hat GFA Google Form using data from the CLI session, with a user review step before submission.
2. **Email monitoring** — the Gmail API polls the inbox for the delivery email, extracts the GFA sheet link, and continues the workflow automatically. If the timeout expires, the user is prompted to paste the URL manually so the rest of the steps (rename, shortcut, cell writes) still execute.

---

## Proposed Changes

### Dependencies

#### [MODIFY] pyproject.toml
Add Playwright and install its Chromium browser:
```toml
[project.dependencies]
...
"playwright>=1.44",
"google-api-python-client>=2.0",   # already present
```
First-time setup will run `playwright install chromium` automatically.

---

### Auth & Scopes

#### [MODIFY] auth.py

Add the Gmail read-only scope. Because the scope list is changing, existing `token.json` files will be invalid. The `get_credentials()` function already refreshes on scope mismatch (the `google-auth` library raises `RefreshError`); we will add a clear message prompting the user to re-run `project-creator setup`.

```python
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly",
]
```

> [!WARNING]
> **Existing users must re-run `project-creator setup` once** after this update. The tool will detect the stale token and show a clear error message with instructions.

---

### Configuration

#### [MODIFY] config.py + setup wizard

New section added to `~/.config/project_creator/config.yaml`:

```yaml
gfa:
  default_geo: "EMEA"        # GEO dropdown default; configurable via setup
  default_opportunity: ""    # Optional standing opportunity ID (usually left blank)
  submit_automatically: false  # false = review before submitting; flip after first few runs
```

The `setup` wizard gains a new **GFA defaults** section asking for `default_geo` and whether to auto-submit.

---

### New Module: `project_creator/gfa_form.py`

Handles Playwright browser automation for the GFA form.

```python
def fill_gfa_form(
    form_url: str,
    account: str,
    opportunity_id: str,
    geo: str,
    term_start: date,       # first day of next calendar month by default
    term_end: date,         # term_start + 1 year − 1 day
    auto_submit: bool = False,
) -> None
```

**Implementation approach:**
- Opens a **persistent Playwright browser context** pointing to the user's existing Chrome profile
  (`~/Library/Application Support/Google/Chrome/Default`) so no re-login is needed.
- Navigates to `form_url` (the `red.ht/gfa` redirect).
- Locates fields by their **visible label text** (robust to Google Form layout changes).
- Fills in order:
  | Field | Source |
  |---|---|
  | Include email checkbox | Checked (mandatory) |
  | Opportunity number | `--opportunity-id` flag or prompted; default = project name |
  | Customer/Partner name | Account name from CLI |
  | GEO dropdown | Config default `EMEA`; overridable |
  | Term Start Date (mm/dd/yyyy) | 1st of next calendar month from today |
  | Term End Date (mm/dd/yyyy) | Term Start + 1 year − 1 day |
- If `auto_submit=False`: pauses — the browser stays open and the CLI shows a review table and confirms before proceeding.
- Submits the form and waits for the "Thank you" confirmation page.

---

### New Module: `project_creator/gmail.py`

Handles Gmail API polling.

```python
def build_gmail_service(creds: Credentials):
    """Build and return an authenticated Gmail v1 service."""

def wait_for_gfa_email(
    gmail_service,
    account: str,
    opportunity_id: str,
    timeout_s: int = 600,
    poll_interval_s: int = 15,
) -> Optional[str]:
    """
    Poll inbox for subject matching:
      "Your GFA for {account}, Opportunity # {opportunity_id}"
    
    Extracts the href of the "here" hyperlink from the HTML email body.
    Returns the URL, or None on timeout.
    """
```

- Uses a Gmail API `q` search query:  
  `subject:"Your GFA for {account}, Opportunity #" after:{submit_epoch}` 
  (the `after:` restricts to emails received after form submission, avoiding false matches from previous runs)
- Polls every 15 seconds, displays a live spinner/countdown in the terminal.
- Parses the HTML body with `html.parser` (stdlib — no extra dependency) to extract the `href` of the anchor whose text is `"here"`.
- Returns `None` after timeout — the caller falls back gracefully.

---

### Updated: `project_creator/cli.py`

#### New `create` command option

```
-o, --opportunity-id    Opportunity number for the GFA form.
                        Defaults to the project name if not provided.
```

#### Date defaults (calculated at runtime)

```python
from datetime import date
from dateutil.relativedelta import relativedelta   # already available via google-auth deps

today = date.today()
term_start = today.replace(day=1) + relativedelta(months=1)   # 1st of next month
term_end   = term_start + relativedelta(years=1) - timedelta(days=1)
```

#### Updated `_handle_gfa()` flow

```
1. Collect opportunity_id (from flag or prompt; default = project name)
2. Calculate term_start, term_end
3. Show pre-submission review table in terminal:
     Account:       Abanca
     Opportunity #: n/a
     GEO:           EMEA
     Term Start:    05/01/2026
     Term End:      04/30/2027
4. [if auto_submit=False] Confirm.ask("Submit GFA form?")
      → No  → skip GFA step entirely (existing behaviour)
      → Yes → proceed
5. fill_gfa_form(...)    # Playwright submits the form
6. Start Gmail poll with live progress:
     ⏳  Waiting for GFA email (up to 10 min)...  [0:00:45 elapsed]
7a. Email found → extract URL → continue
7b. Timeout     → prompt "Email not received. Paste GFA URL/ID (or Enter to skip):"
                  → if provided: continue with that ID
                  → if skipped:  print warning and return (no rename/shortcut/cell writes)
8. rename_file, create_shortcut, write_cell (SOW), customize_gfa
```

---

### Build & Setup Changes

#### [MODIFY] `setup` command additions
- Prompt for `gfa.default_geo` (default `EMEA`)
- Prompt for `gfa.submit_automatically` (default `false`)
- Run `playwright install chromium` on first setup if not already installed.

---

## Verification Plan

### Automated Tests

- `tests/test_gfa_form.py` — mock Playwright `Page` object; assert correct field labels are targeted, correct values written, date arithmetic is correct.
- `tests/test_gmail.py` — mock Gmail API list/get responses; test subject match, `"here"` link extraction, timeout path, manual fallback path.
- Extend `tests/test_cli.py` — test that timeout fallback prompts and still executes downstream steps when user provides a manual ID.

### Manual Verification

- Run `project-creator create` end-to-end:
  1. CLI shows review table → user confirms.
  2. Browser opens, form fields are pre-filled (opportunity, account, GEO, dates).
  3. User clicks Submit (or it auto-submits).
  4. CLI shows countdown spinner.
  5. Email arrives → GFA file is renamed, shortcutted, and cells populated.
  6. Test timeout path by temporarily using an impossible subject string.
