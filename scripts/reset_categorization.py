#!/usr/bin/env python3
"""CLI: undo everything scripts/run_classifier.py has ever applied to one
mapped Gmail account — remove every `Category/*` label from every message
that has one, and restore any archived-by-the-classifier message back to
the inbox (re-add `INBOX`).

There is no other reset/undo path in this codebase (the classifier only
ever adds labels and removes `INBOX`; nothing removes labels or re-adds
`INBOX`), so this exists specifically to get back to a clean slate before
re-running the pipeline from scratch.

Does NOT delete the `Category/*` label objects themselves — only removes
them from messages — so relabeling on the next run reuses the same label
IDs instead of recreating them.

Safety guard (added 2026-07-05 after a real incident): a reset on
personal_hub restored ~7,660 messages to the inbox in one shot, because
those `Category/political`/`Category/church` labels had actually come from
a one-time legacy-label migration (years of archived mail), not from a
recent classifier run — this script can't tell the difference, since it
only sees "message has a Category/* label right now". By default it
refuses to touch more than `--max-messages` messages without `--force`,
so a surprise like that gets a chance to be reviewed (via --dry-run) first
instead of immediately flooding the inbox.

Examples:
    # Safe first look — counts only, nothing is modified.
    python scripts/reset_categorization.py --account personal_hub --dry-run

    # Actually remove every Category/* label and restore INBOX.
    python scripts/reset_categorization.py --account personal_hub

    # Bypass the safety guard for a deliberately large reset.
    python scripts/reset_categorization.py --account personal_hub --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from classifier import gmail_client  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--account",
        required=True,
        choices=sorted(gmail_client.ACCOUNTS.keys()),
        help="Which registered Gmail account to reset",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed/restored; make no changes",
    )
    ap.add_argument(
        "--max-messages",
        type=int,
        default=200,
        help="Refuse to actually reset more than this many messages without --force (default: 200)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Bypass the --max-messages safety guard",
    )
    args = ap.parse_args(argv)

    service = gmail_client.get_gmail_service(args.account)
    profile = service.users().getProfile(userId="me").execute()
    print(f"Account: {args.account} ({profile.get('emailAddress')})")

    category_labels = gmail_client.list_category_labels(service)
    if not category_labels:
        print("No Category/* labels found — nothing to reset.")
        return 0

    # Gather everything first (read-only) so the safety guard below can
    # check the true total before any message is modified.
    per_label_ids = {
        label["name"]: gmail_client.list_message_ids_with_label(service, label["id"])
        for label in sorted(category_labels, key=lambda l: l["name"])
    }
    total_messages = sum(len(ids) for ids in per_label_ids.values())

    verb = "Would remove" if args.dry_run else "Removing"
    for label in sorted(category_labels, key=lambda l: l["name"]):
        print(f"  {verb} {label['name']:<30} from {len(per_label_ids[label['name']])} message(s)")

    action = "Would touch" if args.dry_run else "Touched"
    print(f"\n{action} {total_messages} message(s) total across {len(category_labels)} label(s).")

    if args.dry_run:
        print("DRY RUN: no labels removed, nothing restored to inbox.")
        return 0

    if total_messages > args.max_messages and not args.force:
        print(
            f"\nABORTED: this would touch {total_messages} messages, over the safety "
            f"limit of {args.max_messages}. Re-run with --dry-run to review first, or "
            "--force if this scale is actually intended (e.g. a real prior classifier "
            "run, not an old bulk-labeled backlog)."
        )
        return 1

    for label in sorted(category_labels, key=lambda l: l["name"]):
        message_ids = per_label_ids[label["name"]]
        if message_ids:
            gmail_client.batch_modify(
                service,
                message_ids,
                remove_label_ids=[label["id"]],
                add_label_ids=["INBOX"],
            )

    print("Category/* labels removed and affected messages restored to inbox.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
