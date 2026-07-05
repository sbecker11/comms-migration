"""Tests for classifier/rules_v2_engine.py — the Mail.app-style rule
evaluator, with a focus on `from_url_pattern` (regex against the full
sender address, added 2026-07-05 to replace the domain-only `from_domain`
field) and the date fields' Iso8601Utc datatype.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from classifier.rules_v2_engine import MessageFields, all_rule_hits, match_rules, parse_iso8601_utc

DOMAIN_SUFFIX_RULE = {
    "description": "News (domain suffix)",
    "active": True,
    "combinator": "any",
    "expressions": [
        {"field": "from_url_pattern", "comparator": "matches", "value": r"@([\w-]+\.)*nytimes\.com$"}
    ],
    "action": {"add_label": "news"},
}


def test_domain_suffix_pattern_matches_exact_domain() -> None:
    category = match_rules([DOMAIN_SUFFIX_RULE], MessageFields(from_address="digest@nytimes.com"))
    assert category == "news"


def test_domain_suffix_pattern_matches_subdomain() -> None:
    category = match_rules(
        [DOMAIN_SUFFIX_RULE], MessageFields(from_address="digest@rs.email.nytimes.com")
    )
    assert category == "news"


def test_domain_suffix_pattern_rejects_lookalike_domain() -> None:
    category = match_rules([DOMAIN_SUFFIX_RULE], MessageFields(from_address="spoof@notnytimes.com"))
    assert category is None


def test_local_part_pattern_not_expressible_with_old_from_domain() -> None:
    # The whole point of moving from_domain -> from_url_pattern: a rule can
    # now target the LOCAL PART of the address (e.g. any "noreply@" sender
    # on a given provider), not just the registered domain.
    rule = {
        "description": "Any noreply@ sender on example.com",
        "active": True,
        "combinator": "any",
        "expressions": [
            {"field": "from_url_pattern", "comparator": "matches", "value": r"^noreply@.*example\.com$"}
        ],
        "action": {"add_label": "vendor_transactional"},
    }
    assert match_rules([rule], MessageFields(from_address="noreply@mail.example.com")) == (
        "vendor_transactional"
    )
    assert match_rules([rule], MessageFields(from_address="billing@mail.example.com")) is None


def test_does_not_match_comparator_negates() -> None:
    rule = {
        "description": "Not from a specific sender",
        "active": True,
        "combinator": "any",
        "expressions": [
            {"field": "from_url_pattern", "comparator": "does_not_match", "value": r"@nytimes\.com$"}
        ],
        "action": {"add_label": "spam_unknown"},
    }
    assert match_rules([rule], MessageFields(from_address="someone@other.com")) == "spam_unknown"
    assert match_rules([rule], MessageFields(from_address="digest@nytimes.com")) is None


def test_pattern_matching_is_case_insensitive() -> None:
    category = match_rules([DOMAIN_SUFFIX_RULE], MessageFields(from_address="Digest@NYTimes.COM"))
    assert category == "news"


def test_inactive_rule_never_matches() -> None:
    inactive_rule = {**DOMAIN_SUFFIX_RULE, "active": False}
    category = match_rules([inactive_rule], MessageFields(from_address="digest@nytimes.com"))
    assert category is None


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_parse_iso8601_utc_accepts_z_and_offset_forms() -> None:
    assert parse_iso8601_utc("2026-07-04T12:00:00Z") is not None
    assert parse_iso8601_utc("2026-07-04T12:00:00+00:00") is not None
    assert parse_iso8601_utc("2026-07-04T08:00:00-04:00") is not None  # non-UTC offset still valid ISO-8601


def test_parse_iso8601_utc_rejects_missing_offset() -> None:
    # No UTC offset at all (naive) is NOT a valid Iso8601Utc value —
    # treated the same as unparseable rather than silently assumed UTC.
    assert parse_iso8601_utc("2026-07-04T12:00:00") is None


def test_parse_iso8601_utc_rejects_empty_and_garbage() -> None:
    assert parse_iso8601_utc("") is None
    assert parse_iso8601_utc("not a date") is None


def test_less_than_days_old_matches_recent_date_received() -> None:
    rule = {
        "description": "Recent mail",
        "active": True,
        "combinator": "any",
        "expressions": [{"field": "date_received", "comparator": "less_than_days_old", "value": 7}],
        "action": {"add_label": "news"},
    }
    recent = _iso(datetime.now(timezone.utc) - timedelta(days=1))
    category = match_rules([rule], MessageFields(from_address="x@example.com", date_received=recent))
    assert category == "news"


def test_less_than_days_old_rejects_old_date_received() -> None:
    rule = {
        "description": "Recent mail",
        "active": True,
        "combinator": "any",
        "expressions": [{"field": "date_received", "comparator": "less_than_days_old", "value": 7}],
        "action": {"add_label": "news"},
    }
    old = _iso(datetime.now(timezone.utc) - timedelta(days=30))
    category = match_rules([rule], MessageFields(from_address="x@example.com", date_received=old))
    assert category is None


def test_greater_than_days_old_matches_old_date_sent() -> None:
    rule = {
        "description": "Stale mail",
        "active": True,
        "combinator": "any",
        "expressions": [{"field": "date_sent", "comparator": "greater_than_days_old", "value": 30}],
        "action": {"add_label": "spam_unknown"},
    }
    old = _iso(datetime.now(timezone.utc) - timedelta(days=90))
    category = match_rules([rule], MessageFields(from_address="x@example.com", date_sent=old))
    assert category == "spam_unknown"


def test_missing_date_never_matches_a_date_expression() -> None:
    rule = {
        "description": "Recent mail",
        "active": True,
        "combinator": "any",
        "expressions": [{"field": "date_received", "comparator": "less_than_days_old", "value": 7}],
        "action": {"add_label": "news"},
    }
    category = match_rules([rule], MessageFields(from_address="x@example.com"))
    assert category is None


def test_first_matching_rule_wins() -> None:
    other_rule = {
        "description": "Catch-all",
        "active": True,
        "combinator": "any",
        "expressions": [{"field": "from_url_pattern", "comparator": "matches", "value": r".*"}],
        "action": {"add_label": "spam_unknown"},
    }
    category = match_rules(
        [DOMAIN_SUFFIX_RULE, other_rule], MessageFields(from_address="digest@nytimes.com")
    )
    assert category == "news"


def test_all_rule_hits_returns_every_matching_rule_not_just_first() -> None:
    other_rule = {
        "description": "Catch-all",
        "active": True,
        "combinator": "any",
        "expressions": [{"field": "from_url_pattern", "comparator": "matches", "value": r".*"}],
        "action": {"add_label": "spam_unknown"},
    }
    hits = all_rule_hits(
        [DOMAIN_SUFFIX_RULE, other_rule], MessageFields(from_address="digest@nytimes.com")
    )
    assert hits == ["News (domain suffix)", "Catch-all"]


def test_all_rule_hits_skips_inactive_rules() -> None:
    inactive_rule = {**DOMAIN_SUFFIX_RULE, "active": False}
    hits = all_rule_hits([inactive_rule], MessageFields(from_address="digest@nytimes.com"))
    assert hits == []


def test_all_rule_hits_returns_empty_list_when_nothing_matches() -> None:
    hits = all_rule_hits([DOMAIN_SUFFIX_RULE], MessageFields(from_address="spoof@notnytimes.com"))
    assert hits == []
