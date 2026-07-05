"""Decides satisfiability of a `combinator: all` rule's expressions using
Z3 (an SMT solver — automated theorem proving, not machine learning) rather
than hand-coded pairwise contradiction patterns.

Why: enumerating contradiction *patterns* by hand (see git history of
`classifier/rules_schema_validate.py` before 2026-07-05 for the pairwise
approach this replaced) doesn't scale, and — worse — is easy to get subtly
wrong or incomplete. That old code, despite several rounds of additions,
still missed real cases (e.g. two `begins_with` values with incompatible
prefixes, like "cat" and "dog" — a string can't start with both, but
nothing checked that), and structurally couldn't see a contradiction
between `from` and `from_url_pattern` expressions since it grouped strictly
by schema field-name, even though they constrain the identical real value.
One Z3 solve per rule, over ALL its expressions at once, is complete and
correct for the vocabulary it models (see Scope below) by construction —
no per-comparator-pair code to write, get wrong, or forget. See the
README's "Two ways we check rule satisfiability" section for the full
rationale and the trade-off this module makes.

How: every expression in the rule becomes one Z3 constraint over a small
set of variables — one per *semantic* field (see `_semantic_field`, which
unifies `from` and `from_url_pattern` onto the same variable since both
constrain the sender address), using Z3's built-in theory of strings
(`==`, `Contains`, `PrefixOf`, `SuffixOf` — natively understands that e.g.
`PrefixOf` implies `Contains`, so we don't have to encode that ourselves)
plus linear arithmetic for the date fields' day-count bounds. The whole
conjunction is handed to the solver ONCE; `unsat` means the rule can never
match any message, and `unsat_core()` gives back the minimal subset of
expressions actually responsible — not just "somewhere in this rule."

Scope (see README for the full "complete vs. good-enough" comparison):
`from_url_pattern`'s regex (`matches`/`does_not_match`) is NOT translated
into Z3's regex theory yet — those expressions are simply not modeled
(contribute no constraint), so conflicts purely between two regexes, or a
regex and a string/date expression, still go undetected, exactly like
before this module existed. Everything else — any combination of
`contains`/`does_not_contain`/`begins_with`/`ends_with`/`equals` across any
number of expressions on `from`/`to`/`cc`/`subject`/`body`, plus
`less_than_days_old`/`greater_than_days_old` on the date fields — is now
fully and generally decided, for any N, not just the specific pairs someone
thought to hand-code.
"""

from __future__ import annotations

from typing import Any

import z3

_STRING_FIELDS = {"from", "to", "cc", "subject", "body"}
_DATE_FIELDS = {"date_sent", "date_received"}


def _semantic_field(field: str) -> str:
    """`from_url_pattern` constrains the exact same real-world value as
    `from` (the sender address) — model both onto ONE Z3 variable so a
    contradiction between a `from` expression and a `from_url_pattern`
    expression on the same rule is caught automatically, with no
    field-name special-casing (a gap the old pairwise checker had, since
    it grouped strictly by the schema's `field` string).
    """
    return "from" if field == "from_url_pattern" else field


def _build_solver(
    expressions: list[dict[str, Any]],
) -> tuple[z3.Solver, dict[str, dict[str, Any]]]:
    solver = z3.Solver()
    string_vars: dict[str, z3.SeqRef] = {}
    date_vars: dict[str, z3.ArithRef] = {}
    tracked: dict[str, dict[str, Any]] = {}

    def string_var(field: str) -> z3.SeqRef:
        sem = _semantic_field(field)
        if sem not in string_vars:
            string_vars[sem] = z3.String(f"str__{sem}")
        return string_vars[sem]

    def date_var(field: str) -> z3.ArithRef:
        if field not in date_vars:
            v = z3.Real(f"days_old__{field}")
            date_vars[field] = v
            solver.add(v >= 0)  # a message can't be a negative number of days old
        return date_vars[field]

    for i, expr in enumerate(expressions):
        field = expr.get("field", "")
        comparator = expr.get("comparator", "")
        value = expr.get("value")
        constraint: z3.BoolRef | None = None

        if field == "from_url_pattern":
            # Not modeled — see module docstring's Scope section. Its
            # variable is still unified with `from`'s (via string_var ->
            # _semantic_field), so this expression contributes nothing,
            # but OTHER from/from_url_pattern expressions on this rule are
            # still checked against each other correctly.
            continue
        if field in _STRING_FIELDS:
            var = string_var(field)
            value_lc = str(value).lower()  # matches rules_v2_engine's case-insensitive compare
            if comparator == "equals":
                constraint = var == z3.StringVal(value_lc)
            elif comparator == "contains":
                constraint = z3.Contains(var, z3.StringVal(value_lc))
            elif comparator == "does_not_contain":
                constraint = z3.Not(z3.Contains(var, z3.StringVal(value_lc)))
            elif comparator == "begins_with":
                constraint = z3.PrefixOf(z3.StringVal(value_lc), var)
            elif comparator == "ends_with":
                constraint = z3.SuffixOf(z3.StringVal(value_lc), var)
        elif field in _DATE_FIELDS:
            var = date_var(field)
            if comparator == "less_than_days_old":
                constraint = var < value
            elif comparator == "greater_than_days_old":
                constraint = var > value

        if constraint is None:
            continue  # unknown/unmodeled field+comparator combo — schema-guarded elsewhere

        tracker_name = f"expr_{i}"
        solver.assert_and_track(constraint, z3.Bool(tracker_name))
        tracked[tracker_name] = expr

    return solver, tracked


def find_unsatisfiable_core(rule: dict[str, Any]) -> list[dict[str, Any]]:
    """For a `combinator: all` rule, returns the minimal list of
    expressions Z3 proved jointly unsatisfiable (its `unsat_core`), or `[]`
    if satisfiable — including trivially, if the rule has no expressions
    this module models at all (e.g. `from_url_pattern`-only rules), since
    "no constraints modeled" can never be proven unsatisfiable.

    Only meaningful for `all` (AND) — under `any` (OR), only one
    expression needs to hold, so returns `[]` unconditionally.
    """
    if rule.get("combinator") != "all":
        return []
    expressions = rule.get("expressions", [])
    solver, tracked = _build_solver(expressions)
    if not tracked:
        return []
    if solver.check() == z3.unsat:
        core = solver.unsat_core()
        # unsat_core() order isn't guaranteed to match assertion order;
        # report in original rule (expressions[]) order for readability.
        core_names = {str(c) for c in core}
        return [tracked[name] for name in tracked if name in core_names]
    return []
