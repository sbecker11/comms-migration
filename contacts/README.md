# Contacts.yaml editor

Browse and edit `contacts/Contacts.yaml` — extracted from macOS Contacts, used to build destination rules for comms migration.

## Setup

```bash
cd /Users/sbecker11/workspace-comms/comms-migration
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Grant **Contacts** access when prompted (System Settings → Privacy & Security → Contacts).

## 1. Initialize Contacts.yaml from macOS

```bash
python scripts/init_contacts.py
```

Options:

- `--output PATH` — output file (default: `contacts/Contacts.yaml`)
- `--force` — overwrite existing file
- `--merge` — re-import from macOS but keep edited `groups` on matching contact IDs

Import takes several minutes for large address books (~1,300 contacts).

## 2. Run the web app

```bash
uvicorn contacts_app.main:app --reload --port 8080
```

Open http://127.0.0.1:8080

## Contacts.yaml schema

```yaml
meta:
  version: 1
  updated_at: ISO-8601 UTC
  groups:          # checkbox options in the UI
    - Professional
    - Personal
    - Is Deleted
    # …plus groups imported from macOS Contacts

contacts:
  - id: macos-uuid:ABPerson
    first_name: ""
    last_name: ""
    organization: ""
    emails: [{ label: Work, value: user@example.com }]
    phones: [{ label: Mobile, value: "+1…" }]
    urls: [{ label: Homepage, value: https://… }]
    linkedin: ""    # synced with urls
    groups: []      # subset of meta.groups
    notes: ""
    source: macos_contacts
```

`contacts/Contacts.yaml` is gitignored (PII). Use `contacts/Contacts.yaml.example` as a reference.

## Web app behavior

- **List:** search, filter by group, pagination, hide/show deleted
- **Detail:** edit standard fields; group checkboxes (including **Is Deleted**); Save writes `Contacts.yaml` atomically; Cancel returns to list

See `contacts/SPEC.md` for the full specification.
