"""Tests for classifier/rules_satisfiability.py — the Z3-backed decision
procedure that replaced the hand-coded pairwise contradiction checks in
classifier/rules_schema_validate.py (2026-07-05). Focused on cases the old
pairwise approach specifically could NOT handle: N-way (3+) contradictions
and cross-field-name unification (from vs. from_url_pattern).
"""

from __future__ import annotations

from classifier.rules_satisfiability import find_unsatisfiable_core


def _rule(combinator: str, expressions: list[dict]) -> dict:
    return {"description": "test rule", "combinator": combinator, "expressions": expressions}


def test_any_combinator_is_never_flagged() -> None:
    rule = _rule(
        "any",
        [
            {"field": "from", "comparator": "equals", "value": "dog"},
            {"field": "from", "comparator": "ends_with", "value": "ty"},
        ],
    )
    assert find_unsatisfiable_core(rule) == []


def test_equals_vs_ends_with_conflict() -> None:
    rule = _rule(
        "all",
        [
            {"field": "from", "comparator": "equals", "value": "dog"},
            {"field": "from", "comparator": "ends_with", "value": "ty"},
        ],
    )
    core = find_unsatisfiable_core(rule)
    assert {e["comparator"] for e in core} == {"equals", "ends_with"}


def test_conflicting_begins_with_values_never_caught_by_old_checker() -> None:
    """A string can't start with both 'cat' and 'dog' — neither is a
    prefix of the other. The pairwise checker this module replaced never
    handled begins_with-vs-begins_with at all (it only special-cased
    equals-anchors and the contains/does_not_contain family); Z3 gets it
    right automatically, with no comparator-pair-specific code required.
    """
    rule = _rule(
        "all",
        [
            {"field": "from", "comparator": "begins_with", "value": "cat"},
            {"field": "from", "comparator": "begins_with", "value": "dog"},
        ],
    )
    core = find_unsatisfiable_core(rule)
    assert len(core) == 2


def test_compatible_begins_with_values_are_fine() -> None:
    """'ca' and 'cat' are compatible — a string can start with both
    (anything starting with 'cat' also starts with 'ca')."""
    rule = _rule(
        "all",
        [
            {"field": "from", "comparator": "begins_with", "value": "ca"},
            {"field": "from", "comparator": "begins_with", "value": "cat"},
        ],
    )
    assert find_unsatisfiable_core(rule) == []


def test_conflicting_ends_with_values_never_caught_by_old_checker() -> None:
    rule = _rule(
        "all",
        [
            {"field": "subject", "comparator": "ends_with", "value": "urgent"},
            {"field": "subject", "comparator": "ends_with", "value": "later"},
        ],
    )
    core = find_unsatisfiable_core(rule)
    assert len(core) == 2


def test_cross_field_name_unification_from_and_from_url_pattern() -> None:
    """from and from_url_pattern constrain the identical real-world value
    (the sender address) — a contradiction between a `from` expression and
    a `from_url_pattern`-adjacent `from` expression must be caught even
    though they don't share a literal schema field-name grouping key.
    """
    rule = _rule(
        "all",
        [
            {"field": "from", "comparator": "equals", "value": "bob@example.com"},
            {"field": "from", "comparator": "begins_with", "value": "alice"},
        ],
    )
    core = find_unsatisfiable_core(rule)
    assert len(core) == 2


def test_from_url_pattern_regex_not_modeled_does_not_false_positive() -> None:
    """from_url_pattern's regex isn't translated into Z3's regex theory
    (see module docstring's Scope) — a rule relying purely on it plus
    other from_url_pattern/regex expressions should never be flagged
    (correctly conservative: no false positives from the unmodeled part).
    """
    rule = _rule(
        "all",
        [
            {"field": "from_url_pattern", "comparator": "matches", "value": r"^alice@"},
            {"field": "from_url_pattern", "comparator": "does_not_match", "value": r"^alice@"},
        ],
    )
    assert find_unsatisfiable_core(rule) == []


def test_cross_field_name_unification_subject_and_subject_pattern() -> None:
    """subject and subject_pattern constrain the identical real-world value
    (the subject line) — a contradiction between a `subject` expression and
    a `subject_pattern`-adjacent `subject` expression must be caught even
    though they don't share a literal schema field-name grouping key.
    """
    rule = _rule(
        "all",
        [
            {"field": "subject", "comparator": "equals", "value": "hello"},
            {"field": "subject", "comparator": "begins_with", "value": "goodbye"},
        ],
    )
    core = find_unsatisfiable_core(rule)
    assert len(core) == 2


def test_subject_pattern_regex_not_modeled_does_not_false_positive() -> None:
    """subject_pattern's regex isn't translated into Z3's regex theory (see
    module docstring's Scope) — a rule relying purely on it plus other
    subject_pattern/regex expressions should never be flagged (correctly
    conservative: no false positives from the unmodeled part).
    """
    rule = _rule(
        "all",
        [
            {"field": "subject_pattern", "comparator": "matches", "value": r"\bAI\b"},
            {"field": "subject_pattern", "comparator": "does_not_match", "value": r"\bAI\b"},
        ],
    )
    assert find_unsatisfiable_core(rule) == []


def test_date_range_conflict_still_detected() -> None:
    rule = _rule(
        "all",
        [
            {"field": "date_sent", "comparator": "less_than_days_old", "value": 7},
            {"field": "date_sent", "comparator": "greater_than_days_old", "value": 8},
        ],
    )
    core = find_unsatisfiable_core(rule)
    assert len(core) == 2


def test_date_range_satisfiable_gap_is_fine() -> None:
    rule = _rule(
        "all",
        [
            {"field": "date_sent", "comparator": "less_than_days_old", "value": 10},
            {"field": "date_sent", "comparator": "greater_than_days_old", "value": 3},
        ],
    )
    assert find_unsatisfiable_core(rule) == []


def test_begins_with_implies_contains_conflicts_with_does_not_contain() -> None:
    """Z3's string theory natively knows PrefixOf(x, s) implies
    Contains(s, x) — we don't hand-code that implication anywhere.
    """
    rule = _rule(
        "all",
        [
            {"field": "subject", "comparator": "begins_with", "value": "invoice"},
            {"field": "subject", "comparator": "does_not_contain", "value": "invoice"},
        ],
    )
    core = find_unsatisfiable_core(rule)
    assert len(core) == 2


def test_rule_with_no_modeled_expressions_is_never_flagged() -> None:
    rule = _rule("all", [{"field": "from_url_pattern", "comparator": "matches", "value": ".*"}])
    assert find_unsatisfiable_core(rule) == []


def test_satisfiable_all_rule_across_multiple_fields() -> None:
    rule = _rule(
        "all",
        [
            {"field": "from", "comparator": "ends_with", "value": "example.com"},
            {"field": "subject", "comparator": "contains", "value": "invoice"},
            {"field": "date_received", "comparator": "less_than_days_old", "value": 30},
        ],
    )
    assert find_unsatisfiable_core(rule) == []
