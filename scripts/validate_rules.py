#!/usr/bin/env python3
"""CLI: validate a rules-v2-format YAML file against rules/rules_schema.json,
plus cross-check its categories against rules/actions.yaml.

Examples:
    # Validate the live rules file (default)
    python scripts/validate_rules.py

    # Validate a specific file (e.g. a work-in-progress draft)
    python scripts/validate_rules.py rules/some_draft.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from classifier.rules_schema_validate import validate_rules_file  # noqa: E402

DEFAULT_RULES_PATH = REPO_ROOT / "rules" / "rules.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "rules_path",
        nargs="?",
        default=str(DEFAULT_RULES_PATH),
        help=f"Path to a rules-v2-format YAML file (default: {DEFAULT_RULES_PATH})",
    )
    args = parser.parse_args()

    problems = validate_rules_file(Path(args.rules_path))
    if problems:
        print(f"INVALID: {args.rules_path}")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK: {args.rules_path} is schema-valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
