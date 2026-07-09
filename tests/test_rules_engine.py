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


def test_real_config_flags_familysearch_and_myheritage_as_church_2026_07_06() -> None:
    # Regression test: FamilySearch and MyHeritage Discovery are genealogy/
    # family-history services, routed to church (not social/spam_unknown)
    # per explicit user request. See rules/rules.yaml's "Family history"
    # rule under the Church section.
    engine = RulesEngine()

    for sender in [
        "noreply@familysearch.org",
        "updates@discoveries.myheritage.com",
        "no-reply@myheritage.com",
    ]:
        result = engine.classify(sender, subject="test", body="")
        assert result is not None, f"{sender} should have matched a rule"
        assert result.category == "church", f"{sender} -> {result.category}, expected church"


def test_real_config_flags_waystar_keep_receiving_email_as_active_client_2026_07_06() -> None:
    # Regression test: Waystar's Workday-hosted candidate-communications
    # preference email is an active-application signal, routed to
    # active_client rather than falling through to recruiter_job/spam_unknown
    # (myworkday.com is a shared ATS domain used by many employers, so this
    # rule matches the exact sender AND the subject, not the domain alone).
    engine = RulesEngine()

    result = engine.classify(
        "waystar@myworkday.com",
        subject="Keep Receiving Our Email Communications?",
        body="",
    )
    assert result is not None
    assert result.category == "active_client"

    # Same sender, unrelated subject: should NOT match this rule.
    other = engine.classify(
        "waystar@myworkday.com",
        subject="Your application status has changed",
        body="",
    )
    assert other is None or other.category != "active_client"


def test_real_config_flags_xoom_transaction_subjects_as_billing_2026_07_06() -> None:
    # Regression test: these 5 exact Xoom subjects route to billing per user
    # request. Xoom's "Action Needed - ... Has Been Cancelled" subject is
    # deliberately NOT covered here (left to the LLM fallback, unchanged).
    engine = RulesEngine()

    billing_subjects = [
        "Update on Transaction XABC123",
        "Transaction on hold",
        "Xoom transaction receipt",
        "Here's your receipt Transaction 12345",
        "Welcome to Xoom!",
    ]
    for subject in billing_subjects:
        result = engine.classify("no-reply@xoom.com", subject=subject, body="")
        assert result is not None, f"{subject!r} should have matched a rule"
        assert result.category == "billing", f"{subject!r} -> {result.category}, expected billing"

    # Same sender, a subject NOT in the requested list: must not match these
    # new rules (whatever it resolves to is out of scope for this test).
    cancelled = engine.classify(
        "no-reply@xoom.com", subject="Action Needed - Your Transaction XAHAQC3Q Has Been Cancelled", body=""
    )
    assert cancelled is None or cancelled.category != "billing"

    # Same subject phrasing, unrelated sender: should NOT match (sender-scoped).
    other_sender = engine.classify("billing@somecompany.com", subject="Transaction on hold", body="")
    assert other_sender is None or other_sender.category != "billing"


def test_real_config_flags_medical_appointment_platforms_as_medical_2026_07_06() -> None:
    # Regression test for the new "medical" category (2026-07-06): known
    # practice-management/reminder platforms real medical/dental offices in
    # this mailbox use, scoped by sender domain. Broadened later the same
    # day to match ANY message from these domains (not just subject
    # "Appointment") — see test_real_config_flags_dry_creek_therapy_and_
    # canyon_crest_dental_as_medical_2026_07_06 for the non-"Appointment"
    # cases (receipts, announcements) that motivated dropping that gate.
    engine = RulesEngine()

    medical_senders = [
        "noreply@advancedmd.com",
        "thomas_d_myers_md_aka_riverwoods.sr@remindmemd.com",
        "donotreply@promptlybyfph.com",
        "automated@prompthealth.com",
        "info@mycanyoncrestdental.com",
    ]
    for sender in medical_senders:
        result = engine.classify(sender, subject="Upcoming Appointment", body="")
        assert result is not None, f"{sender} should have matched a rule"
        assert result.category == "medical", f"{sender} -> {result.category}, expected medical"

    # Same domain, subject without "Appointment": these are single-purpose
    # medical platforms, so this now correctly still matches (broadened
    # 2026-07-06 — see module docstring above).
    non_appointment = engine.classify("noreply@advancedmd.com", subject="Billing statement ready", body="")
    assert non_appointment is not None
    assert non_appointment.category == "medical"

    # An unrelated sender using "Appointment" in the subject must still NOT
    # match without also being one of the known dedicated domains, or the
    # separate body-based pharmacy rule below.
    spam_lookalike = engine.classify(
        "noreply@americansurvey.pmta.sailthru.com", subject="URGENT: APPOINTMENT for Shawn Becker", body=""
    )
    assert spam_lookalike is None or spam_lookalike.category != "medical"

    # Body-based pharmacy match, unrelated sender.
    pharmacy = engine.classify(
        "notifications@somepharmacychain.example", subject="Appointment for prescription pickup",
        body="Your local pharmacy has your refill ready.",
    )
    assert pharmacy is not None
    assert pharmacy.category == "medical"

    # Spam that mimics "APPOINTMENT" in the subject from an unrelated survey
    # sender, with no medical body content: must NOT match either new rule.
    spam = engine.classify(
        "noreply@americansurvey.pmta.sailthru.com", subject="URGENT: APPOINTMENT for Shawn Becker", body=""
    )
    assert spam is None or spam.category != "medical"


def test_real_config_flags_linkedin_inmail_job_content_as_recruiter_job_2026_07_06() -> None:
    # Regression test: LinkedIn InMail (and its reply-notification address)
    # routes to recruiter_job when the subject signals real job content —
    # "New job opportunity - <role>", "Hiring for ...", "Software Engineer
    # Opportunity", or an "(Onsite)"/"(Remote)" tag.
    engine = RulesEngine()

    for sender, subject in [
        ("inmail-hit-reply@linkedin.com", "New job opportunity - Staff Software Engineer - Full-Stack Python and React"),
        ("hit-reply@linkedin.com", "Message replied: New job opportunity - Staff Software Engineer - Full-Stack Python and React"),
        ("inmail-hit-reply@linkedin.com", '"Sr. AI Full Stack Engineer in Des Moines, IA (Onsite)'),
        ("inmail-hit-reply@linkedin.com", "Hiring for Architect in United States"),
        ("inmail-hit-reply@linkedin.com", "Software Engineer Opportunity! - Looking for a change!?"),
        ("hit-reply@linkedin.com", "Message replied: PDS - Software Engineer Opportunity"),
        ("inmail-hit-reply@linkedin.com", "Fully-Remote Lead Software Engineer Opportunity $175K! (Remote)"),
    ]:
        result = engine.classify(sender, subject=subject, body="")
        assert result is not None, f"{sender}/{subject!r} should have matched a rule"
        assert result.category == "recruiter_job", f"{sender} -> {result.category}, expected recruiter_job"

    # Unrelated LinkedIn mail (not from an InMail address) still goes to
    # social, unaffected by this rule.
    unrelated = engine.classify("messages-noreply@linkedin.com", subject="You have a new connection request", body="")
    assert unrelated is not None
    assert unrelated.category == "social"


def test_real_config_leaves_generic_linkedin_inmail_networking_in_social_2026_07_06() -> None:
    # Regression test: narrowing the InMail rule (2026-07-06) to require a
    # job-content subject phrase means InMail messages that DON'T carry one
    # — a network-building pitch, or a bare "Message replied:" with no job
    # title — must fall through to the generic Social networks rule
    # instead of being swept into recruiter_job the way the old
    # sender-alone version of this rule did.
    engine = RulesEngine()

    network_pitch = engine.classify(
        "inmail-hit-reply@linkedin.com",
        subject="Come join our network of consultants @ Equal Experts!",
        body="",
    )
    assert network_pitch is not None
    assert network_pitch.category == "social"

    generic_reply = engine.classify(
        "hit-reply@linkedin.com", subject="Message replied: 100% REMOTE Full-Stack Engineer @ CVS (Data / UI)", body=""
    )
    assert generic_reply is not None
    assert generic_reply.category == "social"

    fit_notice = engine.classify(
        "jobs-listings@linkedin.com",
        subject="You may be a fit for Hired's Software Engineer, Micro Platforms (Remote)",
        body="",
    )
    assert fit_notice is not None
    assert fit_notice.category == "social"


def test_real_config_flags_linkedin_i_want_to_connect_as_recruiter_job_2026_07_06() -> None:
    # Regression test: LinkedIn's "I want to connect" invitation notification
    # (invitations@linkedin.com) routes to recruiter_job per user request —
    # distinct from the near-identical "I've sent you a connection request"
    # template from the same sender, which is deliberately NOT auto-routed
    # (see scripts/recategorize_message.py for the manual alternative).
    engine = RulesEngine()

    result = engine.classify("invitations@linkedin.com", subject="I want to connect", body="")
    assert result is not None
    assert result.category == "recruiter_job"

    # The near-identical connection-request receipt is NOT auto-routed.
    not_routed = engine.classify(
        "invitations@linkedin.com", subject="I\u2019ve sent you a connection request", body=""
    )
    assert not_routed is None or not_routed.category != "recruiter_job"


def test_real_config_flags_jobhat_as_recruiter_job_2026_07_06() -> None:
    # Regression test: jobhat.com job-alert mail ("New job openings posted
    # near you!") routes to recruiter_job, alongside indeed.com/jobcase.com/
    # ziprecruiter.com in the same "Recruiter / job boards" rule.
    engine = RulesEngine()

    result = engine.classify("jobs@umail.jobhat.com", subject="New job openings posted near you!", body="")
    assert result is not None
    assert result.category == "recruiter_job"


def test_real_config_flags_additional_job_board_domains_as_recruiter_job_2026_07_06() -> None:
    # Regression test (2nd pass, same day): recurring job-board/staffing-
    # agency domains found repeatedly falling through to the LLM fallback —
    # or, worse, getting mislabeled `ai` by the AI-subject fallback rule
    # when a job title mentions "AI" — during a manual-recategorization
    # sweep. Each of these previously had NO sender-domain rule at all.
    engine = RulesEngine()

    for sender, subject in [
        ("noreply@notification.bebee.com", "20 Software Engineer opportunities waiting in Lehi, Utah"),
        ("alerts@energyjobline.com", "New Jobs Matching Your Profile"),
        ("no.reply@email.roberthalf.com", "New Software Engineer jobs in San Francisco, Ca"),
        ("email@pmail.job-tree.com", "1 new job match at WSP"),
        ("benjamin.gardner@lensa.com", "New job opportunities just for you!"),
        ("jobs@alerts.jobot.com", "Sr. AI Software Engineer (C#/.Net, infrastructure & startup exp. req'd) - 100% Remote"),
        ("nrg-jobnotification@noreply.jobs2web.com", "New jobs posted from NRG"),
        ("hello@obrajobs.com", "New job matches: REMOTE Senior Full-Stack Engineer - Python, React, Django"),
        ("deepak.kumar@diverselynx.com", "RE: As discussed need RTR & Salary confirmation :: Full stack GenAI/Agentic AI"),
        ("jitendrak@sysmind.com", "Open Contract Role - Software Engineer"),
        ("shaijal.b@msrtechnologies.com", "Fulltime Hiring || Senior Data Platform / Data Product Engineering Lead"),
        ("sam.s@navasoftware.com", "Data Engineer - Collabera / Accenture - Chicago, IL - Hybrid"),
    ]:
        result = engine.classify(sender, subject=subject, body="")
        assert result is not None, f"{sender} should have matched a rule"
        assert result.category == "recruiter_job", f"{sender} -> {result.category}, expected recruiter_job"


def test_real_config_flags_dedicated_ai_newsletter_domains_as_ai_2026_07_06() -> None:
    # Regression test (2nd pass, same day): dedicated AI newsletters found
    # split inconsistently across ai/news/spam_unknown by the LLM fallback
    # (no rule covered them at all before) — now matched by sender domain
    # so they land on `ai` consistently and stop costing LLM calls.
    engine = RulesEngine()

    for sender, subject in [
        ("hi@mail.theresanaiforthat.com", "🦾 AI Turns Your Walk Into a Sprint"),
        ("news@alphasignal.ai", "GitHub Copilot adds Kimi K2, Claude auto-applies for jobs"),
        ("hello@ollama.com", "Ollama 0.31: Faster Gemma 4 on Apple Silicon with multi-token prediction (MTP)"),
        ("auggie@augmentcode.com", "Claude Fable 5 returns and Sonnet 5 is now in Augment Code"),
    ]:
        result = engine.classify(sender, subject=subject, body="")
        assert result is not None, f"{sender} should have matched a rule"
        assert result.category == "ai", f"{sender} -> {result.category}, expected ai"


def test_real_config_flags_linkedin_inmail_unparenthesized_remote_tag_2026_07_06() -> None:
    # Regression test (2nd pass, same day): the original "(Onsite)"/
    # "(Remote)" rules required the literal parenthesized string and missed
    # real InMail traffic using the tag without parens (e.g. trailing
    # "- 6-12+ months - Remote"), which fell through to Social networks
    # instead of recruiter_job. Merged into one word-boundary subject_pattern
    # rule covering Onsite/Remote/Hybrid with or without parens.
    engine = RulesEngine()

    for subject in [
        "Machine Learning Engineer - 6-12+ months - Remote",
        "Sr. AI Full Stack Engineer in Des Moines, IA (Onsite)",
        "Fully-Remote Lead Software Engineer Opportunity $175K! (Remote)",
        "Data Platform Engineer - Hybrid - Chicago",
    ]:
        result = engine.classify("inmail-hit-reply@linkedin.com", subject=subject, body="")
        assert result is not None, f"{subject!r} should have matched a rule"
        assert result.category == "recruiter_job", f"{subject!r} -> {result.category}"

    # Still must NOT catch generic InMail networking with no work-
    # arrangement tag at all (falls through to Social, as before).
    not_routed = engine.classify(
        "inmail-hit-reply@linkedin.com", subject="Come join our network of consultants @ Equal Experts!", body=""
    )
    assert not_routed is None or not_routed.category != "recruiter_job"


def test_real_config_flags_hobby_retailer_senders_as_hobby_2026_07_06() -> None:
    # Regression test: hobby/model-kit retailer mail routes to the new
    # hobby category, scoped by sender domain (not a bare subject-contains-
    # "hobby" match, which would misroute e.g. a historyfacts.com trivia
    # newsletter mentioning "George Washington's surprising hobby").
    engine = RulesEngine()

    for sender, subject in [
        ("support@newtype.us", "Massive Mr. Hobby & Gaia Restock + New Releases"),
        ("support@ak-interactive.com", "You have the EXCLUSIVE keys to the hobby..."),
        ("noreply@smartcart.com", "Kitlinx Newsletter July 2"),
        ("noreply=hobbylinc.com@vrmailer3.com", "Hobby Paint On Sale This Week"),
        ("mrshobbyshop@gmail.com", "Newsletter 8/25/23"),
        ("mrshobby@116113174.mailchimpapp.com", "Special Orders: The Upgrade Your Hobby Deserves!"),
    ]:
        result = engine.classify(sender, subject=subject, body="")
        assert result is not None, f"{sender} should have matched the hobby rule"
        assert result.category == "hobby", f"{sender} -> {result.category}, expected hobby"

    # A newsletter that merely mentions "hobby" in passing, from an
    # unrelated sender, must NOT be swept into this category.
    unrelated = engine.classify(
        "hello@historyfacts.com", subject="George Washington's surprising hobby", body=""
    )
    assert unrelated is None or unrelated.category != "hobby"


def test_real_config_flags_dry_creek_therapy_and_canyon_crest_dental_as_medical_2026_07_06() -> None:
    # Regression test: broadened medical/dental practice-platform rule
    # (dropped the "subject contains Appointment" requirement) now also
    # covers non-appointment mail (announcements, receipts) from these
    # single-purpose practice-management domains.
    engine = RulesEngine()

    for sender, subject in [
        ("reach@webpt.com", "Important COVID-19 Updates from Dry Creek Therapy"),
        ("no-reply@webpt.com", "Appointment Reminder from Dry Creek Therapy at Mountain Point Medical"),
        ("noreply@localmed.com", "Appointment Scheduled"),
        ("noreply@payments.flexmail.dental", "Payment receipt from Canyon Crest Dental"),
    ]:
        result = engine.classify(sender, subject=subject, body="")
        assert result is not None, f"{sender} should have matched the medical rule"
        assert result.category == "medical", f"{sender} -> {result.category}, expected medical"


def test_real_config_flags_andrew_linkedin_digest_as_active_client_2026_07_06() -> None:
    # Regression test: LinkedIn's generic messaging digest ("Andrew just
    # messaged you") routes to active_client when the subject names Andrew
    # (Case), a known active contact, per user request.
    engine = RulesEngine()

    result = engine.classify("messaging-digest-noreply@linkedin.com", subject="Andrew just messaged you", body="")
    assert result is not None
    assert result.category == "active_client"

    # Same digest sender, a different name: must NOT match this rule (falls
    # through to Social networks below).
    other = engine.classify("messaging-digest-noreply@linkedin.com", subject="Priya just messaged you", body="")
    assert other is not None
    assert other.category == "social"


def test_real_config_flags_ai_word_boundary_in_subject_2026_07_06() -> None:
    # Regression test: the fallback "AI mentioned in subject" rule (added
    # 2026-07-06, placed last in rules.yaml so more specific categories
    # always win first) uses subject_pattern's word-boundary regex, not a
    # plain `subject contains "AI"`, specifically to avoid false-positiving
    # on ordinary words that merely contain the substring "ai".
    engine = RulesEngine()

    for subject in [
        "Weekly AI roundup: what changed this week",
        "5 AI tools worth trying",
        "AI-powered code review is here",
        "The Future of AI",
    ]:
        result = engine.classify("newsletter@some-unrecognized-sender.example", subject=subject, body="")
        assert result is not None, f"{subject!r} should have matched the AI subject fallback rule"
        assert result.category == "ai", f"{subject!r} -> {result.category}, expected ai"

    # None of these ordinary words (which merely contain the substring
    # "ai") should trigger the rule.
    for subject in [
        "He said he'd call you back",
        "Please wait in the main lobby",
        "Your seat is available now",
        "Routine maintenance this weekend",
        "New chair for the dining room",
    ]:
        result = engine.classify("newsletter@some-unrecognized-sender.example", subject=subject, body="")
        assert result is None or result.category != "ai", (
            f"{subject!r} incorrectly matched the AI subject fallback rule (got {result})"
        )

    # A recruiter/job-alert subject that legitimately contains "AI" as a
    # word must still be caught by the more specific recruiter_job rules
    # earlier in the file, not swept into the generic "ai" newsletter
    # category by this fallback rule.
    job_alert = engine.classify(
        "jobalerts-noreply@linkedin.com", subject="Sr. AI Full Stack Engineer in Des Moines, IA (Onsite)", body=""
    )
    assert job_alert is not None
    assert job_alert.category == "recruiter_job"


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
