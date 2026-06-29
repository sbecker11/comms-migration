"""Read/write contacts/Contacts.yaml."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTACTS_PATH = REPO_ROOT / "contacts" / "Contacts.yaml"
_file_lock = threading.Lock()

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


HUB_GROUPS = frozenset({"Professional", "Personal"})


def has_hub_assignment(groups: list[str] | None) -> bool:
    migrated = migrate_groups(groups)
    return any(g in HUB_GROUPS for g in migrated)


def ensure_hub_default(groups: list[str]) -> list[str]:
    if has_hub_assignment(groups):
        return list(groups)
    return [*groups, "Personal"]


def default_unassigned_contacts_to_personal(
    data: dict[str, Any], *, include_deleted: bool = False
) -> int:
    updated = 0
    for contact in data["contacts"]:
        groups = contact.get("groups") or []
        if has_hub_assignment(groups):
            continue
        if not include_deleted and is_deleted_group(groups):
            continue
        update_standard_groups(contact, ["Personal"])
        updated += 1
    return updated


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


def _write_data(data: dict[str, Any], path: Path = DEFAULT_CONTACTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["meta"]["updated_at"] = _utc_now()
    tmp = path.with_name(f".Contacts.{uuid.uuid4().hex}.yaml.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def save(data: dict[str, Any], path: Path = DEFAULT_CONTACTS_PATH) -> None:
    with _file_lock:
        _write_data(data, path)


def update_store(
    mutator: Callable[[dict[str, Any]], None],
    path: Path = DEFAULT_CONTACTS_PATH,
) -> None:
    with _file_lock:
        data = load(path)
        mutator(data)
        _write_data(data, path)


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


def primary_phone(contact: dict[str, Any]) -> str:
    phones = contact.get("phones") or []
    if not phones:
        return ""
    return phones[0].get("value") or ""


def normalize_phone_digits(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    # Treat +1 (617) … and (617) … as the same NANP number.
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def contact_organization_key(contact: dict[str, Any]) -> str:
    return (contact.get("organization") or "").strip().lower()


def organizations_match_for_dedup(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if abs(len(a) - len(b)) > 4:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.92


def dedup_candidate_contacts(
    data: dict[str, Any], contact: dict[str, Any]
) -> list[dict[str, Any]]:
    org = contact_organization_key(contact)
    if not org:
        return []

    candidates = [
        c for c in data["contacts"] if contact_organization_key(c) == org
    ]
    if not is_org_only_contact(contact):
        return candidates

    seen_ids = {c.get("id") for c in candidates}
    for other in data["contacts"]:
        other_id = other.get("id")
        if other_id in seen_ids:
            continue
        other_org = contact_organization_key(other)
        if not other_org or not is_org_only_contact(other):
            continue
        if organizations_match_for_dedup(org, other_org):
            candidates.append(other)
            seen_ids.add(other_id)
    return candidates


_CREDENTIAL_TOKENS = frozenset(
    {
        "md",
        "m.d",
        "do",
        "d.o",
        "phd",
        "ph.d",
        "jr",
        "sr",
        "ii",
        "iii",
        "iv",
        "esq",
    }
)


def _strip_name_credentials(value: str) -> str:
    parts = (value or "").strip().lower().split()
    while parts:
        token = parts[-1].rstrip(".,)")
        normalized = token.replace(".", "")
        if normalized in _CREDENTIAL_TOKENS:
            parts.pop()
        else:
            break
    return " ".join(parts)


_FIRST_NAME_GROUPS = (
    frozenset({"rich", "richard", "rick"}),
    frozenset({"bob", "robert", "rob"}),
    frozenset({"bill", "william", "will"}),
    frozenset({"jim", "james"}),
    frozenset({"mike", "michael"}),
    frozenset({"dan", "daniel"}),
    frozenset({"dave", "david"}),
    frozenset({"steve", "stephen", "steven"}),
    frozenset({"kate", "katherine", "kathy"}),
    frozenset({"liz", "elizabeth", "beth"}),
    frozenset({"chris", "christopher"}),
    frozenset({"matt", "matthew"}),
    frozenset({"tom", "thomas"}),
    frozenset({"ed", "edward", "edwin"}),
    frozenset({"jon", "john", "jonathan"}),
)


def _person_name_parts(contact: dict[str, Any]) -> tuple[str, str]:
    first = _strip_name_credentials(contact.get("first_name") or "")
    last = _strip_name_credentials(contact.get("last_name") or "")
    return first, last


def _first_name_variants(first: str) -> frozenset[str]:
    first = (first or "").strip().lower()
    if not first:
        return frozenset()
    for group in _FIRST_NAME_GROUPS:
        if first in group:
            return group
    return frozenset({first})


def contacts_same_person(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if is_org_only_contact(a) or is_org_only_contact(b):
        return False
    first_a, last_a = _person_name_parts(a)
    first_b, last_b = _person_name_parts(b)
    if not last_a or last_a != last_b:
        return False
    return bool(_first_name_variants(first_a) & _first_name_variants(first_b))


def contact_person_key(contact: dict[str, Any]) -> str:
    first = _strip_name_credentials(contact.get("first_name") or "")
    last = _strip_name_credentials(contact.get("last_name") or "")
    if not first and not last:
        return ""
    return f"{first}|{last}"


def contact_name_key(contact: dict[str, Any]) -> str:
    return contact_person_key(contact)


def contact_email_set(contact: dict[str, Any]) -> set[str]:
    emails: set[str] = set()
    for entry in contact.get("emails") or []:
        value = (entry.get("value") or "").strip().lower()
        if value:
            emails.add(value)
    return emails


def is_org_only_contact(contact: dict[str, Any]) -> bool:
    return not (contact.get("first_name") or "").strip() and not (
        contact.get("last_name") or ""
    ).strip()


def contact_phone_set(contact: dict[str, Any]) -> set[str]:
    phones: set[str] = set()
    for entry in contact.get("phones") or []:
        digits = normalize_phone_digits(entry.get("value") or "")
        if digits:
            phones.add(digits)
    return phones


def contact_dedup_key(contact: dict[str, Any]) -> str | None:
    org = contact_organization_key(contact)
    if not org:
        return None
    if is_org_only_contact(contact):
        return f"{org}|__org_only__"
    phones = contact_phone_set(contact)
    if phones:
        return f"{org}|{'|'.join(sorted(phones))}"
    return None


def _contacts_linked_for_org_dedup(a: dict[str, Any], b: dict[str, Any]) -> bool:
    phones_a = contact_phone_set(a)
    phones_b = contact_phone_set(b)
    if phones_a and phones_b and phones_a & phones_b:
        return True
    if is_org_only_contact(a) and is_org_only_contact(b) and (
        not phones_a or not phones_b
    ):
        return True
    return False


def _is_fully_sparse_person_contact(contact: dict[str, Any]) -> bool:
    return (
        not is_org_only_contact(contact)
        and not contact_organization_key(contact)
        and not contact_phone_set(contact)
        and not contact_email_set(contact)
    )


def _contacts_linked_for_person_cluster(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if not contacts_same_person(a, b):
        return False

    emails_a = contact_email_set(a)
    emails_b = contact_email_set(b)
    if emails_a and emails_b and emails_a & emails_b:
        return True
    phones_a = contact_phone_set(a)
    phones_b = contact_phone_set(b)
    if phones_a and phones_b and phones_a & phones_b:
        return True
    org = contact_organization_key(a)
    if org and org == contact_organization_key(b):
        if (not phones_a and not emails_a) or (not phones_b and not emails_b):
            return True
    if _is_fully_sparse_person_contact(a) and _is_fully_sparse_person_contact(b):
        return True
    return False


def _contacts_linked_for_named_org_dedup(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _contacts_linked_for_person_cluster(a, b)


def _contacts_linked_for_dedup(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if _contacts_linked_for_org_dedup(a, b):
        return True
    return _contacts_linked_for_named_org_dedup(a, b)


def _contacts_linked_for_person_dedup(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _contacts_linked_for_person_cluster(a, b)


def _duplicate_cluster(
    candidates: list[dict[str, Any]],
    seed: dict[str, Any],
    link_fn: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    by_id = {c.get("id"): c for c in candidates}
    seed_id = seed.get("id")
    if not seed_id or seed_id not in by_id:
        return [seed]

    parent = {cid: cid for cid in by_id}

    def find(contact_id: str) -> str:
        while parent[contact_id] != contact_id:
            parent[contact_id] = parent[parent[contact_id]]
            contact_id = parent[contact_id]
        return contact_id

    def union(left_id: str, right_id: str) -> None:
        left_root, right_root = find(left_id), find(right_id)
        if left_root != right_root:
            parent[left_root] = right_root

    ordered = sorted(by_id.values(), key=lambda c: c.get("id", ""))
    for i, left in enumerate(ordered):
        left_id = left.get("id", "")
        for right in ordered[i + 1 :]:
            if link_fn(left, right):
                union(left_id, right.get("id", ""))

    seed_root = find(seed_id)
    return [c for c in ordered if find(c.get("id", "")) == seed_root]


def find_duplicate_contacts(
    data: dict[str, Any], contact: dict[str, Any]
) -> list[dict[str, Any]]:
    org = contact_organization_key(contact)
    person_key = contact_person_key(contact)

    if is_org_only_contact(contact) and org:
        candidates = dedup_candidate_contacts(data, contact)
        return _duplicate_cluster(candidates, contact, _contacts_linked_for_org_dedup)

    if person_key and not is_org_only_contact(contact):
        person_candidates = [
            c
            for c in data["contacts"]
            if contacts_same_person(contact, c) and not is_org_only_contact(c)
        ]
        if org and contact_phone_set(contact):
            org_candidates = dedup_candidate_contacts(data, contact)
            by_id = {c.get("id"): c for c in person_candidates + org_candidates}
            candidates = list(by_id.values())
            return _duplicate_cluster(candidates, contact, _contacts_linked_for_dedup)
        return _duplicate_cluster(
            person_candidates, contact, _contacts_linked_for_person_cluster
        )

    return [contact]


def pick_canonical_contact(contacts: list[dict[str, Any]]) -> dict[str, Any]:
    active = [c for c in contacts if not is_deleted_group(c.get("groups"))]
    pool = active or contacts
    canonical = sorted(pool, key=lambda c: c.get("id", ""))[0]
    if contact_phone_set(canonical):
        return canonical
    with_phone = [c for c in contacts if contact_phone_set(c)]
    if with_phone:
        return sorted(with_phone, key=lambda c: c.get("id", ""))[0]
    return canonical


def list_row_groups(dups: list[dict[str, Any]]) -> list[str]:
    canonical = pick_canonical_contact(dups)
    groups: set[str] = set()
    for dup in dups:
        for group in dup.get("groups") or []:
            migrated = migrate_group_name(group)
            if migrated in STANDARD_GROUPS:
                groups.add(migrated)
    if any(is_deleted_group(dup.get("groups")) for dup in dups):
        groups.add("Is Deleted")
    else:
        groups.discard("Is Deleted")
    for group in canonical.get("groups") or []:
        migrated = migrate_group_name(group)
        if migrated in ("Professional", "Personal"):
            groups.add(migrated)
    return migrate_groups([g for g in groups if g in STANDARD_GROUPS])


def dedupe_contacts_for_list(
    contacts: list[dict[str, Any]],
    *,
    all_contacts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    all_contacts = all_contacts or contacts
    filtered_ids = {c.get("id") for c in contacts}
    seen_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    for contact in contacts:
        cid = contact.get("id", "")
        if cid in seen_ids:
            continue

        org = contact_organization_key(contact)
        phones = contact_phone_set(contact)
        person_key = contact_person_key(contact)
        can_org_dedup = org and is_org_only_contact(contact)
        can_person_dedup = person_key and not is_org_only_contact(contact)
        if can_org_dedup or can_person_dedup:
            full_dups = find_duplicate_contacts({"contacts": all_contacts}, contact)
            for dup in full_dups:
                seen_ids.add(dup.get("id", ""))
            filtered_dups = [d for d in full_dups if d.get("id") in filtered_ids]
            canonical = pick_canonical_contact(full_dups)
            row = dict(canonical)
            row["_dup_count"] = len(full_dups)
            row["_dup_ids"] = [c["id"] for c in full_dups]
            row["groups"] = list_row_groups(filtered_dups)
            rows.append(row)
        else:
            seen_ids.add(cid)
            rows.append(contact)
    rows.sort(
        key=lambda c: (
            (c.get("last_name") or "").lower(),
            (c.get("first_name") or "").lower(),
            (c.get("organization") or "").lower(),
        )
    )
    return rows


def sync_is_deleted_for_duplicates(
    data: dict[str, Any], source_contact: dict[str, Any], mark_deleted: bool
) -> None:
    for dup in find_duplicate_contacts(data, source_contact):
        std = [
            migrate_group_name(g)
            for g in dup.get("groups") or []
            if migrate_group_name(g) in ("Professional", "Personal")
        ]
        if mark_deleted:
            update_standard_groups(dup, std + ["Is Deleted"])
        else:
            update_standard_groups(dup, std)


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
            (c.get("organization") or "").lower(),
        )
    )
    return dedupe_contacts_for_list(result, all_contacts=contacts)


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


def update_standard_groups(contact: dict[str, Any], groups: list[str]) -> None:
    macos_groups = [
        g
        for g in contact.get("groups") or []
        if g not in STANDARD_GROUPS and migrate_group_name(g) not in STANDARD_GROUPS
    ]
    contact["groups"] = migrate_groups(macos_groups + groups)


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
    update_standard_groups(contact, ensure_hub_default(groups))
    sync_linkedin_field(contact)
