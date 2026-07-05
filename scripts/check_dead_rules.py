#!/usr/bin/env python3
"""CLI: report any active rules/rules.yaml rule that's accumulated enough
real-message observations (see classifier/rule_telemetry.py) to have never
matched once — a strong signal it's dead (unsatisfiable, a typo, a premise
that doesn't hold in practice, or always shadowed by an earlier rule).

Reads only the locally accumulated `rules/.rule_match_stats.json` (built up
by `scripts/run_classifier.py` runs) — does not touch Gmail itself, so this
is safe/fast to run anytime, e.g. periodically in CI or cron.

Examples:
    python scripts/check_dead_rules.py
    python scripts/check_dead_rules.py --min-messages 500
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from classifier import rule_telemetry  # noqa: E402
from classifier.rules_v2_engine import DEFAULT_RULES_PATH, load_rules  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    ap.add_argument("--stats", type=Path, default=rule_telemetry.DEFAULT_STATS_PATH)
    ap.add_argument("--min-messages", type=int, default=rule_telemetry.MIN_MESSAGES_OBSERVED)
    args = ap.parse_args(argv)

    rules = load_rules(args.rules)
    active_descriptions = [r.get("description", "") for r in rules if r.get("active", True)]

    if not args.stats.exists():
        print(f"No telemetry recorded yet at {args.stats} — run scripts/run_classifier.py at least once first.")
        return 0

    stats = rule_telemetry.load_stats(args.stats)
    warnings = rule_telemetry.find_dead_rules(
        stats, active_descriptions=active_descriptions, min_messages_observed=args.min_messages
    )

    if not warnings:
        observed = sum(1 for d in active_descriptions if d in stats)
        print(
            f"No likely-dead rules found ({observed}/{len(active_descriptions)} active rules have "
            f"telemetry; threshold: {args.min_messages} observed messages)."
        )
        return 0

    print(f"=== {len(warnings)} POSSIBLY DEAD RULE(S) ===")
    for w in warnings:
        print(f"  - {w}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
