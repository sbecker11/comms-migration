from __future__ import annotations

import base64

from classifier.gmail_client import build_query, parse_gmail_message


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def test_parse_gmail_message_plain_text() -> None:
    raw = {
        "id": "abc123",
        "threadId": "thread1",
        "snippet": "hello there",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "bob@example.com"},
                {"name": "Subject", "value": "Hi"},
                {"name": "Date", "value": "Mon, 1 Jan 2026 00:00:00 -0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64("Hello, this is the body.")},
        },
    }
    msg = parse_gmail_message(raw)
    assert msg.id == "abc123"
    assert msg.from_address == "alice@example.com"
    assert msg.to_address == "bob@example.com"
    assert msg.subject == "Hi"
    assert "Hello, this is the body." in msg.body_plain


def test_parse_gmail_message_html_fallback_when_no_plain_part() -> None:
    raw = {
        "id": "abc124",
        "threadId": "thread2",
        "snippet": "",
        "payload": {
            "headers": [{"name": "From", "value": "sender@example.com"}],
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>Hello <b>world</b></p>")},
                }
            ],
        },
    }
    msg = parse_gmail_message(raw)
    assert "Hello" in msg.body_plain
    assert "world" in msg.body_plain
    assert "<p>" not in msg.body_plain


def test_build_query_appends_newer_than() -> None:
    assert build_query("in:inbox", 30) == "in:inbox newer_than:30d"
    assert build_query("in:inbox", None) == "in:inbox"
    assert build_query("in:inbox", 0) == "in:inbox"
