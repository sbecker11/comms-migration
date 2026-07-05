from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from classifier.rules_engine import RulesEngine

ACTIONS_YAML = {
    "categories": {
        "active_client": {"default_action": "notify_now", "target_hub": "professional", "human_in_loop": True, "sensitivity": "medium"},
        "personal": {"default_action": "route", "target_hub": "personal", "human_in_loop": False, "sensitivity": "low"},
        "news": {"default_action": "label_archive", "target_hub": "personal", "human_in_loop": False, "sensitivity": "low"},
        "spam_unknown": {"default_action": "quarantine", "target_hub": "n/a", "human_in_loop": False, "sensitivity": "low"},
    }
}

RULES_V2_YAML = {
    "rules": [
        {
            "description": "News (test)",
            "active": True,
            "combinator": "any",
            "expressions": [
                {
                    "field": "from_url_pattern",
                    "comparator": "matches",
                    "value": r"@([\w-]+\.)*nytimes\.com$",
                }
            ],
            "action": {"add_label": "news"},
        }
    ]
}

EMPTY_RULES_V2_YAML = {"rules": []}

SENDERS_YAML = {
    "professional": {"emails": ["client@examplecorp.com"], "domains": ["examplecorp.com"], "phones": []},
    "personal": {"emails": ["friend@example.net"], "domains": [], "phones": []},
    "overrides": [{"match": "special@example.net", "hub": "professional"}],
    "default": "personal",
}


@pytest.fixture
def engine(tmp_path: Path) -> RulesEngine:
    senders_path = tmp_path / "senders.yaml"
    rules_path = tmp_path / "rules.yaml"
    actions_path = tmp_path / "actions.yaml"
    senders_path.write_text(yaml.safe_dump(SENDERS_YAML))
    rules_path.write_text(yaml.safe_dump(RULES_V2_YAML))
    actions_path.write_text(yaml.safe_dump(ACTIONS_YAML))
    return RulesEngine(
        senders_path=senders_path,
        rules_path=rules_path,
        actions_path=actions_path,
    )


def test_known_bulk_domain_resolves_via_rules(engine: RulesEngine) -> None:
    match = engine.classify("digest@nytimes.com")
    assert match is not None
    assert match.category == "news"
    assert match.default_action == "label_archive"
    assert match.matched_on == "rules"


def test_known_professional_contact_resolves_active_client(engine: RulesEngine) -> None:
    match = engine.classify("client@examplecorp.com")
    assert match is not None
    assert match.category == "active_client"
    assert match.default_action == "notify_now"
    assert match.human_in_loop is True


def test_known_professional_domain_resolves_active_client(engine: RulesEngine) -> None:
    match = engine.classify("someone-new@examplecorp.com")
    assert match is not None
    assert match.category == "active_client"


def test_known_personal_contact_resolves_personal(engine: RulesEngine) -> None:
    match = engine.classify("friend@example.net")
    assert match is not None
    assert match.category == "personal"
    assert match.human_in_loop is False


def test_override_beats_domain_default(engine: RulesEngine) -> None:
    match = engine.classify("special@example.net")
    assert match is not None
    assert match.category == "active_client"


def test_unknown_sender_returns_none(engine: RulesEngine) -> None:
    assert engine.classify("nobody@totally-unknown-domain.example") is None


def test_rules_take_priority_over_known_hub(tmp_path: Path) -> None:
    # A sender that is BOTH a known personal contact AND matches a bulk
    # rule should resolve to the more specific bulk category.
    senders_path = tmp_path / "senders.yaml"
    rules_path = tmp_path / "rules.yaml"
    actions_path = tmp_path / "actions.yaml"
    senders_path.write_text(
        yaml.safe_dump(
            {
                "professional": {"emails": [], "domains": [], "phones": []},
                "personal": {"emails": ["digest@nytimes.com"], "domains": [], "phones": []},
                "overrides": [],
                "default": "personal",
            }
        )
    )
    rules_path.write_text(yaml.safe_dump(RULES_V2_YAML))
    actions_path.write_text(yaml.safe_dump(ACTIONS_YAML))
    engine = RulesEngine(
        senders_path=senders_path,
        rules_path=rules_path,
        actions_path=actions_path,
    )
    match = engine.classify("digest@nytimes.com")
    assert match is not None
    assert match.category == "news"


def test_action_for_unknown_category_falls_back_to_spam_unknown(engine: RulesEngine) -> None:
    action = engine.action_for_category("totally-made-up-category")
    assert action["default_action"] == "quarantine"


def test_bulk_sender_subdomain_matches_registered_domain(engine: RulesEngine) -> None:
    # nytimes.com is registered; real digests ship from tracking subdomains.
    match = engine.classify("digest@rs.email.nytimes.com")
    assert match is not None
    assert match.category == "news"


def test_lookalike_domain_does_not_falsely_match(engine: RulesEngine) -> None:
    # "notnytimes.com" must NOT match the registered "nytimes.com" suffix.
    assert engine.classify("spoof@notnytimes.com") is None


def test_real_config_flags_google_security_alert_never_archived() -> None:
    # Regression test for a real 2026-07-04 miss: a genuine Google account
    # security alert was auto-archived under financial_admin by the LLM
    # fallback. Uses the repo's actual rules/*.yaml (not the test fixture)
    # to make sure this specific, high-stakes case is caught by rules alone
    # and never depends on the LLM inferring intent correctly.
    engine = RulesEngine()
    # gmail_client.py parses the raw "From" header via email.utils.parseaddr
    # before this ever reaches RulesEngine, so classify() always sees a bare
    # address like this, never the "Display Name <addr>" form.
    match = engine.classify("no-reply@accounts.google.com")
    assert match is not None
    assert match.category == "security_alert"
    assert match.default_action == "notify_now"
    assert match.human_in_loop is True


def test_subject_based_rule_matches_via_real_config() -> None:
    # Regression test for the new capability rules.yaml adds over the old
    # domain-only category_rules.yaml: matching on Subject content, not
    # just sender domain.
    engine = RulesEngine()
    match = engine.classify(
        "newsletter@some-unrecognized-sender.example",
        subject="There's An AI For That: issue 42",
    )
    assert match is not None
    assert match.category == "ai"


def test_real_config_flags_password_reset_from_any_sender_as_security_alert() -> None:
    # Regression test for a real 2026-07-05 miss on recruiting_funnel: an MIT
    # alumni portal's password-reset/change emails (help@alum.mit.edu — not
    # one of the sender-specific security_alert rules, which only cover
    # Google/Microsoft/Apple) fell through to the LLM and got misclassified
    # as "personal". The generic, sender-agnostic subject-content rule this
    # added must catch this regardless of which site sent it.
    engine = RulesEngine()

    updated = engine.classify("help@alum.mit.edu", subject="Infinite Connection: password updated")
    assert updated is not None
    assert updated.category == "security_alert"
    assert updated.default_action == "notify_now"

    reset = engine.classify(
        "help@alum.mit.edu", subject="Infinite Connection: reset password instructions"
    )
    assert reset is not None
    assert reset.category == "security_alert"

    # And a genuinely unrelated personal subject must NOT be swept in.
    unrelated = engine.classify("friend@example.com", subject="Hey, want to grab lunch?")
    assert unrelated is None


def test_real_config_flags_linkedin_and_ladders_job_alerts_as_recruiter_job_not_social() -> None:
    # Regression test for a real 2026-07-05 miss on recruiting_funnel: LinkedIn
    # Job Alerts/Recommendations mail was shadowed by the generic "Social
    # networks" linkedin.com rule (first-match-wins), and Ladders mail had no
    # rule at all and fell through to the LLM inconsistently. A same-day
    # "job_digest" category was tried to separate these out, then reverted:
    # recruiter_job covers any single-job alert mail, automated or not.
    engine = RulesEngine()

    linkedin_alert = engine.classify(
        "jobalerts-noreply@linkedin.com", subject="Software Engineer - Full-stack at Swiftly, Inc."
    )
    assert linkedin_alert is not None
    assert linkedin_alert.category == "recruiter_job"
    assert linkedin_alert.default_action == "label_archive"

    linkedin_reco = engine.classify(
        "jobs-noreply@linkedin.com", subject="Talkiatry is hiring for a Remote role"
    )
    assert linkedin_reco is not None
    assert linkedin_reco.category == "recruiter_job"

    ladders = engine.classify("jobs@my.theladders.com", subject="Top job opportunities you should see ASAP")
    assert ladders is not None
    assert ladders.category == "recruiter_job"

    # Genuine LinkedIn social notifications (not job-alert senders) must
    # still land in "social", unaffected by the new rule.
    connection_request = engine.classify("messages-noreply@linkedin.com", subject="John Smith wants to connect")
    assert connection_request is not None
    assert connection_request.category == "social"


def test_real_config_flags_additional_political_and_investing_domains_found_2026_07_05() -> None:
    # Regression test for domains added after the 2026-07-05 personal_hub
    # inbox-flood incident's follow-up sender-domain analysis: these were
    # all falling through to the LLM (real $ cost) despite being frequent,
    # unambiguous senders. See rules/rules.yaml's political/investing rules.
    engine = RulesEngine()

    political_senders = [
        "press@win.donaldjtrump.com",
        "news@emails.nrsc.org",
        "team@emails.housegopmajority.com",
        "info@campaigns.rnchq.com",
        "updates@emails.nrccwin.com",
        "campaign@emails.vanorden4congress.com",
        "news@email.thenrcc.org",
    ]
    for sender in political_senders:
        result = engine.classify(sender, subject="test", body="")
        assert result is not None, f"{sender} should have matched a rule"
        assert result.category == "political", f"{sender} -> {result.category}, expected political"

    investing = engine.classify("alerts@seekingalpha.com", subject="test", body="")
    assert investing is not None
    assert investing.category == "investing"


def test_known_hub_domain_also_matches_subdomain(tmp_path: Path) -> None:
    senders_path = tmp_path / "senders.yaml"
    rules_path = tmp_path / "rules.yaml"
    actions_path = tmp_path / "actions.yaml"
    senders_path.write_text(
        yaml.safe_dump(
            {
                "professional": {"emails": [], "domains": ["examplecorp.com"], "phones": []},
                "personal": {"emails": [], "domains": [], "phones": []},
                "overrides": [],
                "default": "personal",
            }
        )
    )
    rules_path.write_text(yaml.safe_dump(EMPTY_RULES_V2_YAML))
    actions_path.write_text(yaml.safe_dump(ACTIONS_YAML))
    engine = RulesEngine(
        senders_path=senders_path,
        rules_path=rules_path,
        actions_path=actions_path,
    )
    match = engine.classify("notifications@mail.examplecorp.com")
    assert match is not None
    assert match.category == "active_client"
