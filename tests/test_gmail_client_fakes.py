"""Fake-service coverage for classifier.gmail_client network helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from classifier import gmail_client


class _Exec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeService:
    def __init__(self):
        self.modify_calls: list[dict] = []
        self._labels = [{"id": "L1", "name": "Category/news"}, {"id": "L2", "name": "INBOX"}]
        self._messages = {
            "m1": {
                "id": "m1",
                "threadId": "t1",
                "snippet": "hi",
                "internalDate": "1783180800000",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@b.com"},
                        {"name": "To", "value": "me@x.com"},
                        {"name": "Subject", "value": "Hi"},
                        {"name": "Date", "value": "Sat, 04 Jul 2026 12:00:00 -0400"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": ""},
                },
            }
        }
        self._list_pages = [
            {"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "p2"},
            {"messages": [{"id": "m3"}]},
        ]
        self._list_idx = 0

    def users(self):
        return self

    def messages(self):
        return self

    def labels(self):
        return self

    def list(self, **kwargs):
        if "q" in kwargs or kwargs.get("labelIds"):
            # messages.list
            page = self._list_pages[min(self._list_idx, len(self._list_pages) - 1)]
            self._list_idx += 1
            return _Exec(page)
        # labels.list
        return _Exec({"labels": list(self._labels)})

    def get(self, **kwargs):
        return _Exec(self._messages[kwargs["id"]])

    def create(self, **kwargs):
        created = {"id": "LNEW", "name": kwargs["body"]["name"]}
        self._labels.append(created)
        return _Exec(created)

    def modify(self, **kwargs):
        self.modify_calls.append(kwargs)
        return _Exec({})


def test_account_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("COMMS_CLASSIFIER_PERSONAL_CREDENTIALS", str(tmp_path / "creds.json"))
    assert gmail_client.default_credentials_path("personal_hub") == tmp_path / "creds.json"
    monkeypatch.delenv("COMMS_CLASSIFIER_PERSONAL_CREDENTIALS", raising=False)
    assert gmail_client.default_credentials_path("personal_hub").name == "credentials.json"
    assert gmail_client.default_token_path("personal_hub").name == "token.json"
    assert gmail_client.account_config_dir("personal_hub").name == "personal_hub"


def test_build_query_and_list_ids():
    assert "newer_than:7d" in gmail_client.build_query("in:inbox", 7)
    svc = _FakeService()
    ids = gmail_client.list_message_ids(svc, query="in:inbox", limit=2, newer_than_days=3)
    assert ids == ["m1", "m2"]


def test_list_ids_pagination_without_limit():
    svc = _FakeService()
    ids = gmail_client.list_message_ids(svc, query="in:inbox")
    assert ids == ["m1", "m2", "m3"]


def test_fetch_and_label_helpers():
    svc = _FakeService()
    msg = gmail_client.fetch_message(svc, "m1")
    assert msg.from_address == "a@b.com"
    assert gmail_client.get_or_create_label(svc, "Category/news") == "L1"
    assert gmail_client.get_or_create_label(svc, "Category/newthing") == "LNEW"
    gmail_client.apply_label(svc, "m1", "L1")
    gmail_client.archive_message(svc, "m1")
    gmail_client.label_and_archive(svc, "m1", "L1")
    assert len(svc.modify_calls) == 3
    cats = gmail_client.list_category_labels(svc)
    assert any(c["name"].startswith("Category/") for c in cats)


def test_list_message_ids_with_label_and_batch_modify():
    svc = _FakeService()
    svc._list_pages = [{"messages": [{"id": "x1"}]}]
    svc._list_idx = 0
    ids = gmail_client.list_message_ids_with_label(svc, "L1")
    assert ids == ["x1"]

    calls: list[dict] = []

    def batchModify(**kwargs):
        calls.append(kwargs)
        return _Exec({})

    svc.batchModify = batchModify
    gmail_client.batch_modify(svc, ["a", "b"], add_label_ids=["L1"], remove_label_ids=["INBOX"])
    assert calls and calls[0]["body"]["ids"] == ["a", "b"]
