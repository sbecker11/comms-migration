"""Tests for the Spam-folder sweep (classifier.run._sweep_spam /
classifier.spam_sweep_state) — see classifier/run.py's module docstring for
the feature's design rationale.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from classifier import run as run_mod
from classifier import spam_sweep_state
from classifier.actions import ActionOutcome
from classifier.gmail_client import RawMessage
from classifier.llm_classify import ClassificationResult
from classifier.rules_engine import RulesEngine


def _raw(mid: str, frm: str = "someone@example.com", subject: str = "Hello") -> RawMessage:
    return RawMessage(
        id=mid,
        thread_id="t1",
        from_address=frm,
        to_address="me@example.com",
        cc_address="",
        subject=subject,
        date_sent="2026-07-21T16:00:00Z",
        date_received="2026-07-21T16:00:00Z",
        snippet="hi",
        body_plain="body text",
        body_html="",
        label_ids=["SPAM"],
    )


def _list_ids_by_query(inbox_ids: list[str], spam_ids: list[str]):
    def _fn(service, *, query, limit=None, newer_than_days=None):
        return list(spam_ids) if query == "in:spam" else list(inbox_ids)

    return _fn


def _base_kwargs(tmp_path: Path, **overrides):
    kwargs = dict(
        account="recruiting_funnel",
        dry_run=False,
        use_llm_fallback=True,
        record_rule_telemetry=False,
        include_spam=True,
        spam_seen_path=tmp_path / "seen.json",
    )
    kwargs.update(overrides)
    return kwargs


def test_spam_sweep_rule_match_rescues(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    # No inbox messages; one spam message that a rule confidently claims.
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1"]))
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda svc, mid: _raw(mid))
    rule_match = SimpleNamespace(category="recruiter_job", confidence=0.95, default_action="label_archive")
    monkeypatch.setattr(engine, "classify", lambda *a, **k: rule_match)
    rescued = []
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: rescued.append(k) or ActionOutcome(
            message_id="s1", category="recruiter_job", label="Category/recruiter_job", archived=True, dry_run=False
        ),
    )

    summary = run_mod.classify_and_act(rules_engine=engine, service=service, **_base_kwargs(tmp_path))

    assert summary.spam_scanned == 1
    assert len(summary.rescued_from_spam) == 1
    assert summary.rescued_from_spam[0].category == "recruiter_job"
    assert rescued[0]["from_spam"] is True


def test_spam_sweep_category_filter_leaves_non_matching_in_spam(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1"]))
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda svc, mid: _raw(mid))
    rule_match = SimpleNamespace(category="political", confidence=0.99, default_action="quarantine")
    monkeypatch.setattr(engine, "classify", lambda *a, **k: rule_match)
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not rescue a filtered-out category")),
    )

    summary = run_mod.classify_and_act(
        rules_engine=engine, service=service, **_base_kwargs(tmp_path, spam_categories={"recruiter_job"})
    )

    assert summary.spam_scanned == 1
    assert summary.rescued_from_spam == []


def test_spam_sweep_llm_below_confidence_stays_in_spam(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1"]))
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda svc, mid: _raw(mid))
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(
        run_mod,
        "classify_message_safe",
        lambda **k: ClassificationResult(
            category="recruiter_job", subcategory=None, confidence=0.5, rationale="x", cost_usd=0.002
        ),
    )
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not rescue below the confidence bar")),
    )

    summary = run_mod.classify_and_act(
        rules_engine=engine, service=service, **_base_kwargs(tmp_path, spam_min_confidence=0.75)
    )

    assert summary.rescued_from_spam == []
    assert summary.llm_calls == 1
    assert summary.llm_cost_usd > 0


def test_spam_sweep_llm_above_confidence_rescues(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1"]))
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda svc, mid: _raw(mid))
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(engine, "action_for_category", lambda cat: {"default_action": "label_archive"})
    monkeypatch.setattr(
        run_mod,
        "classify_message_safe",
        lambda **k: ClassificationResult(
            category="recruiter_job", subcategory=None, confidence=0.98, rationale="x", cost_usd=0.002
        ),
    )
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: ActionOutcome(
            message_id="s1", category="recruiter_job", label="Category/recruiter_job", archived=True, dry_run=False
        ),
    )

    summary = run_mod.classify_and_act(
        rules_engine=engine, service=service, **_base_kwargs(tmp_path, spam_min_confidence=0.75)
    )

    assert len(summary.rescued_from_spam) == 1
    assert summary.rescued_from_spam[0].source == "llm"


def test_spam_sweep_no_llm_fallback_leaves_unmatched_in_spam(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1"]))
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda svc, mid: _raw(mid))
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(
        run_mod,
        "execute_action",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM fallback means no rescue")),
    )

    summary = run_mod.classify_and_act(
        rules_engine=engine, service=service, **_base_kwargs(tmp_path, use_llm_fallback=False)
    )

    assert summary.rescued_from_spam == []
    assert summary.llm_calls == 0


def test_spam_sweep_seen_cache_skips_previously_scanned(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    fetch_calls: list[str] = []
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1", "s2"]))
    monkeypatch.setattr(
        run_mod.gmail_client,
        "fetch_message",
        lambda svc, mid: fetch_calls.append(mid) or _raw(mid),
    )
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(run_mod, "classify_message_safe", lambda **k: None)
    monkeypatch.setattr(
        run_mod, "execute_action", lambda *a, **k: ActionOutcome("x", "x", "x", False, False)
    )

    seen_path = tmp_path / "seen.json"
    run_mod.classify_and_act(rules_engine=engine, service=service, **_base_kwargs(tmp_path, spam_seen_path=seen_path))
    assert sorted(fetch_calls) == ["s1", "s2"]
    assert spam_sweep_state.load_seen("recruiting_funnel", path=seen_path) == {"s1", "s2"}

    # A second sweep, with the same two ids still sitting in Spam, should
    # fetch neither — both were already scanned (and stayed unmatched) last
    # time, and a message's classification can't change on its own.
    fetch_calls.clear()
    summary2 = run_mod.classify_and_act(
        rules_engine=engine, service=service, **_base_kwargs(tmp_path, spam_seen_path=seen_path)
    )
    assert fetch_calls == []
    assert summary2.spam_scanned == 0


def test_spam_sweep_persists_seen_incrementally_survives_mid_sweep_crash(monkeypatch, tmp_path: Path):
    """Regression test for the 2026-07-21 production incident: the original
    implementation only wrote the seen-cache once, after the whole `in:spam`
    loop finished — so a step timeout (which sends SIGTERM straight to this
    process, skipping any Python cleanup code) mid-sweep discarded every
    already-paid-for LLM classification made during that run. Simulates the
    same failure by raising partway through a 3-message sweep (on the 3rd
    message's `fetch_message` call, before it's classified at all) and
    asserts the two messages that finished *before* the crash are still
    recorded on disk, so a retry only ever re-does the one that was actually
    in flight — not all three.
    """
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1", "s2", "s3"]))

    def _fetch_or_crash(svc, mid):
        if mid == "s3":
            raise RuntimeError("simulated abrupt failure mid-sweep")
        return _raw(mid)

    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", _fetch_or_crash)
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(run_mod, "classify_message_safe", lambda **k: None)

    seen_path = tmp_path / "seen.json"
    try:
        run_mod.classify_and_act(rules_engine=engine, service=service, **_base_kwargs(tmp_path, spam_seen_path=seen_path))
        raise AssertionError("expected the simulated crash to propagate")
    except RuntimeError:
        pass

    # s1/s2 finished classifying (both stayed in Spam, no rule/LLM match) and
    # must already be on disk; s3 crashed before it could be marked, so only
    # two of the three should show up here.
    assert spam_sweep_state.load_seen("recruiting_funnel", path=seen_path) == {"s1", "s2"}


def test_spam_sweep_dry_run_does_not_persist_seen_cache(monkeypatch, tmp_path: Path):
    service = SimpleNamespace()
    engine = RulesEngine()
    monkeypatch.setattr(run_mod.gmail_client, "list_message_ids", _list_ids_by_query([], ["s1"]))
    monkeypatch.setattr(run_mod.gmail_client, "fetch_message", lambda svc, mid: _raw(mid))
    monkeypatch.setattr(engine, "classify", lambda *a, **k: None)
    monkeypatch.setattr(run_mod, "classify_message_safe", lambda **k: None)

    seen_path = tmp_path / "seen.json"
    run_mod.classify_and_act(
        rules_engine=engine, service=service, **_base_kwargs(tmp_path, dry_run=True, spam_seen_path=seen_path)
    )
    assert not seen_path.exists()


def test_spam_sweep_state_load_missing_file_returns_empty(tmp_path: Path):
    assert spam_sweep_state.load_seen("recruiting_funnel", path=tmp_path / "nope.json") == set()


def test_spam_sweep_state_mark_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "seen.json"
    spam_sweep_state.mark_seen("recruiting_funnel", ["a", "b"], path=path)
    spam_sweep_state.mark_seen("recruiting_funnel", ["b", "c"], path=path)
    assert spam_sweep_state.load_seen("recruiting_funnel", path=path) == {"a", "b", "c"}


def test_spam_sweep_state_mark_seen_empty_list_is_a_noop(tmp_path: Path):
    path = tmp_path / "seen.json"
    spam_sweep_state.mark_seen("recruiting_funnel", [], path=path)
    assert not path.exists()


def test_spam_sweep_state_load_corrupt_json_returns_empty(tmp_path: Path):
    path = tmp_path / "seen.json"
    path.write_text("not valid json{", encoding="utf-8")
    assert spam_sweep_state.load_seen("recruiting_funnel", path=path) == set()


def test_spam_sweep_state_default_path_is_per_account(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(spam_sweep_state, "STATE_DIR", tmp_path)
    p1 = spam_sweep_state.state_path("recruiting_funnel")
    p2 = spam_sweep_state.state_path("personal_hub")
    assert p1 != p2
    assert p1.name == ".spam_sweep_seen.recruiting_funnel.json"
