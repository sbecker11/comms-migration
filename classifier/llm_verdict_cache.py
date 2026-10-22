"""Persistent per-message cache of LLM classification verdicts for the inbox run
(see `classifier/run.py`'s `classify_and_act`).

The fast cycle queries `in:inbox` every few minutes, and a message that is
labeled but not archived stays in the inbox, so without this the same message
went to the LLM on every run until it aged out of `--newer-than`. Verified in
the October 2026 logs: 223 distinct messages were classified ~11,100 times
(Meta login-code mail up to 977 times each). The LLM's answer for a given
message doesn't change, so a cached verdict is reused and only the action
(label / archive) is re-applied, which is idempotent.

One JSON file per account (`rules/.llm_verdicts.<account>.json`, gitignored —
same pattern as `spam_sweep_state`): message id → {category, confidence},
newest last, capped at `MAX_ENTRIES`.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "rules"
MAX_ENTRIES = 5000


def state_path(account: str) -> Path:
    return STATE_DIR / f".llm_verdicts.{account}.json"


def load(account: str, path: Path | None = None) -> dict[str, dict]:
    p = path or state_path(account)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(account: str, verdicts: dict[str, dict], path: Path | None = None) -> None:
    p = path or state_path(account)
    kept = dict(list(verdicts.items())[-MAX_ENTRIES:])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(kept, indent=2), encoding="utf-8")
