"""Multi-account Gmail API client.

Generalizes the single-account pattern from job-tracker's
`job_tracker/email/gmail_reader.py` to support classifying mail across
several mapped Gmail accounts (the recruiting funnel and the personal hub
today; more can be registered as they get their own OAuth client).

Each account gets its own credentials/token pair under
``~/.config/comms-classifier/<account>/``, so accounts never share tokens
or scopes. Labeling/archiving requires the broader ``gmail.modify`` scope
(vs. job-tracker's read-only scope), so this is a separate OAuth consent
even for the recruiting funnel account.
"""

from __future__ import annotations

import base64
import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

from classifier.rules_v2_engine import Iso8601Utc

# Full mail management (label, archive) needs gmail.modify, not gmail.readonly.
GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.modify",)
DEFAULT_QUERY = "in:inbox"
CONFIG_ROOT = Path.home() / ".config" / "comms-classifier"

# Registered accounts. `credentials_env` lets you point at a shared OAuth
# client (e.g. reuse job-tracker's downloaded client_secret_*.json) via env
# var instead of duplicating the file per account.
ACCOUNTS: dict[str, dict[str, str]] = {
    "recruiting_funnel": {
        "email": "shawnbecker.recruiting@gmail.com",
        "credentials_env": "COMMS_CLASSIFIER_RECRUITING_CREDENTIALS",
    },
    "personal_hub": {
        "email": "scbboston@gmail.com",
        "credentials_env": "COMMS_CLASSIFIER_PERSONAL_CREDENTIALS",
    },
}


@dataclass
class RawMessage:
    id: str
    thread_id: str
    from_address: str
    to_address: str
    cc_address: str
    subject: str
    date_sent: Iso8601Utc  # converted from the raw "Date" header (RFC 2822)
    date_received: Iso8601Utc  # converted from Gmail's internalDate (epoch ms)
    snippet: str
    body_plain: str
    body_html: str
    label_ids: list[str]


def account_config_dir(account: str) -> Path:
    return CONFIG_ROOT / account


def default_credentials_path(account: str) -> Path:
    info = ACCOUNTS.get(account, {})
    env_name = info.get("credentials_env")
    if env_name and os.environ.get(env_name):
        return Path(os.environ[env_name]).expanduser()
    return account_config_dir(account) / "credentials.json"


def default_token_path(account: str) -> Path:
    return account_config_dir(account) / "token.json"


def _require_google_libs() -> None:
    try:
        from google.auth.transport.requests import Request  # noqa: F401
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Gmail support requires google-api-python-client and google-auth-oauthlib. "
            "Install with: pip install google-api-python-client google-auth-oauthlib"
        ) from exc


def get_gmail_service(
    account: str,
    *,
    credentials_path: Path | None = None,
    token_path: Path | None = None,
):
    """Build an authenticated Gmail API client for one registered account."""
    _require_google_libs()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    credentials_path = credentials_path or default_credentials_path(account)
    token_path = token_path or default_token_path(account)

    if not credentials_path.is_file():
        raise FileNotFoundError(
            f"Gmail credentials not found at {credentials_path} for account '{account}'. "
            "Download OAuth desktop credentials from Google Cloud Console for this "
            f"Gmail account, or set {ACCOUNTS.get(account, {}).get('credentials_env')}."
        )

    creds = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                # Most common cause while this OAuth app is in Google's
                # "Testing" publishing status: refresh tokens for unverified
                # apps hard-expire after 7 days, regardless of use. Fall
                # through to a fresh interactive login instead of raising a
                # confusing invalid_grant/RefreshError.
                print(
                    f"Cached Gmail token for '{account}' is no longer valid "
                    f"({exc}). Re-opening browser for a fresh login — this is "
                    "expected roughly weekly while this app is in Google's "
                    "'Testing' publishing status (unverified-app tokens expire "
                    "after 7 days). Sign in as the same account you used before."
                )
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") or []
    return {item["name"].lower(): item["value"] for item in headers if "name" in item and "value" in item}


def _decode_part_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def _collect_bodies(payload: dict[str, Any], plain_parts: list[str], html_parts: list[str]) -> None:
    mime_type = payload.get("mimeType", "")
    body = payload.get("body") or {}
    data = body.get("data")
    if data:
        text = _decode_part_data(data)
        if mime_type == "text/plain":
            plain_parts.append(text)
        elif mime_type == "text/html":
            html_parts.append(text)
    for part in payload.get("parts") or []:
        _collect_bodies(part, plain_parts, html_parts)


_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(value: str) -> str:
    # Minimal fallback text extraction; classifier only needs enough text
    # for keyword/LLM categorization, not faithful rendering.
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _rfc2822_to_iso8601_utc(value: str) -> Iso8601Utc:
    """Convert the raw "Date" header (RFC 2822) into the Iso8601Utc format
    every consumer downstream of this module expects. Returns "" (not None
    — RawMessage fields are always plain str) if missing/unparseable.
    """
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_ms_to_iso8601_utc(value: str | None) -> Iso8601Utc:
    """Convert Gmail's internalDate (epoch milliseconds, as a string) into
    the Iso8601Utc format every consumer downstream of this module expects.
    """
    if not value:
        return ""
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_gmail_message(raw: dict[str, Any]) -> RawMessage:
    payload = raw.get("payload") or {}
    headers = _header_map(payload)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    _collect_bodies(payload, plain_parts, html_parts)

    body_plain = "\n".join(part.strip() for part in plain_parts if part.strip())
    body_html = "\n".join(part.strip() for part in html_parts if part.strip())
    if not body_plain.strip() and body_html.strip():
        body_plain = _html_to_text(body_html)
    body_plain = html.unescape(body_plain)

    _, from_address = parseaddr(headers.get("from", ""))
    _, to_address = parseaddr(headers.get("to", ""))
    _, cc_address = parseaddr(headers.get("cc", ""))

    return RawMessage(
        id=raw.get("id", ""),
        thread_id=raw.get("threadId", ""),
        from_address=from_address or headers.get("from", ""),
        to_address=to_address or headers.get("to", ""),
        cc_address=cc_address or headers.get("cc", ""),
        subject=headers.get("subject", ""),
        date_sent=_rfc2822_to_iso8601_utc(headers.get("date", "")),
        date_received=_epoch_ms_to_iso8601_utc(raw.get("internalDate")),
        snippet=raw.get("snippet", ""),
        body_plain=body_plain,
        body_html=body_html,
        label_ids=list(raw.get("labelIds") or []),
    )


def build_query(base_query: str = DEFAULT_QUERY, newer_than_days: int | None = None) -> str:
    query = base_query.strip()
    if newer_than_days is not None and newer_than_days > 0:
        query = f"{query} newer_than:{newer_than_days}d".strip()
    return query


def list_message_ids(
    service,
    *,
    query: str = DEFAULT_QUERY,
    limit: int | None = None,
    newer_than_days: int | None = None,
) -> list[str]:
    q = build_query(query, newer_than_days)
    ids: list[str] = []
    page_token = None
    max_results = min(limit, 500) if limit else 100

    while True:
        request = (
            service.users().messages().list(userId="me", q=q, maxResults=max_results, pageToken=page_token)
        )
        response = request.execute()
        for item in response.get("messages") or []:
            ids.append(item["id"])
            if limit is not None and len(ids) >= limit:
                return ids
        page_token = response.get("nextPageToken")
        if not page_token:
            break
        if limit is not None:
            max_results = min(limit - len(ids), 500)

    return ids


def fetch_message(service, message_id: str) -> RawMessage:
    raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    return parse_gmail_message(raw)


def get_or_create_label(service, label_name: str) -> str:
    """Return the Gmail label id for `label_name`, creating it if needed."""
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"] == label_name:
            return label["id"]
    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def apply_label(service, message_id: str, label_id: str) -> None:
    service.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [label_id]}
    ).execute()


def archive_message(service, message_id: str) -> None:
    """Remove INBOX so the message leaves the inbox but stays searchable."""
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}
    ).execute()


def label_and_archive(service, message_id: str, label_id: str) -> None:
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]},
    ).execute()


def rescue_from_spam(service, message_id: str, label_id: str) -> None:
    """Pull a message out of Spam and give it a real category label.

    Unlike `label_and_archive` (which only strips INBOX — a message that's
    never been in the inbox has nothing to strip there), a spam-origin
    message also carries the SPAM label itself, which Gmail treats
    specially: as long as SPAM is present, the message stays hidden from
    every normal folder/search regardless of what other labels it has. Both
    removals happen in one call so the message can't end up in a
    half-rescued state (SPAM removed, INBOX still set — landing back in the
    inbox — or vice versa) if the call were split in two.
    """
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["SPAM", "INBOX"]},
    ).execute()


def list_category_labels(service) -> list[dict[str, str]]:
    """Every `Category/*` label that currently exists in this mailbox
    (classifier.actions.LABEL_PREFIX) — used by scripts/reset_categorization.py
    to find everything a prior classifier run may have applied.
    """
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    return [{"id": lbl["id"], "name": lbl["name"]} for lbl in labels if lbl["name"].startswith("Category/")]


def list_message_ids_with_label(service, label_id: str) -> list[str]:
    """Every message currently carrying `label_id` (any Gmail label, not
    just Category/* — used to find exactly what a reset needs to touch).
    """
    ids: list[str] = []
    page_token = None
    while True:
        response = (
            service.users()
            .messages()
            .list(userId="me", labelIds=[label_id], maxResults=500, pageToken=page_token)
            .execute()
        )
        for item in response.get("messages") or []:
            ids.append(item["id"])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return ids


def batch_modify(
    service,
    message_ids: list[str],
    *,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> None:
    """Apply the same add/remove label change to many messages at once via
    Gmail's `batchModify` (capped at 1000 ids/call, so chunk larger lists) —
    far fewer API calls than one `modify` per message.
    """
    body: dict[str, Any] = {"ids": []}
    if add_label_ids:
        body["addLabelIds"] = add_label_ids
    if remove_label_ids:
        body["removeLabelIds"] = remove_label_ids
    for start in range(0, len(message_ids), 1000):
        chunk = message_ids[start : start + 1000]
        service.users().messages().batchModify(userId="me", body={**body, "ids": chunk}).execute()
