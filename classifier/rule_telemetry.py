"""Empirical dead-rule detection — complements, not replaces,
`classifier/rules_schema_validate.py`'s static contradiction checks.

Static checks can only flag the specific unsatisfiable patterns someone
thought to encode (see its docstring for the running list: conflicting date
ranges, `equals` vs. `ends_with`, etc.). Arbitrary combinations of
`contains`/`begins_with`/`ends_with`/`equals`/regex expressions are
open-ended — there will always be another shape of impossible rule the
static checker doesn't know about, plus a whole separate failure mode it
can *never* catch: a rule that's logically satisfiable but whose premise
just doesn't hold for any real message (e.g. `body contains "invoice"` when
no actual sender phrases it that way), or one that's always shadowed by an
earlier rule in the list.

This module catches all of those uniformly and empirically instead: track,
per rule description, how many real messages it's been evaluated against
(`classifier/rules_v2_engine.all_rule_hits`, which — unlike the actual
classify-and-act path — checks every active rule against every message,
not just the first match) and how many of those it actually matched. A rule
observed against a healthy sample of real mail that has matched zero times
is almost certainly dead, whatever the underlying reason.

Deliberately advisory, not a load-time gate: a fresh rule with zero matches
so far might just not have seen a matching message *yet*, so this only
warns once a rule has accumulated enough observations to make "hasn't
happened yet" implausible (`MIN_MESSAGES_OBSERVED`).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATS_PATH = REPO_ROOT / "rules" / ".rule_match_stats.json"

# Below this many observed messages, a rule with zero matches is
# unremarkable — a rule for a rare vendor just hasn't had a chance to fire.
MIN_MESSAGES_OBSERVED = 200


@dataclass
class RuleStats:
    messages_observed: int = 0
    match_count: int = 0
    first_seen: str = ""
    last_matched: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_stats(path: Path = DEFAULT_STATS_PATH) -> dict[str, RuleStats]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {desc: RuleStats(**fields) for desc, fields in raw.items()}


def save_stats(stats: dict[str, RuleStats], path: Path = DEFAULT_STATS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({desc: asdict(s) for desc, s in stats.items()}, f, indent=2, sort_keys=True)
        f.write("\n")


def record_batch(
    stats: dict[str, RuleStats],
    *,
    active_descriptions: list[str],
    hits_per_message: list[list[str]],
) -> None:
    """Update `stats` in place for one classification run.

    `active_descriptions` — every currently-`active: true` rule's
    description, i.e. everything that was actually evaluated this run
    (mirrors the current rules.yaml, not whatever's already in `stats`
    from a previous, possibly-since-edited, run).
    `hits_per_message` — one entry per message processed, each the list of
    descriptions `rules_v2_engine.all_rule_hits` returned for it.
    """
    now = _now_iso()
    n = len(hits_per_message)
    match_counts: dict[str, int] = {}
    for hits in hits_per_message:
        for desc in hits:
            match_counts[desc] = match_counts.get(desc, 0) + 1

    for desc in active_descriptions:
        s = stats.setdefault(desc, RuleStats(first_seen=now))
        s.messages_observed += n
        hit_count = match_counts.get(desc, 0)
        if hit_count:
            s.match_count += hit_count
            s.last_matched = now


def prune_removed_rules(stats: dict[str, RuleStats], known_descriptions: set[str]) -> None:
    """Drop stats entries for rules no longer in rules.yaml at all (active
    or inactive) — otherwise renamed/deleted rules pile up in the stats
    file forever.
    """
    for desc in [d for d in stats if d not in known_descriptions]:
        del stats[desc]


def find_dead_rules(
    stats: dict[str, RuleStats],
    *,
    active_descriptions: list[str],
    min_messages_observed: int = MIN_MESSAGES_OBSERVED,
) -> list[str]:
    """Human-readable warnings for active rules observed against enough
    real mail (`min_messages_observed`) to have never matched once.
    Advisory — call sites should surface these, not fail on them.
    """
    warnings = []
    for desc in active_descriptions:
        s = stats.get(desc)
        if s is None or s.match_count > 0:
            continue
        if s.messages_observed >= min_messages_observed:
            warnings.append(
                f"rule '{desc}': evaluated against {s.messages_observed} real "
                f"message(s) since {s.first_seen} and matched NONE of them — "
                "likely dead (an unsatisfiable combination of expressions, a "
                "typo, or a premise that just doesn't hold in practice, or "
                "always shadowed by an earlier rule). Worth a look in "
                "rules/rules.yaml."
            )
    return warnings


def update_and_check(
    *,
    rules: list[dict[str, Any]],
    hits_per_message: list[list[str]],
    stats_path: Path = DEFAULT_STATS_PATH,
    min_messages_observed: int = MIN_MESSAGES_OBSERVED,
) -> list[str]:
    """Convenience wrapper: load -> record this batch -> prune -> save ->
    return any new dead-rule warnings. `rules` is the full loaded rule list
    (as returned by `rules_v2_engine.load_rules`), active or not.
    """
    active_descriptions = [r.get("description", "") for r in rules if r.get("active", True)]
    all_descriptions = {r.get("description", "") for r in rules}

    stats = load_stats(stats_path)
    record_batch(stats, active_descriptions=active_descriptions, hits_per_message=hits_per_message)
    prune_removed_rules(stats, all_descriptions)
    save_stats(stats, stats_path)

    return find_dead_rules(stats, active_descriptions=active_descriptions, min_messages_observed=min_messages_observed)
