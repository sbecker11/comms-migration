#!/usr/bin/env python3
"""Sync macOS Contacts profile text into contacts/Contacts.yaml notes fields."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contacts.profile_text import sync_profile_notes_to_yaml  # noqa: E402
from contacts.store import DEFAULT_CONTACTS_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pull supplemental profile text from macOS Contacts "
            "(notes, job title, addresses, related names, etc.) "
            "into each contact's notes field in Contacts.yaml"
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_CONTACTS_PATH,
        help=f"Contacts YAML path (default: {DEFAULT_CONTACTS_PATH})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=75,
        help="macOS Contacts read batch size (default: 75)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing Contacts.yaml",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"File not found: {args.input}", file=sys.stderr)
        return 1

    stats = sync_profile_notes_to_yaml(
        args.input,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    action = "Would update" if args.dry_run else "Updated"
    print(
        f"{action} {stats['updated']} contact(s); "
        f"{stats['unchanged']} unchanged; "
        f"{stats['missing_in_yaml']} macOS-only (not in YAML)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
