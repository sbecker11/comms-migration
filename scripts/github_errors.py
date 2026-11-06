#!/usr/bin/env python3
"""List open GitHub failures, or mark one repository workflow fixed.

Copies live in var/github-errors/open until the cause is found and fixed.
Marking one fixed moves those copies to var/github-errors/fixed. A later
failure for the same workflow is stored again as a new open error.

    python3 scripts/github_errors.py
    python3 scripts/github_errors.py fixed --repo sbecker11/linkage-engine --workflow verify --note "cause and fix"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from classifier.github_errors import list_open, mark_fixed  # noqa: E402


def _print_open() -> int:
    rows = list_open()
    if not rows:
        print("No open GitHub errors.")
        return 0
    print(f"Open GitHub errors: {len(rows)}")
    for row in rows:
        where = row.get("repo") or "(repo not parsed)"
        workflow = row.get("workflow") or "(workflow not parsed)"
        branch = row.get("branch") or ""
        branch_bit = f" [{branch}]" if branch else ""
        print(f"  {where} — {workflow}{branch_bit}")
        print(f"    {row.get('received_at') or row.get('stored_at') or ''}  {row.get('subject') or ''}")
        print(f"    message {row.get('message_id')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    fixed = sub.add_parser("fixed", help="Record that the cause was found and fixed")
    fixed.add_argument("--repo", required=True, help="owner/name, as in the GitHub subject")
    fixed.add_argument("--workflow", default="", help="Workflow name. Omit to close every open error for the repo.")
    fixed.add_argument("--note", required=True, help="What was wrong and what fixed it")
    args = parser.parse_args(argv)
    if args.command == "fixed":
        moved = mark_fixed(repo=args.repo, workflow=args.workflow, note=args.note)
        if not moved:
            print(f"No open error for {args.repo}" + (f" workflow {args.workflow}" if args.workflow else ""))
            return 1
        print(f"Marked {len(moved)} error(s) fixed.")
        for path in moved:
            print(f"  {path}")
        return 0
    return _print_open()


if __name__ == "__main__":
    raise SystemExit(main())
