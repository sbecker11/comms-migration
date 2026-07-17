"""Coverage for classifier.__init__ env-key diagnostics."""

from __future__ import annotations

import classifier


def test_log_env_key_source_missing(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    classifier._log_env_key_source("ANTHROPIC_API_KEY")
    assert "WARNING" in capsys.readouterr().out


def test_log_env_key_source_shell(monkeypatch, capsys, tmp_path):
    empty = tmp_path / "e.env"
    empty.write_text("")
    monkeypatch.setattr(classifier, "_PROJECT_ROOT_ENV", empty)
    monkeypatch.setattr(classifier, "_SHARED_ENV", empty)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "shell-key")
    classifier._log_env_key_source("ANTHROPIC_API_KEY")
    assert "pre-existing shell/process environment" in capsys.readouterr().out


def test_log_env_key_source_local(monkeypatch, capsys, tmp_path):
    local = tmp_path / "l.env"
    shared = tmp_path / "s.env"
    local.write_text("ANTHROPIC_API_KEY=local-key\n")  # pragma: allowlist secret
    shared.write_text("")
    monkeypatch.setattr(classifier, "_PROJECT_ROOT_ENV", local)
    monkeypatch.setattr(classifier, "_SHARED_ENV", shared)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-key")  # pragma: allowlist secret
    classifier._log_env_key_source("ANTHROPIC_API_KEY")
    assert "local .env" in capsys.readouterr().out


def test_log_env_key_source_shared(monkeypatch, capsys, tmp_path):
    local = tmp_path / "l.env"
    shared = tmp_path / "s.env"
    local.write_text("")
    shared.write_text("ANTHROPIC_API_KEY=shared-key\n")  # pragma: allowlist secret
    monkeypatch.setattr(classifier, "_PROJECT_ROOT_ENV", local)
    monkeypatch.setattr(classifier, "_SHARED_ENV", shared)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "shared-key")  # pragma: allowlist secret
    classifier._log_env_key_source("ANTHROPIC_API_KEY")
    assert "shared .env" in capsys.readouterr().out
