#!/usr/bin/env python3
"""Export contacts/Contacts.yaml hub assignments to rules/senders.yaml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contacts.export_senders import (  # noqa: E402
    DEFAULT_SENDERS_PATH,
    export_senders,
)
from contacts.store import DEFAULT_CONTACTS_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build rules/senders.yaml from contacts/Contacts.yaml"
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_CONTACTS_PATH,
        help=f"Contacts YAML path (default: {DEFAULT_CONTACTS_PATH})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_SENDERS_PATH,
        help=f"Output senders YAML path (default: {DEFAULT_SENDERS_PATH})",
    )
    parser.add_argument(
        "--no-preserve-overrides",
        action="store_true",
        help="Replace overrides section instead of keeping existing entries",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"File not found: {args.input}", file=sys.stderr)
        return 1

    summary = export_senders(
        contacts_path=args.input,
        output_path=args.output,
        preserve_overrides=not args.no_preserve_overrides,
    )
    print(f"Wrote {args.output}")
    print(
        f"  {summary['rows']} contact rows → "
        f"{summary['professional_emails']} pro / {summary['personal_emails']} personal emails, "
        f"{summary['professional_phones']} pro / {summary['personal_phones']} personal phones, "
        f"{summary['professional_domains']} pro / {summary['personal_domains']} personal domains"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
