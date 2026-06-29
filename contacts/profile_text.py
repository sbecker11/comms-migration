"""Extract supplemental profile text from macOS Contacts for notes sync."""

from __future__ import annotations

import json
import sys
from typing import Any

from contacts.extract import BATCH_SIZE, _run_jxa, fetch_contact_count
from contacts.store import DEFAULT_CONTACTS_PATH, load, save

PROFILE_JXA_HELPERS = r"""
function cleanLabel(label) {
  if (!label) return "";
  return String(label).replace(/_\$\!<(.+)>!\$_/, "$1");
}

function safeString(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function safeCall(fn) {
  try { return safeString(fn()); } catch (e) { return ""; }
}

function mapProfileFields(p) {
  const addresses = p.addresses().map(function(a) {
  const lines = [
      safeCall(function() { return a.street(); }),
      [safeCall(function() { return a.city(); }),
       safeCall(function() { return a.state(); }),
       safeCall(function() { return a.zip(); })].filter(Boolean).join(" "),
      safeCall(function() { return a.country(); }),
    ].filter(Boolean);
    return {
      label: cleanLabel(safeCall(function() { return a.label(); })),
      value: lines.join("\n"),
    };
  }).filter(function(a) { return a.value; });

  const related = [];
  try {
    p.related().forEach(function(r) {
      const name = safeCall(function() { return r.name(); });
      if (!name) return;
      related.push({
        label: cleanLabel(safeCall(function() { return r.label(); })),
        value: name,
      });
    });
  } catch (e) {}

  const socialProfiles = [];
  try {
    p.socialProfiles().forEach(function(s) {
      const parts = [
        safeCall(function() { return s.service(); }),
        safeCall(function() { return s.username(); }),
        safeCall(function() { return s.url(); }),
      ].filter(Boolean);
      if (parts.length === 0) return;
      socialProfiles.push({ label: "Social", value: parts.join(" — ") });
    });
  } catch (e) {}

  const instantMessages = [];
  try {
    p.instantMessages().forEach(function(m) {
      const value = safeCall(function() { return m.value(); });
      if (!value) return;
      instantMessages.push({
        label: cleanLabel(safeCall(function() { return m.label(); })),
        value: value,
      });
    });
  } catch (e) {}

  return {
    id: p.id(),
    note: safeCall(function() { return p.note(); }),
    job_title: safeCall(function() { return p.jobTitle(); }),
    department: safeCall(function() { return p.department(); }),
    nickname: safeCall(function() { return p.nickname(); }),
    middle_name: safeCall(function() { return p.middleName(); }),
    prefix: safeCall(function() { return p.prefix(); }),
    suffix: safeCall(function() { return p.suffix(); }),
    maiden_name: safeCall(function() { return p.maidenName(); }),
    phonetic_first_name: safeCall(function() { return p.phoneticFirstName(); }),
    phonetic_last_name: safeCall(function() { return p.phoneticLastName(); }),
    addresses: addresses,
    related: related,
    social_profiles: socialProfiles,
    instant_messages: instantMessages,
  };
}
"""


def fetch_profile_fields_batch(offset: int, limit: int) -> list[dict[str, Any]]:
    script = f"""
    {PROFILE_JXA_HELPERS}
    const app = Application("Contacts");
    const people = app.people().slice({offset}, {offset + limit});
    JSON.stringify(people.map(mapProfileFields));
    """
    raw = _run_jxa(script)
    return json.loads(raw) if raw else []


def _labeled_lines(profile: dict[str, Any], field_specs: list[tuple[str, str]]) -> list[str]:
    lines: list[str] = []
    for label, key in field_specs:
        value = (profile.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    return lines


def _labeled_entries(entries: list[dict[str, str]] | None) -> list[str]:
    lines: list[str] = []
    for entry in entries or []:
        value = (entry.get("value") or "").strip()
        if not value:
            continue
        label = (entry.get("label") or "").strip()
        if label:
            lines.append(f"{label}: {value}")
        else:
            lines.append(value)
    return lines


def build_profile_notes(profile: dict[str, Any]) -> str:
    """Assemble free-text notes from macOS profile fields not stored elsewhere in YAML."""
    parts: list[str] = []

    note = (profile.get("note") or "").strip()
    if note:
        parts.append(note)

    profile_lines = _labeled_lines(
        profile,
        [
            ("Prefix", "prefix"),
            ("Nickname", "nickname"),
            ("Middle name", "middle_name"),
            ("Maiden name", "maiden_name"),
            ("Suffix", "suffix"),
            ("Phonetic first name", "phonetic_first_name"),
            ("Phonetic last name", "phonetic_last_name"),
            ("Job title", "job_title"),
            ("Department", "department"),
        ],
    )
    profile_lines.extend(_labeled_entries(profile.get("addresses")))
    profile_lines.extend(_labeled_entries(profile.get("related")))
    profile_lines.extend(_labeled_entries(profile.get("social_profiles")))
    profile_lines.extend(_labeled_entries(profile.get("instant_messages")))

    if profile_lines:
        parts.append("\n".join(profile_lines))

    return "\n\n".join(parts).strip()


def sync_profile_notes_to_yaml(
    contacts_path: str | Any = DEFAULT_CONTACTS_PATH,
    *,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
    progress: bool = True,
) -> dict[str, int]:
    """Pull macOS profile text and write it to each contact's notes field."""
    data = load(contacts_path)
    by_id = {contact["id"]: contact for contact in data["contacts"]}

    total = fetch_contact_count()
    updated = 0
    unchanged = 0
    missing = 0

    if progress:
        print(f"Reading profile text for {total} macOS contacts…", file=sys.stderr)

    offset = 0
    while offset < total:
        batch = fetch_profile_fields_batch(offset, batch_size)
        for profile in batch:
            contact = by_id.get(profile["id"])
            if contact is None:
                missing += 1
                continue
            new_notes = build_profile_notes(profile)
            if (contact.get("notes") or "").strip() == new_notes:
                unchanged += 1
                continue
            contact["notes"] = new_notes
            updated += 1
        offset += batch_size
        if progress:
            done = min(offset, total)
            print(f"  {done}/{total}", file=sys.stderr)

    if not dry_run and updated:
        save(data, contacts_path)

    return {
        "updated": updated,
        "unchanged": unchanged,
        "missing_in_yaml": missing,
        "macos_total": total,
    }
