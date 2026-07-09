"""Validate a rules-v2-format YAML file (see rules/rules.yaml) against
rules/rules_schema.json, plus cross-checks the JSON Schema can't express:
every rule's `action.add_label` names a real category in
rules/actions.yaml, every `from_url_pattern` expression's `value` is a
compilable regex, and — for `combinator: all` rules — that the expressions
aren't jointly unsatisfiable (e.g. `date_sent less_than_days_old 7` AND
`date_sent greater_than_days_old 8` can never both be true for any
message; decided by `classifier/rules_satisfiability.py`, via Z3 — see
`_find_unsatisfiable_expressions()` and that module's docstring for why).

Used both as a standalone check (`scripts/validate_rules.py`) and as a
startup guard inside `classifier/rules_v2_engine.load_rules()`, so a
malformed, stale, or self-contradictory rules.yaml fails loudly at load
time instead of silently never matching anything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

from classifier import rules_satisfiability

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = REPO_ROOT / "rules" / "rules_schema.json"
DEFAULT_ACTIONS_PATH = REPO_ROOT / "rules" / "actions.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _describe_expr(expr: dict[str, Any]) -> str:
    return f"{expr.get('field')} {expr.get('comparator')} {expr.get('value')!r}"


def _find_unsatisfiable_expressions(rule: dict[str, Any]) -> list[str]:
    """Detect expressions within one `combinator: all` rule that can never
    ALL be true for any single message — i.e. the rule is dead code that
    will never match anything, no matter how it's tuned per-message.

    Only meaningful for `all` (AND): under `any` (OR), only one expression
    needs to hold, so "conflicting" expressions are normal and fine (that's
    the whole point of an any-rule listing alternatives) —
    `rules_satisfiability.find_unsatisfiable_core` already returns `[]`
    unconditionally for `any` rules.

    Delegates the actual decision to `classifier/rules_satisfiability.py`
    (an SMT solve via Z3) rather than hand-coded contradiction patterns —
    see that module's docstring for what is and isn't modeled. The message
    below lists the exact minimal conflicting subset Z3 identified
    (its `unsat_core`), not just "this rule is broken somewhere."
    """
    core = rules_satisfiability.find_unsatisfiable_core(rule)
    if not core:
        return []
    desc = rule.get("description", "")
    parts = " AND ".join(_describe_expr(e) for e in core)
    return [
        f"rule '{desc}': combinator 'all' requires {parts} to all hold at "
        "once — impossible (Z3 proved this exact combination of "
        "expressions jointly unsatisfiable; every other expression in the "
        "rule may be fine)"
    ]


def validate_rules_file(
    rules_path: Path,
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    actions_path: Path = DEFAULT_ACTIONS_PATH,
) -> list[str]:
    """Returns human-readable problem strings; an empty list means valid.

    Checks, in order (stops after schema errors since a malformed rule can
    cascade into confusing follow-on errors otherwise):
      1. Structural/enum validity against rules_schema.json.
      2. Every `action.add_label` is a key in actions.yaml's `categories:`.
      3. No duplicate rule `description` values (each should be a unique,
         human-referenceable name, mirroring Mail.app's rule list).
      4. Every `from_url_pattern`/`subject_pattern` expression's `value`
         compiles as a regex (the schema can only check it's a non-empty
         string, not that `re.compile` accepts it).
      5. No `combinator: all` rule has jointly-unsatisfiable expressions,
         decided via Z3 (see `_find_unsatisfiable_expressions` and
         `classifier/rules_satisfiability.py`) — a rule that can
         structurally never match anything is almost certainly a mistake,
         not intentional dead code.
    """
    rules_doc = _load_yaml(rules_path)
    schema = _load_json(schema_path)

    validator = Draft7Validator(schema)
    problems = [
        f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(rules_doc), key=lambda e: list(e.path))
    ]
    if problems:
        return problems

    known_categories = set((_load_yaml(actions_path).get("categories") or {}).keys())
    descriptions_seen: dict[str, int] = {}
    for i, rule in enumerate(rules_doc.get("rules", [])):
        label = rule.get("action", {}).get("add_label")
        if label not in known_categories:
            problems.append(
                f"rules[{i}] ('{rule.get('description')}'): add_label "
                f"'{label}' is not a category in {actions_path.name}"
            )
        desc = rule.get("description", "")
        descriptions_seen[desc] = descriptions_seen.get(desc, 0) + 1

        for j, expr in enumerate(rule.get("expressions", [])):
            field = expr.get("field")
            if field in ("from_url_pattern", "subject_pattern"):
                try:
                    re.compile(expr.get("value", ""))
                except re.error as exc:
                    problems.append(
                        f"rules[{i}].expressions[{j}] ('{rule.get('description')}'): "
                        f"{field} value is not a valid regex: {exc}"
                    )

        problems.extend(_find_unsatisfiable_expressions(rule))

    problems.extend(
        f"duplicate rule description used {count}x: '{desc}'"
        for desc, count in descriptions_seen.items()
        if count > 1
    )

    return problems
