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

## Spam-folder sweep (`include_spam`, 2026-07-21)

Gmail's own spam filter occasionally swallows real recruiter mail — verified
live when a CRB Workforce recruiter's job-description email landed in
`shawnbecker.recruiting@gmail.com`'s Spam folder and sat there invisible to
every part of this pipeline, since `gmail_client.DEFAULT_QUERY` is
`in:inbox` and Gmail search excludes Spam/Trash unless asked for explicitly.

`include_spam=True` adds a second pass over `in:spam` (same
`newer_than_days` window). That pass is deliberately more conservative than
the primary one:

- **Rules first (free), same as the primary pass.** A known sender/domain
  rule match rescues immediately.
- **LLM fallback only if `use_llm_fallback` is on, and only rescued above
  `spam_min_confidence` (default 0.75, vs. the primary pass's implicit "any
  confidence" — see llm_classify.py).** This matters in practice, not just
  in theory: the CRB Workforce recruiter email that motivated this feature
  came from a domain with no existing sender rule (a one-off staffing
  agency, not a repeat sender), so a rules-only spam pass — which is what
  the first version of this feature shipped as — would have left it sitting
  in Spam anyway. The LLM classifier is specifically prompted to
  distinguish genuine recruiting outreach from promotional job-alert spam
  by intent, not just keywords, so it's the right tool for exactly this
  case; the raised confidence bar is what keeps a merely-plausible-looking
  promotional email from getting rescued on a shaky call.
- **No `spam_unknown` fallback.** If nothing clears the bar, the message is
  left exactly where Gmail put it — untouched, not re-quarantined, not
  counted as a miss. Spam is the correct resting place for everything that
  doesn't confidently clear it.
- **Anything rescued gets pulled out of Spam entirely** (see
  `actions.execute_action`'s `from_spam` / `gmail_client.rescue_from_spam`),
  regardless of whether its category's `default_action` would normally
  archive or just label — leaving SPAM set would keep it invisible to every
  downstream consumer (job-tracker, this classifier's own next run, you)
  either way.
- **`spam_categories`, if set, restricts which confident matches actually
  get rescued** (e.g. just `{"recruiter_job"}` for the automated hourly
  job) — a confidently-classified `spam_unknown`/`political`/`ai` message
  is still correctly left in Spam; there's no reason to pull it into the
  archive just because the LLM could name what it was.
- **Each message is only ever classified once, full stop** — see
  `spam_sweep_state`'s docstring. A single manual test of this feature
  against ~100 real spam messages made 91 LLM calls (~$0.23); running that
  every hour against a mostly-unchanged backlog forever would be pure
  waste, since re-classifying the same message can never produce a
  different answer.

`RunSummary.rescued_from_spam` lists exactly what got pulled out, so a human
can spot-check the sweep (it runs on real senders you don't fully control,
after all) instead of it silently reshaping the mailbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from classifier import gmail_client, rule_telemetry, spam_sweep_state
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
    # Spam-sweep rescues (see module docstring's "Spam-folder sweep" section)
    # — kept separate from `messages`/`total_messages` so normal-query stats
    # aren't diluted by a pass over a totally different mailbox folder.
    spam_scanned: int = 0
    rescued_from_spam: list[ClassifiedMessage] = field(default_factory=list)


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
    include_spam: bool = False,
    spam_limit: int | None = None,
    spam_min_confidence: float = 0.75,
    spam_categories: set[str] | None = None,
    spam_seen_path: Path | None = None,
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

    if include_spam:
        _sweep_spam(
            engine=engine,
            service=service,
            account=account,
            newer_than_days=newer_than_days,
            limit=spam_limit,
            dry_run=dry_run,
            label_cache=label_cache,
            summary=summary,
            use_llm_fallback=use_llm_fallback,
            llm_model=llm_model,
            min_confidence=spam_min_confidence,
            allowed_categories=spam_categories,
            seen_path=spam_seen_path,
        )

    return summary


def _sweep_spam(
    *,
    engine: RulesEngine,
    service,
    account: str,
    newer_than_days: int | None,
    limit: int | None,
    dry_run: bool,
    label_cache: dict[str, str],
    summary: RunSummary,
    use_llm_fallback: bool,
    llm_model: str | None,
    min_confidence: float,
    allowed_categories: set[str] | None,
    seen_path: Path | None,
) -> None:
    """Rescue pass over `in:spam` — see module docstring's "Spam-folder
    sweep" section for the rules-then-high-confidence-LLM design and why a
    rules-only version wasn't enough to catch the case that motivated this.

    `allowed_categories`, if given, restricts *rescue* to messages resolving
    to one of those categories (typically just `{"recruiter_job"}` for the
    automated hourly sweep) — a confident-but-irrelevant classification
    (`spam_unknown`, `political`, `ai`, ...) is left exactly where Gmail put
    it rather than pulled into the archive too. `None` (the default, used by
    ad-hoc/manual runs) rescues on any confident match, which is what
    verified 99/100 real spam messages as "confidently classifiable as
    something" in practice — mostly correct, but broader than the automated
    job should do unattended every hour.

    `seen_path` (via `spam_sweep_state`) is what actually bounds recurring
    LLM cost — see that module's docstring. Every message id fetched here is
    marked seen the moment its own classification finishes, regardless of
    outcome — not batched up and written once at the end of this whole
    function (that was the original 2026-07-21 shape, and it silently threw
    away an entire run's worth of already-paid-for LLM calls the first time
    this hit the automated job's step timeout mid-sweep: `run_step`'s
    `timeout` sends SIGTERM straight to this process, which does not run
    Python `finally`/cleanup code, so anything not already flushed to disk
    at the moment of the kill is gone. Writing per-message means only the
    one message actually in flight when a kill lands is ever re-done —
    every message finished before that point stays recorded no matter how
    the process ends.
    """
    spam_ids = gmail_client.list_message_ids(
        service, query="in:spam", limit=limit, newer_than_days=newer_than_days
    )
    already_seen = spam_sweep_state.load_seen(account, path=seen_path)
    new_ids = [mid for mid in spam_ids if mid not in already_seen]
    summary.spam_scanned = len(new_ids)

    def _mark_seen(mid: str) -> None:
        if not dry_run:
            spam_sweep_state.mark_seen(account, [mid], path=seen_path)

    for message_id in new_ids:
        raw = gmail_client.fetch_message(service, message_id)
        rule_match = engine.classify(
            raw.from_address,
            to_address=raw.to_address,
            cc_address=raw.cc_address,
            subject=raw.subject,
            body=raw.body_plain or raw.snippet,
            date_sent=raw.date_sent,
            date_received=raw.date_received,
        )

        category: str
        source: str
        confidence: float
        default_action: str

        if rule_match is not None:
            category, source, confidence = rule_match.category, "rules", rule_match.confidence
            default_action = rule_match.default_action
        elif use_llm_fallback:
            llm_kwargs = {"model": llm_model} if llm_model else {}
            llm_result = classify_message_safe(
                from_address=raw.from_address,
                subject=raw.subject,
                body=raw.body_plain or raw.snippet,
                **llm_kwargs,
            )
            summary.llm_calls += 1
            if llm_result is not None:
                summary.llm_cost_usd += llm_result.cost_usd
            if llm_result is None or llm_result.confidence < min_confidence:
                # Below the (deliberately higher than the primary pass's)
                # confidence bar, or the LLM call itself failed — leave it in
                # Spam untouched rather than risk a shaky rescue.
                _mark_seen(message_id)
                continue
            category, source, confidence = llm_result.category, "llm", llm_result.confidence
            default_action = engine.action_for_category(category).get("default_action", "flag")
        else:
            # No rule match and LLM fallback disabled — leave it in Spam.
            # No spam_unknown re-labeling; see module docstring.
            _mark_seen(message_id)
            continue

        if allowed_categories is not None and category not in allowed_categories:
            # Confidently classified, but not a category worth pulling out
            # of Spam for — leave it there (dry_run/no-op either way).
            _mark_seen(message_id)
            continue

        outcome = execute_action(
            service,
            message_id=message_id,
            category=category,
            default_action=default_action,
            account=account,
            dry_run=dry_run,
            label_cache=label_cache,
            from_spam=True,
        )
        rescued = ClassifiedMessage(
            message_id=message_id,
            from_address=raw.from_address,
            subject=raw.subject,
            category=category,
            source=source,
            confidence=confidence,
            outcome=outcome,
        )
        summary.rescued_from_spam.append(rescued)
        _mark_seen(message_id)
