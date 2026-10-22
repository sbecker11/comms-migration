"""Tests for classifier.run.classify_and_act with Gmail/LLM fakes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from classifier import run as run_mod
from classifier.actions import ActionOutcome
from classifier.gmail_client import RawMessage
from classifier.llm_classify import ClassificationResult
from classifier.rules_engine import RulesEngine


def _raw(mid: str = "m1", frm: str = "unknown@example.com") -> RawMessage:
    return RawMessage(
        id=mid,
        thread_id="t1",
        from_address=frm,
        to_address="me@example.com",
        cc_address="",
        subject="Hello",
        date_sent="2026-07-04T16:00:00Z",
        date_received="2026-07-04T16:00:00Z",
        snippet="hi",
        body_plain="body text",
        body_html="",
        label_ids=["INBOX"],
    )


def test_classify_and_act_rules_path(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    # Force a known-domain rule hit if possible; otherwise patch engine.classify
    rule_match = SimpleNamespace(
        category="news",
        confidence=0.95,
        default_action="label",
    )
    monkeypatch.setattr(engine, "classify", lambda *a, **k: rule_match)
    monkeypatch.setattr(engine, "all_rule_hits", lambda *a, **k: ["r1"])
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", lambda *a, **k: ["m1"])
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda *a, **k: _raw())
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: ActionOutcome(
            message_id="m1", category="news", label="Category/news", archived=False, dry_run=True
        ),
    )
    monkeypatch.setattr(
        run_mod.rule_telemetry,
        "update_and_check",
        lambda **k: ["dead:r2"],
    )

    summary = run_mod.classify_and_act(
        account="personal_hub",
        dry_run=True,
        use_llm_fallback=False,
        rules_engine=engine,
        service=service,
        rule_stats_path=tmp_path / "stats.json",
    )
    assert summary.total_messages == 1
    assert summary.by_category["news"] == 1
    assert summary.by_source["rules"] == 1
    assert summary.messages[0].source == "rules"
    assert summary.dead_rule_warnings == ["dead:r2"]


def test_classify_and_act_llm_success(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(engine, "all_rule_hits", lambda *a, **k: [])
    monkeypatch.setattr(engine, "action_for_category", lambda cat: {"default_action": "flag"})
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", lambda *a, **k: ["m1"])
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda *a, **k: _raw())
    monkeypatch.setattr(
        run_mod,
        "classify_message_safe",
        lambda **k: ClassificationResult(
            category="social", subcategory=None, confidence=0.8, rationale="x", cost_usd=0.001
        ),
    )
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: ActionOutcome(
            message_id="m1", category="social", label="Category/social", archived=False, dry_run=True
        ),
    )

    summary = run_mod.classify_and_act(
        account="personal_hub",
        dry_run=True,
        use_llm_fallback=True,
        rules_engine=engine,
        service=service,
        record_rule_telemetry=False,
        rule_stats_path=tmp_path / "stats.json",
    )
    assert summary.llm_calls == 1
    assert summary.by_source["llm"] == 1
    assert summary.llm_cost_usd > 0


def test_classify_and_act_llm_fallback_to_spam(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(engine, "all_rule_hits", lambda *a, **k: [])
    monkeypatch.setattr(engine, "action_for_category", lambda cat: {"default_action": "quarantine"})
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", lambda *a, **k: ["m1"])
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda *a, **k: _raw())
    monkeypatch.setattr(run_mod, "classify_message_safe", lambda **k: None)
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: ActionOutcome(
            message_id="m1",
            category="spam_unknown",
            label="Category/spam_unknown",
            archived=False,
            dry_run=True,
        ),
    )

    summary = run_mod.classify_and_act(
        account="personal_hub",
        dry_run=True,
        use_llm_fallback=True,
        rules_engine=engine,
        service=service,
        record_rule_telemetry=False,
    )
    assert summary.by_source["fallback"] == 1
    assert summary.by_category["spam_unknown"] == 1


def test_classify_and_act_no_llm_fallback(monkeypatch):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(engine, "all_rule_hits", lambda *a, **k: [])
    monkeypatch.setattr(engine, "action_for_category", lambda cat: {"default_action": "quarantine"})
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", lambda *a, **k: ["m1"])
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda *a, **k: _raw())
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: ActionOutcome(
            message_id="m1",
            category="spam_unknown",
            label="Category/spam_unknown",
            archived=False,
            dry_run=True,
        ),
    )

    summary = run_mod.classify_and_act(
        account="personal_hub",
        dry_run=True,
        use_llm_fallback=False,
        rules_engine=engine,
        service=service,
        record_rule_telemetry=False,
    )
    assert summary.by_source["fallback"] == 1


def test_classify_and_act_defers_remaining_on_gmail_quota(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(engine, "all_rule_hits", lambda *a, **k: [])
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", lambda *a, **k: ["m1", "m2"])

    def boom(*a, **k):
        err = RuntimeError(
            "Quota exceeded for quota metric 'Total Query Cost' and limit "
            "'Units per minute per user' ... rateLimitExceeded"
        )
        err.resp = SimpleNamespace(status=403)
        raise err

    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", boom)

    summary = run_mod.classify_and_act(
        account="recruiting_funnel",
        dry_run=True,
        use_llm_fallback=False,
        rules_engine=engine,
        service=service,
        record_rule_telemetry=False,
        rule_stats_path=tmp_path / "stats.json",
    )
    assert summary.deferred_for_quota == 2
    assert summary.messages == []


def test_classify_and_act_defers_remaining_on_gmail_timeout(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(engine, "all_rule_hits", lambda *a, **k: [])
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", lambda *a, **k: ["m1", "m2", "m3"])
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda *a, **k: _raw())
    calls = []

    def flaky(*a, **k):
        calls.append(k["message_id"])
        if len(calls) == 2:
            raise TimeoutError("The read operation timed out")
        return ActionOutcome(
            message_id=k["message_id"],
            category="spam_unknown",
            label="Category/spam_unknown",
            archived=False,
            dry_run=True,
        )

    monkeypatch.setattr(run_mod, "execute_action", flaky)

    summary = run_mod.classify_and_act(
        account="recruiting_funnel",
        dry_run=True,
        use_llm_fallback=False,
        rules_engine=engine,
        service=service,
        record_rule_telemetry=False,
        rule_stats_path=tmp_path / "stats.json",
    )
    assert summary.deferred_for_quota == 2
    assert len(summary.messages) == 1


def test_second_run_reuses_the_llm_verdict_without_a_call(monkeypatch, tmp_path: Path):
    engine = RulesEngine()
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(engine, "all_rule_hits", lambda *a, **k: [])
    monkeypatch.setattr(engine, "action_for_category", lambda cat: {"default_action": "flag"})
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", lambda *a, **k: ["m1"])
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda *a, **k: _raw())
    calls = []

    def _llm(**k):
        calls.append(k)
        return ClassificationResult(category="social", subcategory=None, confidence=0.8, rationale="x", cost_usd=0.002)

    monkeypatch.setattr(run_mod, "classify_message_safe", _llm)
    acted = []
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: acted.append(k["category"])
        or ActionOutcome(message_id="m1", category=k["category"], label="Category/social", archived=False, dry_run=False),
    )
    kwargs = dict(
        account="personal_hub", dry_run=False, use_llm_fallback=True, rules_engine=engine,
        service=SimpleNamespace(), record_rule_telemetry=False, llm_verdicts_path=tmp_path / "verdicts.json",
    )

    first = run_mod.classify_and_act(**kwargs)
    second = run_mod.classify_and_act(**kwargs)

    assert len(calls) == 1
    assert (first.llm_calls, first.llm_cache_hits) == (1, 0)
    assert (second.llm_calls, second.llm_cache_hits, second.llm_cost_usd) == (0, 1, 0.0)
    assert second.messages[0].source == "llm" and second.messages[0].confidence == 0.8
    assert acted == ["social", "social"]
