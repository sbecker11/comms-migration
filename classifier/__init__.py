"""Phase 5 categorization & action layer.

Reads mail from the mapped Gmail accounts, resolves a category via
``rules/senders.yaml`` + ``rules/actions.yaml`` (falling back to an LLM for
ambiguous senders), and executes the configured action (label, archive,
flag, quarantine, digest).

This package owns *categorization of already-arrived mail*. It does not
decide where a sender should forward to (that's `contacts/` + `rules/senders.yaml`,
Layer 2) and it does not process recruiting mail (that's the sibling
`job-tracker` repo).
"""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# Explicit paths rather than a bare load_dotenv() (which walks up from the
# CWD and stops at the first .env it finds) for two reasons: it no longer
# depends on always being invoked with CWD=comms-migration/ (previously
# true in practice, but fragile), and it lets _log_env_key_source below
# attribute the source correctly rather than guessing from CWD-dependent
# behavior. The shared parent .env (workspace-recruiting-automation/.env,
# where ANTHROPIC_API_KEY genuinely lives as of 2026-07-15 rather than being
# duplicated per-repo) is loaded second as a fallback — this repo's own
# .env is loaded first and always wins for any key it sets locally.
#
# _SHARED_ENV is derived from _PROJECT_ROOT_ENV.parent (one level above the
# already-correct project root) rather than its own independently-counted
# Path(__file__).parents[N], so it can't drift out of sync with
# _PROJECT_ROOT_ENV if this file's own depth in the repo ever changes.
# recruiting-automation's run_cycle.sh/status.sh independently derive the
# very same directory via a shell WORKSPACE_ROOT var (see that repo's
# install.sh) and export it as RECRUITING_AUTOMATION_WORKSPACE_ROOT, so that
# env var is checked first here too — keeps both sides of the process
# boundary pointed at the same directory if it's ever overridden.
_PROJECT_ROOT_ENV = Path(__file__).resolve().parents[1] / ".env"
_WORKSPACE_ROOT_OVERRIDE = os.environ.get("RECRUITING_AUTOMATION_WORKSPACE_ROOT")
_SHARED_ENV = (
    Path(_WORKSPACE_ROOT_OVERRIDE) / ".env"
    if _WORKSPACE_ROOT_OVERRIDE
    else _PROJECT_ROOT_ENV.parent.parent / ".env"
)
def _safe_load_dotenv(path: Path) -> None:
    """`load_dotenv`, tolerant of a still-git-crypt-encrypted `.env`.

    A git-crypt-encrypted `.env` that hasn't been `git-crypt unlock`ed yet
    (a fresh clone with no key registered, or CI, which never has the key
    at all) checks out as raw AES-256 ciphertext, not valid UTF-8 text.
    Without this, python-dotenv's parser raises UnicodeDecodeError — and
    since this module-level load runs at package-import time, that crashed
    *every* test file that imports classifier (observed 2026-08-19: all 15
    test files failing identically in CI right after `.env` was git-crypt-
    encrypted). This makes the encrypted-but-unlocked case degrade safely
    instead of a hard crash, matching what the docs already promise.
    """
    try:
        load_dotenv(path)
    except UnicodeDecodeError:
        pass


def _safe_dotenv_values(path: Path) -> dict:
    try:
        return dotenv_values(path)
    except UnicodeDecodeError:
        return {}


_safe_load_dotenv(_PROJECT_ROOT_ENV)
_safe_load_dotenv(_SHARED_ENV)


def _log_env_key_source(key: str) -> None:
    """One-line diagnostic at import time (added 2026-07-15) so every hourly
    cycle's log durably records whether the shared-.env fallback actually
    worked, instead of that only being answerable via an ad-hoc `python -c`
    check — and so a missing key surfaces here as a clear warning instead of
    a confusing 401 deep inside whichever Anthropic call site hits it first.
    """
    value = os.environ.get(key, "")
    if not value:
        print(
            f"[comms-migration] WARNING: {key} is not set (checked "
            f"{_PROJECT_ROOT_ENV}, {_SHARED_ENV}, and the shell environment) "
            "— any LLM-fallback call will fail."
        )
        return
    # Attribute by exact value match rather than mere presence, so a
    # present-but-blank entry in either file (which load_dotenv treats as
    # "already set" and won't let a later call override) can't be misreported
    # as the source when it actually contributed nothing.
    if _safe_dotenv_values(_PROJECT_ROOT_ENV).get(key) == value:
        source = f"local .env ({_PROJECT_ROOT_ENV})"
    elif _safe_dotenv_values(_SHARED_ENV).get(key) == value:
        source = f"shared .env ({_SHARED_ENV})"
    else:
        source = "pre-existing shell/process environment"
    print(f"[comms-migration] {key}: loaded from {source} ({len(value)} chars).")


_log_env_key_source("ANTHROPIC_API_KEY")
