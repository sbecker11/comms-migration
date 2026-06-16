#!/usr/bin/env python3
"""Initialize contacts/Contacts.yaml from the macOS Contacts database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contacts.extract import extract_all_contacts  # noqa: E402
from contacts.store import DEFAULT_CONTACTS_PATH, load, save  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract macOS Contacts into contacts/Contacts.yaml"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_CONTACTS_PATH,
        help=f"Output YAML path (default: {DEFAULT_CONTACTS_PATH})",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing file: keep edited groups on matching contact IDs",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing file without prompting",
    )
    args = parser.parse_args()

    if args.output.exists() and not args.force and not args.merge:
        print(
            f"{args.output} already exists. Use --force to overwrite or --merge to update.",
            file=sys.stderr,
        )
        return 1

    data = extract_all_contacts(progress=True)

    if args.merge and args.output.exists():
        existing = load(args.output)
        edited = {
            c["id"]: c.get("groups", [])
            for c in existing.get("contacts", [])
            if c.get("groups")
        }
        for contact in data["contacts"]:
            if contact["id"] in edited:
                contact["groups"] = edited[contact["id"]]
        for name in existing.get("meta", {}).get("groups", []):
            if name not in data["meta"]["groups"]:
                data["meta"]["groups"].append(name)

    save(data, args.output)
    print(f"Wrote {len(data['contacts'])} contacts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
