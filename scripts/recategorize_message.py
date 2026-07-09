#!/usr/bin/env python3
"""CLI: manually move one or more messages to a different `Category/*` label,
applying that category's real policy from `rules/actions.yaml` (archive vs.
stay in inbox) rather than just slapping a label on.

Exists for cases that are deliberately NOT auto-rules — e.g. LinkedIn's
"I've sent you a connection request" notification (2026-07-06): it's from
the same `invitations@linkedin.com` sender as "I want to connect" (which
IS auto-routed to recruiter_job), but covers routine non-recruiter
connections too, so a blanket rule would over-match. This script lets you
review a batch and re-route the ones that are actually recruiting-related,
one Gmail search query at a time, without hand-editing labels in the UI.

What it does, per matched message:
    1. Removes every `Category/*` label currently on the message.
    2. Adds `Category/<to-category>`.
    3. Archives it (removes INBOX) if the new category's `default_action`
       in rules/actions.yaml is an archiving tier — otherwise restores it
       to the inbox (adds INBOX back), since the old category's action may
       have already archived it.

Examples:
    # Preview: LinkedIn connection-request notifications from a specific
    # sender/subject you've identified as actually being recruiter outreach.
    python scripts/recategorize_message.py --account recruiting_funnel \\
        --query 'subject:"I\\'ve sent you a connection request" from:invitations@linkedin.com' \\
        --to-category recruiter_job --dry-run

    # Re-route a single message by id.
    python scripts/recategorize_message.py --account recruiting_funnel \\
        --message-id 18d2f1a2b3c4d5e6 --to-category recruiter_job

    # Actually apply the batch re-route above.
    python scripts/recategorize_message.py --account recruiting_funnel \\
        --query 'subject:"I\\'ve sent you a connection request" from:invitations@linkedin.com' \\
        --to-category recruiter_job
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from classifier import actions, gmail_client  # noqa: E402

DEFAULT_ACTIONS_PATH = REPO_ROOT / "rules" / "actions.yaml"


def _load_categories(actions_path: Path = DEFAULT_ACTIONS_PATH) -> dict:
    with actions_path.open() as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("categories", {})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--account",
        required=True,
        choices=sorted(gmail_client.ACCOUNTS.keys()),
        help="Which registered Gmail account to operate on",
    )
    selector = ap.add_mutually_exclusive_group(required=True)
    selector.add_argument("--query", help="Gmail search query selecting the messages to re-route")
    selector.add_argument("--message-id", help="A single Gmail message id to re-route")
    ap.add_argument(
        "--to-category",
        required=True,
        help="Target category — must be a key in rules/actions.yaml's categories:",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change; make no changes",
    )
    args = ap.parse_args(argv)

    categories = _load_categories()
    if args.to_category not in categories:
        print(f"ERROR: '{args.to_category}' is not a category in {DEFAULT_ACTIONS_PATH}.")
        print(f"Known categories: {', '.join(sorted(categories))}")
        return 1
    default_action = categories[args.to_category]["default_action"]

    service = gmail_client.get_gmail_service(args.account)
    profile = service.users().getProfile(userId="me").execute()
    print(f"Account: {args.account} ({profile.get('emailAddress')})")

    message_ids = [args.message_id] if args.message_id else gmail_client.list_message_ids(service, query=args.query)
    if not message_ids:
        print("No matching messages — nothing to do.")
        return 0

    should_archive = default_action in actions._ARCHIVING_ACTIONS and not actions._never_archive(
        args.to_category, args.account
    )
    new_label = actions.label_name(args.to_category)
    verb = "Would re-route" if args.dry_run else "Re-routing"
    print(
        f"{verb} {len(message_ids)} message(s) to {new_label} "
        f"({'archive' if should_archive else 'keep/restore in inbox'})."
    )

    if args.dry_run:
        for mid in message_ids:
            msg = gmail_client.fetch_message(service, mid)
            print(f"  [{mid}] from={msg.from_address!r} subject={msg.subject!r}")
        print("DRY RUN: no labels changed.")
        return 0

    existing_category_labels = {lbl["name"]: lbl["id"] for lbl in gmail_client.list_category_labels(service)}
    new_label_id = gmail_client.get_or_create_label(service, new_label)

    for mid in message_ids:
        raw = service.users().messages().get(userId="me", id=mid, format="minimal").execute()
        current_label_ids = set(raw.get("labelIds", []))
        remove_ids = [
            lbl_id
            for name, lbl_id in existing_category_labels.items()
            if lbl_id in current_label_ids and name != new_label
        ]
        add_ids = [new_label_id]
        if should_archive:
            remove_ids.append("INBOX")
        else:
            add_ids.append("INBOX")
        gmail_client.batch_modify(service, [mid], add_label_ids=add_ids, remove_label_ids=remove_ids or None)

    print(f"Done: {len(message_ids)} message(s) re-routed to {new_label}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
