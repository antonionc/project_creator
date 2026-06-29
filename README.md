# Red Hat Proposal Creator

A CLI tool that automates the creation of consulting proposal folders in Google Drive for Red Hat TSMs.

Given a customer account name and project, it:

- Searches Google Drive for the account folder (creates it if missing)
- Creates `Proposals/<Year>/<Project Name> (<Mon YY>)` inside it
- Copies your Proposal (Slides) and Purchase Summary & SOW (Sheets) templates into the folder with correct naming
- Opens the GFA form (`red.ht/gfa`), then renames the resulting sheet and creates a Drive Shortcut in the proposal folder

---

## Installation

```bash
cd /path/to/project_creator
pip install -e .
```

After installation, the `project-creator` command is available globally.

---

## Google Credentials Setup

You need a Google Cloud project with the Drive API enabled and an OAuth 2.0 client to authorize Drive access.

### Step 1 — Create a Google Cloud Project

1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Click **"Select a project"** → **"New Project"**
3. Name it (e.g. `rh-proposal-creator`) and click **"Create"**

### Step 2 — Enable the Google Drive API

1. In your project, go to **"APIs & Services"** → **"Library"**
2. Search for **"Google Drive API"** and click **"Enable"**

### Step 3 — Create OAuth 2.0 Credentials

1. Go to **"APIs & Services"** → **"Credentials"**
2. Click **"Create Credentials"** → **"OAuth client ID"**
3. If prompted, configure the **OAuth consent screen** first:
   - **User Type**: Internal (recommended if your Red Hat account is Google Workspace) or External
   - Fill in app name and your email, then click **Save**
   - Add the scopes `https://www.googleapis.com/auth/drive` and `https://www.googleapis.com/auth/gmail.readonly`
   - If External: add your email as a **test user**
4. Back in Credentials → Create OAuth client ID:
   - **Application type**: Desktop app
   - Name it (e.g. `proposal-creator-cli`) and click **"Create"**
5. Download the JSON file and save it here:
   ```
   ~/.config/project_creator/credentials.json
   ```

### Step 4 — Run First-Time Setup

```bash
project-creator setup
```

This will:
- Verify `credentials.json` exists
- Open a browser tab asking you to authorize Drive access
- Save a `token.json` in `~/.config/project_creator/` — reused automatically on future runs
- Prompt you to enter your template file IDs and optional search scope

---

## Configuration

Configuration is stored at `~/.config/project_creator/config.yaml`.

See [`config.example.yaml`](config.example.yaml) for the full schema. Key fields:

| Field | Description |
|---|---|
| `templates.proposal` | File ID (or URL) of your master Proposal (Slides) template |
| `templates.purchase_summary_sow` | File ID (or URL) of your Purchase Summary & SOW (Sheets) template |
| `templates.gfa_form_url` | URL of the GFA form (default: `https://red.ht/gfa`) |
| `search_root_id` | Optional: Shared Drive or folder ID to scope account folder searches |

**Finding a Google Drive file ID:** open the file in Drive and copy the `{ID}` from:
```
drive.google.com/file/d/{ID}/edit
```

---

## Usage

### Create a new proposal

```bash
project-creator create
```

The tool will prompt for:

- **Account name** — customer name used to search Drive (e.g. `Acme Corp`)
- **Project name** — used in the folder name (e.g. `Platform Migration`)
- **Year** — defaults to current year
- **Month** — defaults to current month abbreviation

All prompts can be provided as flags for scripting:

```bash
project-creator create \
  --account "Acme Corp" \
  --project "Platform Migration" \
  --year 2026 \
  --month Apr
```

**Skip the GFA step** (add the shortcut manually later):

```bash
project-creator create --skip-gfa
```

### Example session

```
$ project-creator create
  Account name: Acme Corp
  Project name: Platform Migration
  Year [2026]:
  Month [Apr]:

⌕  Searching for account folder "Acme Corp"...
  Found: My Drive > Customers > Acme Corp
  Use this folder? [Y/n]:

→  Building Proposals/2026/Platform Migration (Apr 26)
✔  Folder ready: Proposals/2026/Platform Migration (Apr 26)

→  Copying Proposal template...
✔  Copied:  Acme Corp - Platform Migration (Apr 26) - Proposal

→  Copying Purchase Summary & SOW template...
✔  Copied:  Acme Corp - Platform Migration (Apr 26) - Purchase Summary & SOW

→  Opening GFA form: https://red.ht/gfa
  Fill in the form. Once you receive the generated sheet by email,
  paste its URL below. Press Enter to skip and add manually later.

  GFA sheet URL or file ID: https://docs.google.com/spreadsheets/d/SHEET_ID/edit

✔  Renamed: Acme Corp - Platform Migration (Apr 26) - GFA
✔  Shortcut: Acme Corp - Platform Migration (Apr 26) - GFA → original

✔  All done!
   https://drive.google.com/drive/folders/...
```

---

## Security

- `credentials.json` and `token.json` are stored only in `~/.config/project_creator/` and are listed in `.gitignore` — **never commit them**
- OAuth secret files are created with restrictive permissions (`0o700` on the config directory, `0o600` on credential files)
- The Playwright Chrome profile at `~/.project_creator_chrome` is also restricted to `0o700` — do not run this tool on shared machines where other users can access your home directory
- Verbose debug output (Gmail polling details, browser automation traces) is off by default; enable with `--verbose` or `PROJECT_CREATOR_DEBUG=1`
- GFA domain sharing is restricted by `gfa.domain_allow_list` in config (default: `redhat.com` only); non-default domains require confirmation before granting access
- Gmail search values and GFA sheet URLs are validated before use; modification YAML writes use `RAW` input by default to avoid formula injection
- The OAuth scopes used are `https://www.googleapis.com/auth/drive` (full Drive access required to create folders, copy files, and create shortcuts across Shared Drives) and `https://www.googleapis.com/auth/gmail.readonly` (read-only Gmail access required to poll your inbox and automatically retrieve the GFA form response email)
- Tokens are refreshed automatically; re-authorization is only needed if you revoke access in your Google account settings

---

## Future Plans (Phase 2)

- Pre-populate proposal content based on desired services scope
- Named account profiles (multiple Shared Drive roots)
- `list` command to browse existing proposals for an account
