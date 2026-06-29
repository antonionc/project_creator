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

### Step 2 — Enable Google APIs

1. In your project, go to **"APIs & Services"** → **"Library"**
2. Search for and enable:
   - **Google Drive API** (required for folder and file operations)
   - **Gmail API** (required for the `gmail.readonly` OAuth scope — see [Gmail access](#gmail-access-gmailreadonly) below)

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
- Open a browser tab asking you to authorize Google access (Drive and Gmail read-only)
- Save your OAuth token for reuse on future runs — in the **macOS Keychain** on Mac, or as `token.json` on other platforms (see [Token storage](#token-storage-and-device-security))
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

### OAuth scopes

| Scope | Purpose |
|---|---|
| `https://www.googleapis.com/auth/drive` | Create folders, copy templates, rename files, and manage shortcuts across Shared Drives |
| `https://www.googleapis.com/auth/gmail.readonly` | Poll your inbox for the automated GFA response email after form submission |

### Gmail access (`gmail.readonly`)

The tool requests **read-only** Gmail access so it can wait for the GFA confirmation email and extract the Google Sheets link automatically. This scope:

- **Can** list and read messages in your inbox (used only to search for GFA emails matching the customer account)
- **Cannot** send, delete, or modify email, labels, or drafts

If you prefer not to grant Gmail access:

| Option | When to use |
|---|---|
| `--gfa-url URL` | You already have the GFA sheet URL or ID — skips browser submission **and** Gmail polling |
| `--skip-gfa` | You will add the GFA shortcut manually later |

Example without Gmail polling:

```bash
project-creator create --account "Acme" --project "Alpha" \
  --gfa-url "https://docs.google.com/spreadsheets/d/SHEET_ID/edit"
```

To revoke access later: [Google Account → Third-party apps with account access](https://myaccount.google.com/permissions).

### Token storage and device security

OAuth tokens grant broad Drive access. Protect the machine where you run this tool:

| Platform | Token storage | Recommendations |
|---|---|---|
| **macOS** | Encrypted in **Keychain** via `keyring` (service: `project-creator`) — **required**; Keychain failures block authentication rather than falling back to plaintext | Enable **FileVault**, require password on wake, use a screen lock, and do not share your user account |
| **Linux / Windows** | Plaintext `~/.config/project_creator/token.json` (`0o600`) | Encrypt the home directory or full disk, lock the screen when away, restrict file permissions on shared hosts |

Additional practices:

- **Never commit** `credentials.json` or `token.json` — both are listed in `.gitignore`
- **Do not run** on shared or multi-user machines where others can access your home directory or Keychain
- **Revoke tokens** promptly if a laptop is lost or you stop using the tool ([Google Account permissions](https://myaccount.google.com/permissions))
- **Re-authenticate** after scope changes by running `project-creator setup` (stale tokens are removed automatically)

On macOS, existing plaintext `token.json` files are migrated to Keychain on the next successful login and the file is removed.

### Other protections

- OAuth secret files are created with restrictive permissions (`0o700` on the config directory, `0o600` on credential files)
- The Playwright Chrome profile at `~/.project_creator_chrome` is also restricted to `0o700` — do not run this tool on shared machines where other users can access your home directory
- Verbose debug output (Gmail polling details, browser automation traces) is off by default; enable with `--verbose` or `PROJECT_CREATOR_DEBUG=1`
- GFA domain sharing is restricted by `gfa.domain_allow_list` in config (default: `redhat.com` only); non-default domains require confirmation before granting access
- Gmail search values and GFA sheet URLs are validated before use; modification YAML writes use `RAW` input by default to avoid formula injection
- Tokens are refreshed automatically; re-authorization is only needed if you revoke access in your Google account settings

---

## Future Plans (Phase 2)

- Pre-populate proposal content based on desired services scope
- Named account profiles (multiple Shared Drive roots)
- `list` command to browse existing proposals for an account
