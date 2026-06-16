"""Read/write contacts/Contacts.yaml."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTACTS_PATH = REPO_ROOT / "contacts" / "Contacts.yaml"

# Always available in the group picker (in addition to macOS-imported groups).
STANDARD_GROUPS = ["Professional", "Personal", "Is Deleted"]
DELETED_GROUP = "Is Deleted"
LINKEDIN_PREFIX = "https://linkedin.com/in/"

LEGACY_GROUP_MAP = {
    "Hub-Professional": "Professional",
    "Hub-Personal": "Personal",
    "is deleted": "Is Deleted",
}


def migrate_group_name(name: str) -> str:
    return LEGACY_GROUP_MAP.get(name, name)


def migrate_groups(groups: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups or []:
        migrated = migrate_group_name(group)
        if migrated not in seen:
            seen.add(migrated)
            out.append(migrated)
    return out


def is_deleted_group(groups: list[str] | None) -> bool:
    return DELETED_GROUP in (groups or []) or "is deleted" in (groups or [])


def normalize_linkedin_input(value: str) -> str:
    stripped = (value or "").strip()
    if not stripped:
        return ""
    bare = stripped.rstrip("/")
    if bare in (LINKEDIN_PREFIX.rstrip("/"), "https://www.linkedin.com/in"):
        return ""
    return stripped


def linkedin_display_value(value: str) -> str:
    return value if (value or "").strip() else LINKEDIN_PREFIX


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_document() -> dict[str, Any]:
    return {
        "meta": {
            "version": 1,
            "updated_at": _utc_now(),
            "groups": list(STANDARD_GROUPS),
        },
        "contacts": [],
    }


def load(path: Path = DEFAULT_CONTACTS_PATH) -> dict[str, Any]:
    if not path.exists():
        return empty_document()
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "meta" not in data:
        data["meta"] = empty_document()["meta"]
    if "contacts" not in data:
        data["contacts"] = []
    groups = migrate_groups(list(data["meta"].get("groups") or []))
    for name in STANDARD_GROUPS:
        if name not in groups:
            groups.append(name)
    data["meta"]["groups"] = groups
    for contact in data["contacts"]:
        contact["groups"] = migrate_groups(contact.get("groups"))
    return data


def save(data: dict[str, Any], path: Path = DEFAULT_CONTACTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["meta"]["updated_at"] = _utc_now()
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    shutil.move(tmp, path)


def find_contact(data: dict[str, Any], contact_id: str) -> dict[str, Any] | None:
    for contact in data["contacts"]:
        if contact.get("id") == contact_id:
            return contact
    return None


def linkedin_from_urls(urls: list[dict[str, str]]) -> str:
    for item in urls:
        value = (item.get("value") or "").lower()
        label = (item.get("label") or "").lower()
        if "linkedin.com" in value or "linkedin" in label:
            return item.get("value") or ""
    return ""


def sync_linkedin_field(contact: dict[str, Any]) -> None:
    """Keep linkedin field and urls list consistent."""
    linkedin = normalize_linkedin_input(contact.get("linkedin") or "")
    urls = list(contact.get("urls") or [])
    urls = [u for u in urls if "linkedin.com" not in (u.get("value") or "").lower()]
    if linkedin:
        urls.insert(0, {"label": "LinkedIn", "value": linkedin})
    contact["urls"] = urls
    contact["linkedin"] = linkedin_from_urls(urls)


def normalize_contact(contact: dict[str, Any]) -> dict[str, Any]:
    contact.setdefault("first_name", "")
    contact.setdefault("last_name", "")
    contact.setdefault("organization", "")
    contact.setdefault("emails", [])
    contact.setdefault("phones", [])
    contact.setdefault("urls", [])
    contact.setdefault("groups", [])
    contact.setdefault("notes", "")
    sync_linkedin_field(contact)
    return contact


def filter_contacts(
    contacts: list[dict[str, Any]],
    *,
    q: str = "",
    group: str = "",
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    q_lower = q.strip().lower()
    result: list[dict[str, Any]] = []
    for contact in contacts:
        groups = contact.get("groups") or []
        is_deleted = is_deleted_group(groups)
        if is_deleted and not include_deleted:
            continue
        if group and group not in groups:
            continue
        if q_lower:
            haystack = " ".join(
                [
                    contact.get("first_name") or "",
                    contact.get("last_name") or "",
                    contact.get("organization") or "",
                    contact.get("notes") or "",
                    " ".join(e.get("value", "") for e in contact.get("emails") or []),
                    " ".join(p.get("value", "") for p in contact.get("phones") or []),
                ]
            ).lower()
            if q_lower not in haystack:
                continue
        result.append(contact)
    result.sort(
        key=lambda c: (
            (c.get("last_name") or "").lower(),
            (c.get("first_name") or "").lower(),
        )
    )
    return result


def paginate(items: list[Any], page: int, per_page: int) -> tuple[list[Any], int]:
    page = max(1, page)
    per_page = max(1, min(per_page, 100))
    total = len(items)
    start = (page - 1) * per_page
    return items[start : start + per_page], total


def new_contact_record() -> dict[str, Any]:
    return {
        "id": f"{uuid.uuid4()}:manual",
        "first_name": "",
        "last_name": "",
        "organization": "",
        "emails": [],
        "phones": [],
        "urls": [],
        "linkedin": "",
        "groups": [],
        "notes": "",
        "source": "manual",
    }


def apply_contact_form(
    contact: dict[str, Any],
    *,
    first_name: str,
    last_name: str,
    organization: str,
    linkedin: str,
    notes: str,
    emails: list[dict[str, str]],
    phones: list[dict[str, str]],
    urls: list[dict[str, str]],
    groups: list[str],
) -> None:
    contact["first_name"] = first_name.strip()
    contact["last_name"] = last_name.strip()
    contact["organization"] = organization.strip()
    contact["linkedin"] = normalize_linkedin_input(linkedin)
    contact["notes"] = notes.strip()
    contact["emails"] = emails
    contact["phones"] = phones
    contact["urls"] = urls
    macos_groups = [
        g
        for g in contact.get("groups") or []
        if g not in STANDARD_GROUPS and migrate_group_name(g) not in STANDARD_GROUPS
    ]
    contact["groups"] = migrate_groups(macos_groups + groups)
    sync_linkedin_field(contact)
