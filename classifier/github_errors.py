"""Keep GitHub Actions failures until the cause is found and fixed.

Mail to scbboston@gmail.com from GitHub is forwarded to
shawnbecker.recruiting+errormessages@gmail.com. The classifier files each
failure here and archives it out of the recruiting inbox. The copy stays
under var/github-errors/open until scripts/github_errors.py marks that
repository workflow fixed. Marking it fixed moves the copy to
var/github-errors/fixed; it is not deleted.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "var" / "github-errors"

_FWD_RE = re.compile(r"^(?:(?:re|fwd|fw)\s*:\s*)+", re.I)
_FAILURE_RE = re.compile(
    r"\[(?P<repo>[\w.-]+/[\w.-]+)\]\s+Run failed:\s*(?P<workflow>.+?)\s+-\s*(?P<branch>[^\s(]+)",
    re.I,
)


def parse_github_failure(subject: str) -> dict[str, str] | None:
    """Repo, workflow, and branch from a GitHub 'Run failed' subject.

    A leading Fwd:/Re: is ignored. None when the subject is not that shape.
    """
    text = _FWD_RE.sub("", (subject or "").strip())
    match = _FAILURE_RE.search(text)
    if match is None:
        return None
    return {
        "repo": match.group("repo"),
        "workflow": match.group("workflow").strip(),
        "branch": match.group("branch"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _already_stored(root: Path, message_id: str) -> Path | None:
    name = f"{message_id}.json"
    for folder in ("open", "fixed"):
        path = root / folder / name
        if path.is_file():
            return path
    return None


def record_github_error(
    *,
    message_id: str,
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    received_at: str = "",
    root: Path | None = None,
) -> Path:
    """Write one open failure. The same Gmail id is not stored twice."""
    root = root or DEFAULT_ROOT
    existing = _already_stored(root, message_id)
    if existing is not None:
        return existing
    parsed = parse_github_failure(subject) or {}
    record = {
        "message_id": message_id,
        "from_address": from_address,
        "to_address": to_address,
        "subject": subject,
        "received_at": received_at,
        "repo": parsed.get("repo", ""),
        "workflow": parsed.get("workflow", ""),
        "branch": parsed.get("branch", ""),
        "body": body or "",
        "status": "open",
        "stored_at": _now(),
        "fixed_at": "",
        "note": "",
    }
    dest = root / "open"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{message_id}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def list_open(root: Path | None = None) -> list[dict]:
    root = root or DEFAULT_ROOT
    folder = root / "open"
    if not folder.is_dir():
        return []
    rows = [_load(path) for path in sorted(folder.glob("*.json"))]
    rows.sort(key=lambda row: (row.get("repo") or "", row.get("workflow") or "", row.get("stored_at") or ""))
    return rows


def mark_fixed(
    *,
    repo: str,
    workflow: str = "",
    note: str,
    root: Path | None = None,
) -> list[Path]:
    """Move matching open failures to fixed/. A later failure is a new open record."""
    if not (note or "").strip():
        raise ValueError("A note saying what was found and fixed is required")
    root = root or DEFAULT_ROOT
    moved: list[Path] = []
    want_repo = (repo or "").strip().lower()
    want_workflow = (workflow or "").strip().lower()
    for row in list_open(root):
        if (row.get("repo") or "").lower() != want_repo:
            continue
        if want_workflow and (row.get("workflow") or "").lower() != want_workflow:
            continue
        src = root / "open" / f"{row['message_id']}.json"
        row["status"] = "fixed"
        row["fixed_at"] = _now()
        row["note"] = note.strip()
        dest_dir = root / "fixed"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        dest.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        src.unlink()
        moved.append(dest)
    return moved
