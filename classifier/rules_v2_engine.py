"""Evaluates the Mail.app-style rule schema (`rules/rules.yaml`,
`rules/rules_schema.json`) against a message.

This is the engine behind the "MacMail rules" redesign of 2026-07-04:
named, toggleable rules with any/all-combined field/comparator/value
expressions, replacing the old flat domain/email dicts that used to live
in `rules/category_rules.yaml` (retired — see git history).

Kept deliberately separate from `classifier/rules_engine.py`, which owns
the surrounding policy (senders.yaml hub lookup, actions.yaml action
resolution, the RuleMatch contract). `RulesEngine` calls into
`match_rules()` here as its first-line matcher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from classifier.rules_schema_validate import DEFAULT_ACTIONS_PATH, DEFAULT_SCHEMA_PATH, validate_rules_file

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES_PATH = REPO_ROOT / "rules" / "rules.yaml"

_STRING_FIELDS = {"from", "to", "cc", "subject", "body"}
_PATTERN_FIELDS = {"from_url_pattern", "subject_pattern"}
_DATE_FIELDS = {"date_sent", "date_received"}

# Which MessageFields attribute each pattern field's regex actually runs
# against. from_url_pattern is named for what it matches (a URL/address-like
# string), not a MessageFields attribute 1:1, so this can't be a simple
# getattr(msg, field) — same reason subject_pattern needs its own entry
# even though its name IS the attribute name.
_PATTERN_FIELD_SOURCE = {
    "from_url_pattern": "from_address",
    "subject_pattern": "subject",
}

# A single canonical datatype for every date this engine touches: an
# ISO-8601 string with an explicit UTC offset (either literal "Z" or
# "+00:00"). `MessageFields.date_sent`/`date_received` are always this —
# never Gmail's raw RFC 2822 "Date" header or an epoch-ms int — so this
# engine has exactly one date format to parse, regardless of source.
# Conversion from Gmail's native formats happens once, at the source
# (`gmail_client.parse_gmail_message`), not scattered across consumers.
Iso8601Utc = str


def parse_iso8601_utc(value: Iso8601Utc) -> datetime | None:
    """Parse an Iso8601Utc string. Returns None (not an exception) for an
    empty/missing value or one that fails to parse — callers treat "can't
    tell how old this is" as "this date expression doesn't match" rather
    than a hard error, since a message legitimately might not have a usable
    date_sent/date_received in every code path.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Not a valid Iso8601Utc value (missing UTC offset) — treat like
        # any other unparseable date rather than silently assuming UTC,
        # since that would mask an upstream bug in whoever built this
        # MessageFields.
        return None
    return parsed.astimezone(timezone.utc)


class RulesFileError(Exception):
    """Raised when a rules-v2 YAML file fails schema/category validation."""


@dataclass
class MessageFields:
    """The subset of a message the v2 rule engine can match against.

    `classifier/run.py` builds this from `gmail_client.RawMessage`; tests
    can construct it directly without touching Gmail at all.
    """

    from_address: str = ""
    to_address: str = ""
    cc_address: str = ""
    subject: str = ""
    body: str = ""
    date_sent: Iso8601Utc = ""
    date_received: Iso8601Utc = ""


def domain_matches(sender_domain: str | None, registered_domain: str) -> bool:
    """Dot-boundary-safe suffix match — see rules/rules.yaml header.

    Public (no leading underscore): also reused by classifier/rules_engine.py
    for its senders.yaml hub-domain lookup, so the same false-positive-safe
    logic applies everywhere a domain gets suffix-matched.
    """
    if not sender_domain:
        return False
    registered_domain = registered_domain.strip().lower()
    return sender_domain == registered_domain or sender_domain.endswith("." + registered_domain)


def load_rules(
    path: Path = DEFAULT_RULES_PATH,
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    actions_path: Path = DEFAULT_ACTIONS_PATH,
) -> list[dict[str, Any]]:
    """Validate then load the rule list. Raises RulesFileError on any problem
    (schema violation, unknown category, duplicate description) instead of
    silently running with a malformed rule set.
    """
    problems = validate_rules_file(path, schema_path=schema_path, actions_path=actions_path)
    if problems:
        joined = "\n".join(f"  - {p}" for p in problems)
        raise RulesFileError(f"{path} failed validation:\n{joined}")
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return doc.get("rules", [])


def _string_field_value(msg: MessageFields, field: str) -> str:
    if field == "from":
        return msg.from_address or ""
    if field == "to":
        return msg.to_address or ""
    if field == "cc":
        return msg.cc_address or ""
    if field == "subject":
        return msg.subject or ""
    if field == "body":
        return msg.body or ""
    raise ValueError(f"not a string field: {field}")  # pragma: no cover — schema-guarded


def _string_compare(comparator: str, actual: str, value: str) -> bool:
    actual_lc, value_lc = actual.lower(), value.lower()
    if comparator == "contains":
        return value_lc in actual_lc
    if comparator == "does_not_contain":
        return value_lc not in actual_lc
    if comparator == "begins_with":
        return actual_lc.startswith(value_lc)
    if comparator == "ends_with":
        return actual_lc.endswith(value_lc)
    if comparator == "equals":
        return actual_lc == value_lc
    raise ValueError(f"unknown string comparator: {comparator}")  # pragma: no cover — schema-guarded


@lru_cache(maxsize=256)
def _compile_pattern(pattern: str) -> re.Pattern[str]:
    # Cached: the same handful of rule patterns get compiled once and
    # reused across every message in a run, not recompiled per message.
    # Invalid patterns are already rejected at load time (see
    # classifier/rules_schema_validate.py), so a re.error here would only
    # happen for a rules list that bypassed load_rules() entirely.
    return re.compile(pattern, re.IGNORECASE)


def _pattern_compare(comparator: str, actual: str, pattern: str) -> bool:
    found = _compile_pattern(pattern).search(actual or "") is not None
    if comparator == "matches":
        return found
    if comparator == "does_not_match":
        return not found
    raise ValueError(f"unknown pattern comparator: {comparator}")  # pragma: no cover — schema-guarded


def _days_old(msg: MessageFields, field: str) -> float | None:
    value = msg.date_received if field == "date_received" else msg.date_sent
    parsed = parse_iso8601_utc(value)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 86400


def _date_compare(comparator: str, days_old: float | None, value: int) -> bool:
    if days_old is None:
        return False
    if comparator == "less_than_days_old":
        return days_old < value
    if comparator == "greater_than_days_old":
        return days_old > value
    raise ValueError(f"unknown date comparator: {comparator}")  # pragma: no cover — schema-guarded


def _expression_matches(expr: dict[str, Any], msg: MessageFields) -> bool:
    field = expr["field"]
    comparator = expr["comparator"]
    value = expr["value"]

    if field in _PATTERN_FIELDS:
        source_attr = _PATTERN_FIELD_SOURCE[field]
        return _pattern_compare(comparator, getattr(msg, source_attr), value)
    if field in _STRING_FIELDS:
        return _string_compare(comparator, _string_field_value(msg, field), value)
    if field in _DATE_FIELDS:
        return _date_compare(comparator, _days_old(msg, field), value)
    raise ValueError(f"unknown field: {field}")  # pragma: no cover — schema-guarded


def _rule_matches(rule: dict[str, Any], msg: MessageFields) -> bool:
    if not rule.get("active", True):
        return False
    expressions = rule.get("expressions", [])
    results = (_expression_matches(expr, msg) for expr in expressions)
    return any(results) if rule.get("combinator") == "any" else all(results)


def match_rules(rules: list[dict[str, Any]], msg: MessageFields) -> str | None:
    """Returns the `add_label` category of the first active matching rule,
    evaluated top-to-bottom, or None if nothing matches (caller should fall
    through to senders.yaml / the LLM).
    """
    for rule in rules:
        if _rule_matches(rule, msg):
            return rule["action"]["add_label"]
    return None


def all_rule_hits(rules: list[dict[str, Any]], msg: MessageFields) -> list[str]:
    """Every ACTIVE rule's `description` whose expressions match `msg` —
    NOT just the first (unlike `match_rules`, which stops at the first
    match since that's what actually determines the action taken).

    Used only for empirical dead-rule telemetry
    (`classifier/rule_telemetry.py`): static contradiction detection
    (`classifier/rules_schema_validate.py`) can only flag patterns it was
    explicitly coded to recognize, so it will always miss some genuinely
    unsatisfiable rule. Evaluating every active rule against every real
    message independent of list order — and tallying which ones *never*
    match across a large sample — catches any dead rule empirically,
    including ones that are unsatisfiable for reasons no one anticipated,
    or that are simply always shadowed by an earlier rule in the list.
    """
    return [rule.get("description", "") for rule in rules if _rule_matches(rule, msg)]
