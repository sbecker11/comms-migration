#!/usr/bin/env python3
"""CLI: classify inbox mail for one mapped Gmail account and (optionally)
label/archive it per rules/actions.yaml.

Defaults to only mail from the last 365 days (`--newer-than`, added 2026-07-05
after a `scripts/reset_categorization.py` run on a mailbox with years of
legacy-labeled backlog flooded the inbox with ~7,660 old messages that had
nothing to do with the run at hand — see the runbook's incident notes).
Pass `--newer-than 0` to process mail of any age.

Examples:
    # Safe first look — nothing is modified, just reports what WOULD happen.
    python scripts/run_classifier.py --account personal_hub --dry-run --limit 25

    # Same, but skip the LLM fallback (rules only, zero API cost).
    python scripts/run_classifier.py --account personal_hub --dry-run --no-llm-fallback --limit 25

    # Actually label + archive per the resolved actions (last 30 days only).
    python scripts/run_classifier.py --account personal_hub --newer-than 30

    # Process mail of any age (disables the default 365-day cutoff).
    python scripts/run_classifier.py --account personal_hub --newer-than 0 --limit 25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from classifier.gmail_client import ACCOUNTS, DEFAULT_QUERY  # noqa: E402
from classifier.llm_classify import DEFAULT_MODEL as DEFAULT_LLM_MODEL  # noqa: E402
from classifier.run import classify_and_act  # noqa: E402


def _print_report(summary) -> None:
    print(f"Account: {summary.account}")
    print(f"Processed {summary.total_messages} message(s).")
    if summary.by_category:
        print("\nBy category:")
        for category, count in sorted(summary.by_category.items(), key=lambda kv: -kv[1]):
            print(f"  {category:<20} {count}")
    if summary.by_source:
        source_str = ", ".join(f"{k}={v}" for k, v in summary.by_source.items())
        print(f"\nResolved via: {source_str}")
    if summary.llm_calls:
        print(f"LLM fallback calls: {summary.llm_calls}  (est. cost: ${summary.llm_cost_usd:.4f})")

    never_archived = [
        m for m in summary.messages if m.outcome is not None and not m.outcome.archived
    ]
    if never_archived:
        print(f"\nLabeled but not archived: {len(never_archived)}")
        for m in never_archived[:15]:
            print(f"  {m.category:<18} {m.subject[:60]!r}  <{m.from_address}>")

    low_confidence = [m for m in summary.messages if m.source == "llm" and m.confidence < 0.6]
    if low_confidence:
        print(f"\n=== LOW CONFIDENCE — worth a manual glance ({len(low_confidence)}) ===")
        for m in low_confidence[:15]:
            print(f"  [{m.confidence:.2f}] {m.category:<18} {m.subject[:60]!r}  <{m.from_address}>")

    if summary.spam_scanned:
        print(f"\nSpam folder scanned: {summary.spam_scanned} message(s) (rules, then high-confidence LLM fallback).")
        if summary.rescued_from_spam:
            print(f"=== RESCUED FROM SPAM ({len(summary.rescued_from_spam)}) — worth a spot-check ===")
            for m in summary.rescued_from_spam:
                print(f"  [{m.source:<5}] {m.category:<18} {m.subject[:60]!r}  <{m.from_address}>")
        else:
            print("Nothing in spam confidently matched (rule or LLM) — left untouched.")

    if summary.dead_rule_warnings:
        print(f"\n=== POSSIBLY DEAD RULES ({len(summary.dead_rule_warnings)}) ===")
        for w in summary.dead_rule_warnings:
            print(f"  - {w}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--account",
        required=True,
        choices=sorted(ACCOUNTS.keys()),
        help="Which registered Gmail account to classify",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen; never label or archive anything",
    )
    ap.add_argument("--limit", type=int, help="Max messages to process")
    ap.add_argument("--query", default=DEFAULT_QUERY, help=f"Gmail search query (default: {DEFAULT_QUERY!r})")
    ap.add_argument(
        "--newer-than",
        type=int,
        default=365,
        metavar="DAYS",
        help="Only classify mail newer than this many days old (default: 365; pass 0 to disable the filter entirely)",
    )
    ap.add_argument("--credentials", type=Path)
    ap.add_argument("--token", type=Path)
    ap.add_argument(
        "--no-llm-fallback",
        action="store_true",
        help="Rules only — never call the LLM for unresolved senders (unresolved -> spam_unknown)",
    )
    ap.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    ap.add_argument(
        "--include-spam",
        action="store_true",
        help="Also sweep the Spam folder: rules first (free), then a high-confidence-only LLM "
        "fallback (see --spam-min-confidence) unless --no-llm-fallback is also set. Rescues any "
        "confident match out of Spam entirely. See classifier/run.py's module docstring for why "
        "this is deliberately more conservative than the normal inbox pass.",
    )
    ap.add_argument(
        "--spam-limit",
        type=int,
        help="Max messages to scan in the Spam sweep (defaults to no limit / --limit's value is NOT reused here)",
    )
    ap.add_argument(
        "--spam-min-confidence",
        type=float,
        default=0.75,
        help="Minimum LLM confidence to rescue a Spam message with no rule match (default: 0.75; ignored for "
        "rule-based matches, which are always rescued)",
    )
    ap.add_argument(
        "--spam-categories",
        nargs="*",
        default=None,
        metavar="CATEGORY",
        help="Restrict Spam-sweep rescues to these categories (e.g. --spam-categories recruiter_job). Default: "
        "rescue on any confident match, regardless of category.",
    )
    ap.add_argument("--json", action="store_true", help="Emit the full summary as JSON instead of a report")
    ap.add_argument(
        "--no-rule-telemetry",
        action="store_true",
        help="Don't record this run's rule hit/miss counts into rules/.rule_match_stats.json "
        "(use for one-off/ad-hoc runs you don't want counted toward dead-rule detection)",
    )
    args = ap.parse_args(argv)

    from classifier import gmail_client

    credentials_path = args.credentials or gmail_client.default_credentials_path(args.account)
    token_path = args.token or gmail_client.default_token_path(args.account)
    service = gmail_client.get_gmail_service(
        args.account, credentials_path=credentials_path, token_path=token_path
    )

    if args.dry_run:
        print("DRY RUN: no labels applied, nothing archived.", file=sys.stderr)

    summary = classify_and_act(
        account=args.account,
        query=args.query,
        newer_than_days=args.newer_than,
        limit=args.limit,
        dry_run=args.dry_run,
        use_llm_fallback=not args.no_llm_fallback,
        llm_model=args.llm_model,
        service=service,
        record_rule_telemetry=not args.no_rule_telemetry,
        include_spam=args.include_spam,
        spam_limit=args.spam_limit,
        spam_min_confidence=args.spam_min_confidence,
        spam_categories=set(args.spam_categories) if args.spam_categories else None,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "account": summary.account,
                    "total_messages": summary.total_messages,
                    "by_category": summary.by_category,
                    "by_source": summary.by_source,
                    "llm_calls": summary.llm_calls,
                    "llm_cost_usd": summary.llm_cost_usd,
                    "dead_rule_warnings": summary.dead_rule_warnings,
                    "spam_scanned": summary.spam_scanned,
                    "rescued_from_spam": [
                        {
                            "message_id": m.message_id,
                            "from": m.from_address,
                            "subject": m.subject,
                            "category": m.category,
                        }
                        for m in summary.rescued_from_spam
                    ],
                    "messages": [
                        {
                            "message_id": m.message_id,
                            "from": m.from_address,
                            "subject": m.subject,
                            "category": m.category,
                            "source": m.source,
                            "confidence": m.confidence,
                            "label": m.outcome.label if m.outcome else None,
                            "archived": m.outcome.archived if m.outcome else None,
                        }
                        for m in summary.messages
                    ],
                },
                indent=2,
            )
        )
    else:
        _print_report(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
