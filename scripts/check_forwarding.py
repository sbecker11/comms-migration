#!/usr/bin/env python3
"""One-off diagnostic: check an account's *actual* Gmail forwarding/filter
config via the Gmail API, to settle a documentation conflict between
routing-inventory.md (claims scbboston@gmail.com forwards into the
recruiting funnel) and comms-migration-runbook.md / README (assume it
doesn't).

Uses its own token file with gmail.settings.basic (readonly-sufficient
usage; we never call an update/create endpoint here) so the main
classifier's gmail_client.py token/scope is untouched. Safe to delete
afterward: ~/.config/comms-classifier/<account>/diag_token.json

Usage:
    python scripts/check_forwarding.py --account personal_hub
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from classifier.gmail_client import ACCOUNTS, CONFIG_ROOT, default_credentials_path  # noqa: E402

SETTINGS_SCOPES = (
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.readonly",
)


def get_diagnostic_service(account: str, credentials_path: Path, token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SETTINGS_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SETTINGS_SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--account", required=True, choices=sorted(ACCOUNTS.keys()))
    args = ap.parse_args()

    credentials_path = default_credentials_path(args.account)
    token_path = CONFIG_ROOT / args.account / "diag_token.json"

    service = get_diagnostic_service(args.account, credentials_path, token_path)
    email = ACCOUNTS[args.account]["email"]

    print(f"=== Forwarding/filter diagnostic for {email} ({args.account}) ===\n")

    print("-- Auto-forwarding (Settings > Forwarding and POP/IMAP) --")
    try:
        auto_fwd = service.users().settings().getAutoForwarding(userId="me").execute()
        print(f"  enabled: {auto_fwd.get('enabled')}")
        if auto_fwd.get("enabled"):
            print(f"  forwardingEmail: {auto_fwd.get('emailAddress')}")
            print(f"  disposition: {auto_fwd.get('disposition')}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    print("\n-- Registered forwarding addresses (verified destinations) --")
    try:
        fwd_addrs = service.users().settings().forwardingAddresses().list(userId="me").execute()
        addrs = fwd_addrs.get("forwardingAddresses", [])
        if not addrs:
            print("  (none)")
        for a in addrs:
            print(f"  {a.get('forwardingEmail')}  verificationStatus={a.get('verificationStatus')}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    print("\n-- Filters with a forwarding action --")
    try:
        filters = service.users().settings().filters().list(userId="me").execute()
        rows = filters.get("filter", [])
        forwarding_filters = [f for f in rows if f.get("action", {}).get("forward")]
        if not forwarding_filters:
            print(f"  (none of {len(rows)} filters forward mail)")
        for f in forwarding_filters:
            print(f"  criteria={f.get('criteria')}  -> forward={f.get('action', {}).get('forward')}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
