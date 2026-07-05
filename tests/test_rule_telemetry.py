"""Tests for classifier/rule_telemetry.py — empirical dead-rule detection
via per-rule observed/matched message counts, complementing the static
contradiction checks in classifier/rules_schema_validate.py.
"""

from __future__ import annotations

from classifier.rule_telemetry import (
    RuleStats,
    find_dead_rules,
    load_stats,
    prune_removed_rules,
    record_batch,
    save_stats,
    update_and_check,
)


def test_record_batch_increments_messages_observed_for_every_active_rule() -> None:
    stats: dict[str, RuleStats] = {}
    record_batch(
        stats,
        active_descriptions=["Rule A", "Rule B"],
        hits_per_message=[["Rule A"], [], ["Rule A"]],
    )
    assert stats["Rule A"].messages_observed == 3
    assert stats["Rule A"].match_count == 2
    assert stats["Rule B"].messages_observed == 3
    assert stats["Rule B"].match_count == 0
    assert stats["Rule B"].last_matched is None
    assert stats["Rule A"].last_matched is not None


def test_record_batch_accumulates_across_multiple_calls() -> None:
    stats: dict[str, RuleStats] = {}
    record_batch(stats, active_descriptions=["Rule A"], hits_per_message=[["Rule A"], []])
    record_batch(stats, active_descriptions=["Rule A"], hits_per_message=[[], [], []])
    assert stats["Rule A"].messages_observed == 5
    assert stats["Rule A"].match_count == 1


def test_find_dead_rules_flags_zero_matches_above_threshold() -> None:
    stats = {"Dead rule": RuleStats(messages_observed=500, match_count=0, first_seen="2026-01-01")}
    warnings = find_dead_rules(stats, active_descriptions=["Dead rule"], min_messages_observed=200)
    assert len(warnings) == 1
    assert "Dead rule" in warnings[0]
    assert "500" in warnings[0]


def test_find_dead_rules_does_not_flag_below_threshold() -> None:
    stats = {"Quiet rule": RuleStats(messages_observed=50, match_count=0, first_seen="2026-01-01")}
    warnings = find_dead_rules(stats, active_descriptions=["Quiet rule"], min_messages_observed=200)
    assert warnings == []


def test_find_dead_rules_does_not_flag_rules_with_matches() -> None:
    stats = {"Healthy rule": RuleStats(messages_observed=500, match_count=3, first_seen="2026-01-01")}
    warnings = find_dead_rules(stats, active_descriptions=["Healthy rule"], min_messages_observed=200)
    assert warnings == []


def test_find_dead_rules_ignores_rules_with_no_stats_yet() -> None:
    warnings = find_dead_rules({}, active_descriptions=["Brand new rule"], min_messages_observed=200)
    assert warnings == []


def test_prune_removed_rules_drops_unknown_descriptions() -> None:
    stats = {
        "Still here": RuleStats(messages_observed=10, match_count=1, first_seen="2026-01-01"),
        "Deleted from rules.yaml": RuleStats(messages_observed=10, match_count=0, first_seen="2026-01-01"),
    }
    prune_removed_rules(stats, {"Still here"})
    assert set(stats) == {"Still here"}


def test_save_and_load_stats_round_trip(tmp_path) -> None:
    path = tmp_path / "stats.json"
    original = {
        "Rule A": RuleStats(messages_observed=42, match_count=7, first_seen="2026-01-01", last_matched="2026-02-01"),
    }
    save_stats(original, path)
    loaded = load_stats(path)
    assert loaded == original


def test_load_stats_returns_empty_dict_when_file_missing(tmp_path) -> None:
    assert load_stats(tmp_path / "does_not_exist.json") == {}


def test_update_and_check_persists_and_reports_dead_rule(tmp_path) -> None:
    path = tmp_path / "stats.json"
    rules = [
        {"description": "Alive rule", "active": True},
        {"description": "Dead rule", "active": True},
        {"description": "Disabled rule", "active": False},
    ]
    hits_per_message = [["Alive rule"]] * 250 + [[]] * 250  # 500 messages total

    warnings = update_and_check(
        rules=rules, hits_per_message=hits_per_message, stats_path=path, min_messages_observed=200
    )

    assert any("Dead rule" in w for w in warnings)
    assert not any("Alive rule" in w for w in warnings)
    assert not any("Disabled rule" in w for w in warnings)

    persisted = load_stats(path)
    assert persisted["Alive rule"].messages_observed == 500
    assert persisted["Alive rule"].match_count == 250
    assert persisted["Dead rule"].messages_observed == 500
    assert persisted["Dead rule"].match_count == 0
    # Inactive rules aren't evaluated by all_rule_hits, so they're never
    # passed in active_descriptions — but if a description is *also* not
    # in the rules list at all, prune_removed_rules would drop it. Here
    # "Disabled rule" is still a known description (just inactive), so it
    # simply never accrues stats rather than being pruned.
    assert "Disabled rule" not in persisted


def test_update_and_check_prunes_stats_for_rules_removed_from_yaml(tmp_path) -> None:
    path = tmp_path / "stats.json"
    save_stats(
        {"Old removed rule": RuleStats(messages_observed=999, match_count=0, first_seen="2020-01-01")}, path
    )
    rules = [{"description": "Current rule", "active": True}]

    update_and_check(rules=rules, hits_per_message=[["Current rule"]], stats_path=path)

    persisted = load_stats(path)
    assert "Old removed rule" not in persisted
    assert "Current rule" in persisted
