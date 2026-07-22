"""Persistent "already scanned" cache for the Spam-folder sweep (see
`classifier/run.py`'s `_sweep_spam`).

Without this, an hourly automated sweep would re-run the LLM fallback on
the *entire* unresolved Spam backlog every single cycle — verified live: a
single manual sweep against ~100 recent spam messages made 91 LLM calls
(~$0.23) because almost none of them matched a sender/domain rule. Running
that every hour forever, mostly against the exact same unchanged backlog,
would be pure waste (the LLM's answer for a given message never changes) —
this is what actually bounds the recurring cost, not `spam_min_confidence`
(that only controls which *outcomes* get acted on, not how many messages
get classified in the first place).

One JSON file per account (`rules/.spam_sweep_seen.<account>.json`,
gitignored — same pattern as `rule_telemetry.DEFAULT_STATS_PATH`): a flat
list of message ids that have ever been through the spam sweep, rescued or
not. A message is recorded here the moment it's classified, regardless of
outcome, so a message that stayed in Spam (no confident match) is never
reclassified on a later run either — Gmail's own spam verdict for it isn't
expected to change, and this file only needs to answer "have we already
spent an LLM call figuring out what this message is", not "is it still in
Spam".
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "rules"


def state_path(account: str) -> Path:
    return STATE_DIR / f".spam_sweep_seen.{account}.json"


def load_seen(account: str, path: Path | None = None) -> set[str]:
    p = path or state_path(account)
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data) if isinstance(data, list) else set()


def mark_seen(account: str, message_ids: list[str], path: Path | None = None) -> None:
    if not message_ids:
        return
    p = path or state_path(account)
    seen = load_seen(account, path=p)
    seen.update(message_ids)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")
