"""GitHub failure mail is stored until the cause is marked fixed."""

from __future__ import annotations

from classifier.github_errors import list_open, mark_fixed, parse_github_failure, record_github_error
from classifier.rules_engine import RulesEngine

SUBJECT = "Fwd: [sbecker11/linkage-engine] Run failed: verify - main (9abc123)"
SINK = "shawnbecker.recruiting+errormessages@gmail.com"


def test_parse_strips_the_forward_prefix():
    parsed = parse_github_failure(SUBJECT)
    assert parsed == {
        "repo": "sbecker11/linkage-engine",
        "workflow": "verify",
        "branch": "main",
    }
    assert parse_github_failure("Fwd: weekly digest") is None


def test_rule_matches_only_a_failure_sent_to_the_error_address():
    engine = RulesEngine()
    hit = engine.classify(
        "scbboston@gmail.com",
        to_address=SINK,
        subject=SUBJECT,
    )
    assert hit is not None
    assert hit.category == "github_error"
    used = engine.classify(
        "scbboston@gmail.com",
        to_address="shawnbecker.recruiting+runfailures@gmail.com",
        subject=SUBJECT,
    )
    assert used is not None and used.category == "github_error"
    assert engine.classify(
        "scbboston@gmail.com",
        to_address="shawnbecker.recruiting@gmail.com",
        subject=SUBJECT,
    ) is None or engine.classify(
        "scbboston@gmail.com",
        to_address="shawnbecker.recruiting@gmail.com",
        subject=SUBJECT,
    ).category != "github_error"
    other = engine.classify(
        "scbboston@gmail.com",
        to_address=SINK,
        subject="Fwd: lunch tomorrow",
    )
    assert other is None or other.category != "github_error"


def test_an_open_error_stays_until_it_is_marked_fixed(tmp_path):
    first = record_github_error(
        message_id="g1",
        from_address="scbboston@gmail.com",
        to_address=SINK,
        subject=SUBJECT,
        body="Process completed with exit code 1",
        received_at="2026-10-26T01:26:00Z",
        root=tmp_path,
    )
    again = record_github_error(
        message_id="g1",
        from_address="scbboston@gmail.com",
        to_address=SINK,
        subject=SUBJECT,
        body="Process completed with exit code 1",
        root=tmp_path,
    )
    assert again == first
    open_rows = list_open(tmp_path)
    assert len(open_rows) == 1
    assert open_rows[0]["repo"] == "sbecker11/linkage-engine"
    assert open_rows[0]["status"] == "open"
    assert "exit code 1" in open_rows[0]["body"]

    moved = mark_fixed(
        repo="sbecker11/linkage-engine",
        workflow="verify",
        note="verify failed on a missing import; fixed in the test suite",
        root=tmp_path,
    )
    assert len(moved) == 1
    assert not list_open(tmp_path)
    assert moved[0].parent.name == "fixed"

    record_github_error(
        message_id="g2",
        from_address="scbboston@gmail.com",
        to_address=SINK,
        subject=SUBJECT,
        body="failed again",
        root=tmp_path,
    )
    assert len(list_open(tmp_path)) == 1
    assert list_open(tmp_path)[0]["message_id"] == "g2"
