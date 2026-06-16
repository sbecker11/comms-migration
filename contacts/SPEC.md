# Contacts.yaml — specification

## Overview

`contacts/Contacts.yaml` is the canonical contact store for comms migration. It is initialized from the macOS Contacts database and edited via a local web app. Group membership drives hub assignment (`Professional`, `Personal`) and soft-delete (`Is Deleted`).

## Components

| Component | Path | Role |
|---|---|---|
| Init utility | `scripts/init_contacts.py` | Extract macOS Contacts → `Contacts.yaml` |
| Extraction library | `contacts/extract.py` | JXA batch reader for Contacts.app |
| Store library | `contacts/store.py` | Load/save/filter YAML |
| Web app | `contacts_app/main.py` | Browse, search, edit contacts |

## 1. Init utility

**Command:** `python scripts/init_contacts.py`

**Behavior:**

1. Reads all people from macOS Contacts via JavaScript for Automation (batched).
2. Collects all macOS contact group names into `meta.groups`.
3. Appends standard groups: `Professional`, `Personal`, `Is Deleted`.
4. Writes `contacts/Contacts.yaml` atomically (temp file + rename).

**Flags:**

- `--force` — overwrite existing YAML
- `--merge` — re-import contacts; preserve `groups` edits for matching `id`
- `--output PATH` — custom output path

**Permissions:** Terminal (or IDE) needs Contacts access in System Settings.

## 2. Web app

**Command:** `uvicorn contacts_app.main:app --reload --port 8080`

### List page (`GET /`)

| Feature | Implementation |
|---|---|
| Data source | `contacts/Contacts.yaml` |
| Search | Substring match on name, org, email, phone, notes |
| Filter | Dropdown of `meta.groups` |
| Pagination | `page`, `per_page` (25/50/100) |
| Deleted | Hidden by default; `include_deleted=true` shows contacts in `Is Deleted` group |

### Detail page (`GET /contacts/{id}`)

Editable fields:

- First name, last name, organization
- Email addresses (label + value, repeatable)
- Phone numbers (label + value, repeatable)
- LinkedIn URL (dedicated field)
- Other websites (label + value, repeatable)
- Notes
- **Group checkboxes** — one per entry in `meta.groups`, including `Is Deleted`

### Save (`POST /contacts/{id}`)

- **Save** — validates form, updates contact in memory, writes `Contacts.yaml`
- **Cancel** — returns to list without writing

## 3. Data model

### Contact `id`

Stable identifier from macOS (`{UUID}:ABPerson`). Never change on edit.

### Groups

- Imported from macOS on init.
- Standard groups always available: `Professional`, `Personal`, `Is Deleted`.
- A contact may belong to **multiple** groups except hub groups should be mutually exclusive in practice.
- `Is Deleted` — soft delete; excluded from default list view.

### LinkedIn

Stored in `linkedin` field and mirrored into `urls` with label `LinkedIn` on save.

## 4. Future integration

- Export `Professional` / `Personal` contacts to `rules/senders.yaml` (script TBD).
- Phase 5 classifier may load group membership for sender lookup.

## 5. Non-goals (v1)

- Two-way sync back to macOS Contacts
- Multi-user / concurrent editing
- Authentication (local dev tool only)
