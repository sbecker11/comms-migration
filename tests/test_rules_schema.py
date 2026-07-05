"""Tests for classifier/rules_schema_validate.py against the real
rules/rules_schema.json + rules/rules.yaml, plus synthetic bad-input cases
to prove the schema actually rejects what it should.
"""

from __future__ import annotations

from pathlib import Path

from classifier.rules_schema_validate import validate_rules_file

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_RULES_PATH = REPO_ROOT / "rules" / "rules.yaml"


def test_live_rules_file_is_schema_valid() -> None:
    problems = validate_rules_file(LIVE_RULES_PATH)
    assert problems == []


def test_rejects_unknown_comparator_for_date_field(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
rules:
  - description: "bad rule"
    active: true
    combinator: any
    expressions:
      - field: date_sent
        comparator: contains
        value: 5
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(bad)
    assert problems


def test_rejects_invalid_regex_in_from_url_pattern(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        r"""
rules:
  - description: "bad regex"
    active: true
    combinator: any
    expressions:
      - field: from_url_pattern
        comparator: matches
        value: "@([unclosed"
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(bad)
    assert any("not a valid regex" in p for p in problems)


def test_rejects_unknown_field_name(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
rules:
  - description: "bad rule"
    active: true
    combinator: any
    expressions:
      - field: bcc
        comparator: contains
        value: "someone@example.com"
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(bad)
    assert problems


def test_rejects_unknown_category_in_add_label(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        r"""
rules:
  - description: "bad rule"
    active: true
    combinator: any
    expressions:
      - field: from_url_pattern
        comparator: matches
        value: '@example\.com$'
    action:
      add_label: not_a_real_category
"""
    )
    problems = validate_rules_file(bad)
    assert any("not_a_real_category" in p for p in problems)


def test_rejects_duplicate_rule_descriptions(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        r"""
rules:
  - description: "duplicate name"
    active: true
    combinator: any
    expressions:
      - field: from_url_pattern
        comparator: matches
        value: '@example\.com$'
    action:
      add_label: news
  - description: "duplicate name"
    active: true
    combinator: any
    expressions:
      - field: from_url_pattern
        comparator: matches
        value: '@other\.com$'
    action:
      add_label: social
"""
    )
    problems = validate_rules_file(bad)
    assert any("duplicate rule description" in p for p in problems)


def test_rejects_unsatisfiable_date_range_with_all_combinator(tmp_path) -> None:
    # less_than_days_old 7 AND greater_than_days_old 8 can never both be
    # true for any message — the exact case from the 2026-07-05 discussion.
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
rules:
  - description: "impossible date range"
    active: true
    combinator: all
    expressions:
      - field: date_sent
        comparator: less_than_days_old
        value: 7
      - field: date_sent
        comparator: greater_than_days_old
        value: 8
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(bad)
    assert any("impossible" in p for p in problems)


def test_accepts_satisfiable_date_range_with_all_combinator(tmp_path) -> None:
    # less_than_days_old 30 AND greater_than_days_old 7 IS satisfiable
    # (anything 8-29 days old) — must NOT be flagged as a contradiction.
    ok = tmp_path / "ok.yaml"
    ok.write_text(
        """
rules:
  - description: "satisfiable date range"
    active: true
    combinator: all
    expressions:
      - field: date_sent
        comparator: less_than_days_old
        value: 30
      - field: date_sent
        comparator: greater_than_days_old
        value: 7
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(ok)
    assert problems == []


def test_same_conflicting_date_range_is_fine_under_any_combinator(tmp_path) -> None:
    # The identical thresholds from the impossible-range test above are
    # perfectly valid under combinator: any (OR) — only ONE needs to hold.
    ok = tmp_path / "ok.yaml"
    ok.write_text(
        """
rules:
  - description: "either very fresh or quite stale"
    active: true
    combinator: any
    expressions:
      - field: date_sent
        comparator: less_than_days_old
        value: 7
      - field: date_sent
        comparator: greater_than_days_old
        value: 8
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(ok)
    assert problems == []


def test_rejects_conflicting_equals_values_with_all_combinator(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
rules:
  - description: "impossible equals"
    active: true
    combinator: all
    expressions:
      - field: from
        comparator: equals
        value: "a@example.com"
      - field: from
        comparator: equals
        value: "b@example.com"
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(bad)
    assert any("impossible" in p for p in problems)


def test_rejects_contains_and_does_not_contain_same_value_with_all_combinator(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
rules:
  - description: "impossible contains"
    active: true
    combinator: all
    expressions:
      - field: subject
        comparator: contains
        value: "invoice"
      - field: subject
        comparator: does_not_contain
        value: "Invoice"
    action:
      add_label: billing
"""
    )
    problems = validate_rules_file(bad)
    assert any("impossible" in p for p in problems)


def test_rejects_equals_value_that_does_not_end_with_required_suffix(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
rules:
  - description: "impossible equals vs ends_with"
    active: true
    combinator: all
    expressions:
      - field: from
        comparator: equals
        value: "dog"
      - field: from
        comparator: ends_with
        value: "ty"
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(bad)
    assert any("impossible" in p for p in problems)


def test_accepts_equals_value_that_does_satisfy_begins_and_ends_with(tmp_path) -> None:
    ok = tmp_path / "ok.yaml"
    ok.write_text(
        """
rules:
  - description: "consistent equals plus begins/ends_with"
    active: true
    combinator: all
    expressions:
      - field: from
        comparator: equals
        value: "recruiter@example.com"
      - field: from
        comparator: begins_with
        value: "recruiter"
      - field: from
        comparator: ends_with
        value: "example.com"
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(ok)
    assert problems == []


def test_begins_with_and_ends_with_without_equals_is_fine(tmp_path) -> None:
    ok = tmp_path / "ok.yaml"
    ok.write_text(
        """
rules:
  - description: "begins/ends_with alone, no pinned equals"
    active: true
    combinator: all
    expressions:
      - field: subject
        comparator: begins_with
        value: "Re:"
      - field: subject
        comparator: ends_with
        value: "urgent"
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(ok)
    assert problems == []


def test_rejects_does_not_contain_implied_by_begins_with_same_value(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
rules:
  - description: "impossible begins_with vs does_not_contain"
    active: true
    combinator: all
    expressions:
      - field: subject
        comparator: begins_with
        value: "invoice"
      - field: subject
        comparator: does_not_contain
        value: "Invoice"
    action:
      add_label: billing
"""
    )
    problems = validate_rules_file(bad)
    assert any("impossible" in p for p in problems)


def test_missing_required_field_is_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        r"""
rules:
  - description: "missing combinator"
    active: true
    expressions:
      - field: from_url_pattern
        comparator: matches
        value: '@example\.com$'
    action:
      add_label: news
"""
    )
    problems = validate_rules_file(bad)
    assert problems
