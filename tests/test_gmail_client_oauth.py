"""Mocked OAuth path coverage for classifier.gmail_client.get_gmail_service."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from classifier import gmail_client


def test_get_gmail_service_missing_creds(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        gmail_client.get_gmail_service(
            "personal_hub",
            credentials_path=tmp_path / "missing.json",
            token_path=tmp_path / "tok.json",
        )


def test_get_gmail_service_valid_cached_token(monkeypatch, tmp_path: Path):
    creds = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    creds.write_text("{}")
    token.write_text("{}")
    fake_creds = SimpleNamespace(valid=True, expired=False, refresh_token=None, to_json=lambda: "{}")
    built = object()

    monkeypatch.setattr(gmail_client, "_require_google_libs", lambda: None)
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.oauth2.credentials",
        SimpleNamespace(
            Credentials=SimpleNamespace(from_authorized_user_file=lambda *a, **k: fake_creds)
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.auth.transport.requests",
        SimpleNamespace(Request=object),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google_auth_oauthlib.flow",
        SimpleNamespace(InstalledAppFlow=SimpleNamespace()),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "googleapiclient.discovery",
        SimpleNamespace(build=lambda *a, **k: built),
    )

    svc = gmail_client.get_gmail_service(
        "personal_hub", credentials_path=creds, token_path=token
    )
    assert svc is built


def test_get_gmail_service_fresh_login(monkeypatch, tmp_path: Path):
    creds = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    creds.write_text("{}")
    fake_creds = SimpleNamespace(valid=True, to_json=lambda: '{"ok":true}')
    built = object()

    class FakeFlow:
        @staticmethod
        def from_client_secrets_file(*a, **k):
            return SimpleNamespace(run_local_server=lambda port=0: fake_creds)

    monkeypatch.setattr(gmail_client, "_require_google_libs", lambda: None)
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.oauth2.credentials",
        SimpleNamespace(Credentials=SimpleNamespace(from_authorized_user_file=lambda *a, **k: None)),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.auth.transport.requests",
        SimpleNamespace(Request=object),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google_auth_oauthlib.flow",
        SimpleNamespace(InstalledAppFlow=FakeFlow),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "googleapiclient.discovery",
        SimpleNamespace(build=lambda *a, **k: built),
    )

    svc = gmail_client.get_gmail_service(
        "personal_hub", credentials_path=creds, token_path=token
    )
    assert svc is built
    assert token.is_file()
