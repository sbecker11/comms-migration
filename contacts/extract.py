"""Extract contacts from the macOS Contacts database via JavaScript for Automation."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from contacts.store import STANDARD_GROUPS, _utc_now, linkedin_from_urls

BATCH_SIZE = 75

JXA_HELPERS = r"""
function cleanLabel(label) {
  if (!label) return "";
  return String(label).replace(/_\$\!<(.+)>!\$_/, "$1");
}

function mapContact(p) {
  const emails = p.emails().map(function(e) {
    return { label: cleanLabel(e.label()), value: e.value() || "" };
  });
  const phones = p.phones().map(function(ph) {
    return { label: cleanLabel(ph.label()), value: ph.value() || "" };
  });
  const urls = p.urls().map(function(u) {
    return { label: cleanLabel(u.label()), value: u.value() || "" };
  });
  return {
    id: p.id(),
    first_name: p.firstName() || "",
    last_name: p.lastName() || "",
    organization: p.organization() || "",
    emails: emails,
    phones: phones,
    urls: urls,
    linkedin: "",
    groups: p.groups().map(function(g) { return g.name(); }),
    notes: p.note() || "",
    source: "macos_contacts"
  };
}
"""


def _run_jxa(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-l", "JavaScript"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Contacts extraction failed.\n"
            f"Grant Terminal/Cursor Contacts access in System Settings → Privacy.\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def fetch_group_names() -> list[str]:
    script = """
    const app = Application("Contacts");
    JSON.stringify(app.groups().map(function(g) { return g.name(); }));
    """
    raw = _run_jxa(script)
    names = json.loads(raw) if raw else []
    merged = list(names)
    for name in STANDARD_GROUPS:
        if name not in merged:
            merged.append(name)
    return merged


def fetch_contact_count() -> int:
    script = "JSON.stringify(Application('Contacts').people().length);"
    return int(_run_jxa(script))


def fetch_contacts_batch(offset: int, limit: int) -> list[dict[str, Any]]:
    script = f"""
    {JXA_HELPERS}
    const app = Application("Contacts");
    const people = app.people().slice({offset}, {offset + limit});
    JSON.stringify(people.map(mapContact));
    """
    raw = _run_jxa(script)
    contacts = json.loads(raw) if raw else []
    for contact in contacts:
        contact["linkedin"] = linkedin_from_urls(contact.get("urls") or [])
    return contacts


def extract_all_contacts(
    progress: bool = True,
    batch_size: int = BATCH_SIZE,
) -> dict[str, Any]:
    total = fetch_contact_count()
    groups = fetch_group_names()
    contacts: list[dict[str, Any]] = []

    if progress:
        print(f"Extracting {total} contacts from macOS Contacts…", file=sys.stderr)

    offset = 0
    while offset < total:
        batch = fetch_contacts_batch(offset, batch_size)
        contacts.extend(batch)
        offset += batch_size
        if progress:
            done = min(offset, total)
            print(f"  {done}/{total}", file=sys.stderr)

    return {
        "meta": {
            "version": 1,
            "updated_at": _utc_now(),
            "groups": groups,
            "source": "macos_contacts",
            "contact_count": len(contacts),
        },
        "contacts": contacts,
    }
