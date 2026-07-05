"""Tests for classifier/gmail_client.py's date conversion into the
Iso8601Utc datatype consumed by classifier/rules_v2_engine.py.
"""

from __future__ import annotations

from classifier.gmail_client import (
    _epoch_ms_to_iso8601_utc,
    _rfc2822_to_iso8601_utc,
    parse_gmail_message,
)
from classifier.rules_v2_engine import parse_iso8601_utc


def test_rfc2822_date_header_converts_to_iso8601_utc() -> None:
    result = _rfc2822_to_iso8601_utc("Sat, 04 Jul 2026 12:00:00 -0400")
    assert result == "2026-07-04T16:00:00Z"
    assert parse_iso8601_utc(result) is not None


def test_rfc2822_conversion_handles_missing_header() -> None:
    assert _rfc2822_to_iso8601_utc("") == ""


def test_rfc2822_conversion_handles_garbage_header() -> None:
    assert _rfc2822_to_iso8601_utc("not a real date") == ""


def test_epoch_ms_converts_to_iso8601_utc() -> None:
    # 2026-07-04T16:00:00Z in epoch milliseconds.
    result = _epoch_ms_to_iso8601_utc("1783180800000")
    assert result == "2026-07-04T16:00:00Z"
    assert parse_iso8601_utc(result) is not None


def test_epoch_ms_conversion_handles_missing_value() -> None:
    assert _epoch_ms_to_iso8601_utc(None) == ""
    assert _epoch_ms_to_iso8601_utc("") == ""


def test_parse_gmail_message_populates_iso8601_dates() -> None:
    raw = {
        "id": "abc123",
        "threadId": "thread1",
        "snippet": "hello",
        "internalDate": "1783180800000",
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "recipient@example.com"},
                {"name": "Subject", "value": "Test"},
                {"name": "Date", "value": "Sat, 04 Jul 2026 12:00:00 -0400"},
            ],
            "mimeType": "text/plain",
            "body": {"data": ""},
        },
    }
    message = parse_gmail_message(raw)
    assert message.date_sent == "2026-07-04T16:00:00Z"
    assert message.date_received == "2026-07-04T16:00:00Z"
