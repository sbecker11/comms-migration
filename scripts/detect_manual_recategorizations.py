"""CLI: find messages whose CURRENT Gmail `Category/*` label disagrees with
what `rules/rules.yaml` (+ `senders.yaml`) would classify them as today —
i.e. likely manual corrections the user made in the Gmail UI (or, less
often, mail a stale/removed rule used to catch but nothing catches anymore)
— so `rules.yaml` can be updated to match going forward.

Read-only: never modifies Gmail (no labeling/archiving) or rules.yaml
itself; only reports mismatches for a human (or a follow-up edit) to act on.

Scoped to recent mail by default (`--newer-than`, 30 days) rather than the
mailbox's full multi-year Category/* history — a manual re-categorization
is something the user just did, not something to re-derive from years of
legacy-labeled backlog (see run_classifier.py's docstring for the same
reasoning re: `reset_categorization.py`'s ~7,660-message incident).

Usage:
    python scripts/detect_manual_recategorizations.py --account personal_hub
    python scripts/detect_manual_recategorizations.py --account recruiting_funnel --newer-than 14
    python scripts/detect_manual_recategorizations.py --account personal_hub --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from classifier import gmail_client  # noqa: E402
from classifier.rules_engine import RulesEngine  # noqa: E402

LABEL_PREFIX = "Category/"


@dataclass
class Mismatch:
    message_id: str
    from_address: str
    subject: str
    labeled_category: str
    rule_category: str | None  # None = rules+senders.yaml don't resolve this at all today


def find_mismatches(
    service,
    engine: RulesEngine,
    *,
    newer_than_days: int = 7,
    limit_per_label: int | None = 300,
    verbose: bool = True,
) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    labels = gmail_client.list_category_labels(service)
    for label in labels:
        category = label["name"][len(LABEL_PREFIX) :]
        query = f'label:"{label["name"]}" newer_than:{newer_than_days}d'
        message_ids = gmail_client.list_message_ids(service, query=query, limit=limit_per_label)
        if verbose:
            print(f"  {label['name']}: {len(message_ids)} message(s) to check...", file=sys.stderr)
        for i, message_id in enumerate(message_ids):
            if verbose and i and i % 25 == 0:
                print(f"    ...{i}/{len(message_ids)}", file=sys.stderr)
            raw = gmail_client.fetch_message(service, message_id)
            match = engine.classify(
                raw.from_address,
                to_address=raw.to_address,
                cc_address=raw.cc_address,
                subject=raw.subject,
                body=raw.body_plain or raw.snippet,
                date_sent=raw.date_sent,
                date_received=raw.date_received,
            )
            rule_category = match.category if match else None
            if rule_category != category:
                mismatches.append(
                    Mismatch(
                        message_id=message_id,
                        from_address=raw.from_address,
                        subject=raw.subject,
                        labeled_category=category,
                        rule_category=rule_category,
                    )
                )
    return mismatches


def _print_report(mismatches: list[Mismatch]) -> None:
    if not mismatches:
        print("No mismatches found — every recent Category/* label agrees with rules/senders.yaml.")
        return

    by_pair = Counter((m.labeled_category, m.rule_category) for m in mismatches)
    print(f"{len(mismatches)} mismatch(es) found, grouped by (labeled -> rules would say):\n")
    for (labeled, rule_cat), count in sorted(by_pair.items(), key=lambda kv: -kv[1]):
        print(f"  {labeled!r} <- currently rules would say {rule_cat!r} ({count} message(s))")

    print("\nDetail (up to 20 per group shown):")
    seen_per_pair: Counter = Counter()
    for m in mismatches:
        pair = (m.labeled_category, m.rule_category)
        if seen_per_pair[pair] >= 20:
            continue
        seen_per_pair[pair] += 1
        print(f"  [{m.labeled_category} <- {m.rule_category}] {m.from_address}  |  {m.subject[:80]}  ({m.message_id})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True, choices=sorted(gmail_client.ACCOUNTS.keys()))
    ap.add_argument("--newer-than", type=int, default=7, metavar="DAYS")
    ap.add_argument("--limit-per-label", type=int, default=300, help="Cap messages scanned per label")
    ap.add_argument("--credentials", type=str, default=None)
    ap.add_argument("--token", type=str, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    service = gmail_client.get_gmail_service(
        args.account,
        credentials_path=Path(args.credentials) if args.credentials else None,
        token_path=Path(args.token) if args.token else None,
    )
    engine = RulesEngine()
    mismatches = find_mismatches(
        service,
        engine,
        newer_than_days=args.newer_than,
        limit_per_label=args.limit_per_label,
        verbose=not args.json,
    )

    if args.json:
        print(json.dumps([m.__dict__ for m in mismatches], indent=2))
    else:
        _print_report(mismatches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
