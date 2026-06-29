"""Build rules/senders.yaml from contacts/Contacts.yaml."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from contacts.store import (
    DEFAULT_CONTACTS_PATH,
    filter_contacts,
    is_deleted_group,
    load,
    migrate_groups,
    normalize_phone_digits,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SENDERS_PATH = REPO_ROOT / "rules" / "senders.yaml"

# Consumer mail domains — never emit domain-level rules (use exact email only).
FREEMAIL_DOMAINS = frozenset(
    {
        "126.com",
        "163.com",
        "aol.com",
        "att.net",
        "comcast.net",
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "icloud.com",
        "live.com",
        "mac.com",
        "me.com",
        "msn.com",
        "outlook.com",
        "proton.me",
        "protonmail.com",
        "qq.com",
        "sbcglobal.net",
        "verizon.net",
        "yahoo.com",
        "ymail.com",
    }
)

ALWAYS_PROFESSIONAL_DOMAINS = frozenset({"spexture.com"})


def normalize_phone_e164(value: str) -> str | None:
    digits = normalize_phone_digits(value)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 8:
        return f"+{digits}"
    return None


def normalize_email(value: str) -> str | None:
    email = (value or "").strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        return None
    local, domain = email.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        return None
    return email


def email_domain(email: str) -> str | None:
    _, domain = email.rsplit("@", 1)
    domain = domain.strip().lower()
    if domain and "." in domain:
        return domain
    return None


def hub_for_row(contact: dict[str, Any]) -> str:
    groups = migrate_groups(contact.get("groups") or [])
    if "Professional" in groups:
        return "professional"
    return "personal"


def collect_sender_entries(
    data: dict[str, Any],
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Return hub → {emails|phones|domains} and summary counts."""
    contacts_by_id = {c["id"]: c for c in data["contacts"]}
    hubs: dict[str, dict[str, set[str]]] = {
        "professional": {"emails": set(), "phones": set(), "domains": set()},
        "personal": {"emails": set(), "phones": set(), "domains": set()},
    }
    domain_hubs: dict[str, set[str]] = defaultdict(set)
    row_count = 0
    pro_rows = 0

    for row in filter_contacts(data["contacts"]):
        row_count += 1
        hub = hub_for_row(row)
        if hub == "professional":
            pro_rows += 1

        dup_ids = row.get("_dup_ids") or [row["id"]]
        for contact_id in dup_ids:
            contact = contacts_by_id.get(contact_id)
            if contact is None or is_deleted_group(contact.get("groups")):
                continue

            for entry in contact.get("emails") or []:
                email = normalize_email(entry.get("value") or "")
                if not email:
                    continue
                hubs[hub]["emails"].add(email)
                domain = email_domain(email)
                if domain and domain not in FREEMAIL_DOMAINS:
                    domain_hubs[domain].add(hub)

            for entry in contact.get("phones") or []:
                phone = normalize_phone_e164(entry.get("value") or "")
                if phone:
                    hubs[hub]["phones"].add(phone)

    for domain, assigned in domain_hubs.items():
        if len(assigned) == 1:
            (only_hub,) = assigned
            hubs[only_hub]["domains"].add(domain)

    for domain in ALWAYS_PROFESSIONAL_DOMAINS:
        hubs["professional"]["domains"].add(domain)

    summary = {
        "rows": row_count,
        "professional_rows": pro_rows,
        "personal_rows": row_count - pro_rows,
        "professional_emails": len(hubs["professional"]["emails"]),
        "personal_emails": len(hubs["personal"]["emails"]),
        "professional_phones": len(hubs["professional"]["phones"]),
        "personal_phones": len(hubs["personal"]["phones"]),
        "professional_domains": len(hubs["professional"]["domains"]),
        "personal_domains": len(hubs["personal"]["domains"]),
    }
    return hubs, summary


def build_senders_document(
    data: dict[str, Any],
    *,
    overrides: list[Any] | None = None,
) -> dict[str, Any]:
    hubs, _summary = collect_sender_entries(data)
    return {
        "professional": {
            "domains": sorted(hubs["professional"]["domains"]),
            "emails": sorted(hubs["professional"]["emails"]),
            "phones": sorted(hubs["professional"]["phones"]),
        },
        "personal": {
            "domains": sorted(hubs["personal"]["domains"]),
            "emails": sorted(hubs["personal"]["emails"]),
            "phones": sorted(hubs["personal"]["phones"]),
        },
        "overrides": overrides if overrides is not None else [],
        "default": "personal",
    }


def _load_existing_overrides(path: Path) -> list[Any]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        existing = yaml.safe_load(f) or {}
    overrides = existing.get("overrides")
    if overrides is None:
        return []
    if isinstance(overrides, list):
        return overrides
    return []


def format_senders_yaml(document: dict[str, Any], *, summary: dict[str, int]) -> str:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    header = (
        "# Destination rule (Layer 2) — generated from contacts/Contacts.yaml\n"
        "# Regenerate: python scripts/export_senders.py\n"
        "# Match order: exact email → phone → domain (longest match wins) → default\n"
        "#\n"
        f"# generated_at: {generated_at}\n"
        f"# contacts: {summary['rows']} rows "
        f"({summary['professional_rows']} professional, {summary['personal_rows']} personal)\n"
        f"# professional: {summary['professional_emails']} emails, "
        f"{summary['professional_phones']} phones, "
        f"{summary['professional_domains']} domains\n"
        f"# personal: {summary['personal_emails']} emails, "
        f"{summary['personal_phones']} phones, "
        f"{summary['personal_domains']} domains\n"
        "\n"
    )
    body = yaml.safe_dump(
        document,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    return header + body


def export_senders(
    contacts_path: Path = DEFAULT_CONTACTS_PATH,
    output_path: Path = DEFAULT_SENDERS_PATH,
    *,
    preserve_overrides: bool = True,
) -> dict[str, int]:
    data = load(contacts_path)
    overrides = _load_existing_overrides(output_path) if preserve_overrides else []
    _, summary = collect_sender_entries(data)
    document = build_senders_document(data, overrides=overrides)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        format_senders_yaml(document, summary=summary),
        encoding="utf-8",
    )
    return summary
