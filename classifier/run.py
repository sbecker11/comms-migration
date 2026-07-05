"""Orchestrates one classification pass over one Gmail account.

For each message in the query window:
  1. Try the rule engine (free, instant).
  2. If unresolved, try the LLM fallback (cheap, only for the unknown tail).
  3. If still unresolved, fall back to `spam_unknown`.
  4. Execute the resolved action (label, and archive if the tier calls for it).

Nothing here talks to job-tracker directly; `recruiter_job` messages are
recognized (so they don't fall through to spam_unknown), labeled, and
archived per `rules/actions.yaml` — except on `recruiting_funnel`, where
`classifier.actions.NEVER_ARCHIVE_CATEGORIES_BY_ACCOUNT` keeps them
label-only, since job-tracker's default query for that account IS scoped
to `in:inbox` (unlike its `personal_hub` query).

Also records empirical dead-rule telemetry every run (`record_rule_telemetry`,
on by default) — see `classifier/rule_telemetry.py` for why this exists
alongside the static checks in `rules_schema_validate.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from classifier import gmail_client, rule_telemetry
from classifier.actions import ActionOutcome, execute_action
from classifier.llm_classify import ClassificationResult, classify_message_safe
from classifier.rules_engine import RulesEngine


@dataclass
class ClassifiedMessage:
    message_id: str
    from_address: str
    subject: str
    category: str
    source: str  # "rules" | "llm" | "fallback"
    confidence: float
    outcome: ActionOutcome | None = None


@dataclass
class RunSummary:
    account: str
    total_messages: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    messages: list[ClassifiedMessage] = field(default_factory=list)
    dead_rule_warnings: list[str] = field(default_factory=list)


def classify_and_act(
    *,
    account: str,
    query: str = gmail_client.DEFAULT_QUERY,
    newer_than_days: int | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    use_llm_fallback: bool = True,
    llm_model: str | None = None,
    rules_engine: RulesEngine | None = None,
    service=None,
    record_rule_telemetry: bool = True,
    rule_stats_path: Path = rule_telemetry.DEFAULT_STATS_PATH,
) -> RunSummary:
    engine = rules_engine or RulesEngine()
    service = service or gmail_client.get_gmail_service(account)

    message_ids = gmail_client.list_message_ids(
        service, query=query, limit=limit, newer_than_days=newer_than_days
    )

    summary = RunSummary(account=account, total_messages=len(message_ids))
    label_cache: dict[str, str] = {}
    hits_per_message: list[list[str]] = []

    for message_id in message_ids:
        raw = gmail_client.fetch_message(service, message_id)
        message_kwargs = dict(
            to_address=raw.to_address,
            cc_address=raw.cc_address,
            subject=raw.subject,
            body=raw.body_plain or raw.snippet,
            date_sent=raw.date_sent,
            date_received=raw.date_received,
        )

        rule_match = engine.classify(raw.from_address, **message_kwargs)
        # Independent of rule_match above: every active rule's verdict on
        # this message, for empirical dead-rule telemetry — see
        # classifier/rule_telemetry.py. Cheap (a few dozen boolean
        # expression evaluations) relative to one Gmail API call/message.
        if record_rule_telemetry:
            hits_per_message.append(engine.all_rule_hits(raw.from_address, **message_kwargs))
        llm_result: ClassificationResult | None = None
        category: str
        source: str
        confidence: float
        default_action: str

        if rule_match is not None:
            category = rule_match.category
            source = "rules"
            confidence = rule_match.confidence
            default_action = rule_match.default_action
        elif use_llm_fallback:
            llm_kwargs = {"model": llm_model} if llm_model else {}
            llm_result = classify_message_safe(
                from_address=raw.from_address,
                subject=raw.subject,
                body=raw.body_plain or raw.snippet,
                **llm_kwargs,
            )
            if llm_result is not None:
                category = llm_result.category
                source = "llm"
                confidence = llm_result.confidence
                default_action = engine.action_for_category(category).get("default_action", "flag")
                summary.llm_calls += 1
                summary.llm_cost_usd += llm_result.cost_usd
            else:
                category, source, confidence = "spam_unknown", "fallback", 0.0
                default_action = engine.action_for_category(category).get("default_action", "quarantine")
        else:
            category, source, confidence = "spam_unknown", "fallback", 0.0
            default_action = engine.action_for_category(category).get("default_action", "quarantine")

        outcome = execute_action(
            service,
            message_id=message_id,
            category=category,
            default_action=default_action,
            account=account,
            dry_run=dry_run,
            label_cache=label_cache,
        )

        summary.by_category[category] = summary.by_category.get(category, 0) + 1
        summary.by_source[source] = summary.by_source.get(source, 0) + 1
        summary.messages.append(
            ClassifiedMessage(
                message_id=message_id,
                from_address=raw.from_address,
                subject=raw.subject,
                category=category,
                source=source,
                confidence=confidence,
                outcome=outcome,
            )
        )

    if record_rule_telemetry and hits_per_message:
        summary.dead_rule_warnings = rule_telemetry.update_and_check(
            rules=engine.rules,
            hits_per_message=hits_per_message,
            stats_path=rule_stats_path,
        )

    return summary
