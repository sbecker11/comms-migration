#!/usr/bin/env python3
"""Assign Personal to contacts that have neither Professional nor Personal."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contacts.store import (  # noqa: E402
    DEFAULT_CONTACTS_PATH,
    default_unassigned_contacts_to_personal,
    update_store,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Default unassigned contacts to Personal hub"
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_CONTACTS_PATH,
        help=f"Contacts YAML path (default: {DEFAULT_CONTACTS_PATH})",
    )
    parser.add_argument(
        "--include-deleted",
        action="store_true",
        help="Also assign Personal to deleted contacts",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"File not found: {args.input}", file=sys.stderr)
        return 1

    updated = 0

    def mutate(data: dict) -> None:
        nonlocal updated
        updated = default_unassigned_contacts_to_personal(
            data, include_deleted=args.include_deleted
        )

    update_store(mutate, path=args.input)
    print(f"Assigned Personal to {updated} contact(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
