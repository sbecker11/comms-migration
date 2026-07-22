"""Execute the action resolved for a message's category.

Maps the `default_action` values in `rules/actions.yaml` to concrete Gmail
operations. Every category gets a `Category/<name>` label applied (so
nothing is ever silently unlabeled); only categories whose `default_action`
is an archiving tier (see `_ARCHIVING_ACTIONS`) additionally get archived
out of the inbox.

`recruiter_job` mail on `personal_hub` is archived like any other
`label_archive` category as of 2026-07-04 — `job-tracker`'s pickup query
for that account (`label:Category/recruiter_job is:unread`) isn't scoped
to `in:inbox`, so archiving doesn't hide it from that pipeline, it just
tidies the inbox.

`recruiting_funnel` is different: `job-tracker`'s *default* query for its
primary account is `is:unread in:inbox` (inbox-scoped), since job-tracker
reads that account directly with no dependency on this classifier's
labels. If this classifier archived `recruiter_job` mail there before
job-tracker's own poll ran, job-tracker would silently never see it —
exactly the kind of gap this whole project exists to close, just on the
other account. `NEVER_ARCHIVE_CATEGORIES_BY_ACCOUNT` exists specifically
for this: `recruiter_job` is label-only (never archived) on
`recruiting_funnel`, while still auto-archiving everywhere else.
`NEVER_ARCHIVE_CATEGORIES` (account-independent) remains available too,
for any future category that should never archive anywhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from classifier import gmail_client

logger = logging.getLogger(__name__)

LABEL_PREFIX = "Category"

# Actions that additionally remove the message from the inbox. Every other
# action tier only labels — it stays visible for you to act on.
_ARCHIVING_ACTIONS = {"label_archive", "quarantine"}

# Categories that are always labeled but never archived on ANY account,
# overriding whatever rules/actions.yaml's default_action says. Empty for
# now — see module docstring for why recruiter_job no longer needs a
# blanket (account-independent) override.
NEVER_ARCHIVE_CATEGORIES: set[str] = set()

# Same idea, but scoped to specific accounts — see module docstring for why
# recruiting_funnel needs this while personal_hub doesn't.
NEVER_ARCHIVE_CATEGORIES_BY_ACCOUNT: dict[str, set[str]] = {
    "recruiting_funnel": {"recruiter_job"},
}


def _never_archive(category: str, account: str | None) -> bool:
    if category in NEVER_ARCHIVE_CATEGORIES:
        return True
    if account and category in NEVER_ARCHIVE_CATEGORIES_BY_ACCOUNT.get(account, set()):
        return True
    return False


@dataclass
class ActionOutcome:
    message_id: str
    category: str
    label: str
    archived: bool
    dry_run: bool


def label_name(category: str) -> str:
    return f"{LABEL_PREFIX}/{category}"


def execute_action(
    service,
    *,
    message_id: str,
    category: str,
    default_action: str,
    account: str | None = None,
    dry_run: bool = True,
    label_cache: dict[str, str] | None = None,
    from_spam: bool = False,
) -> ActionOutcome:
    """Apply the label (and archive, if the action tier calls for it) for one message.

    `account` enables account-specific archive overrides (see
    `NEVER_ARCHIVE_CATEGORIES_BY_ACCOUNT`) — omit it only for account-
    independent testing; production call sites should always pass it.

    `label_cache` lets a batch run resolve each label id once instead of
    once per message (get_or_create_label is a Gmail API call).

    `from_spam` marks this message as having been found via a spam-folder
    sweep (see `run.classify_and_act`'s `include_spam`) rather than the
    normal query. Always rescues it out of Spam (via
    `gmail_client.rescue_from_spam`, regardless of `should_archive` below) —
    a message a rule confidently matched has no business staying quarantined
    in Spam even for a label-only category like `needs_review`; leaving SPAM
    set would keep it invisible to every downstream consumer either way.
    """
    label = label_name(category)
    should_archive = default_action in _ARCHIVING_ACTIONS and not _never_archive(category, account)

    if dry_run:
        return ActionOutcome(
            message_id=message_id,
            category=category,
            label=label,
            archived=should_archive or from_spam,
            dry_run=True,
        )

    label_cache = label_cache if label_cache is not None else {}
    label_id = label_cache.get(label)
    if label_id is None:
        label_id = gmail_client.get_or_create_label(service, label)
        label_cache[label] = label_id

    if from_spam:
        gmail_client.rescue_from_spam(service, message_id, label_id)
    elif should_archive:
        gmail_client.label_and_archive(service, message_id, label_id)
    else:
        gmail_client.apply_label(service, message_id, label_id)

    return ActionOutcome(
        message_id=message_id,
        category=category,
        label=label,
        archived=should_archive or from_spam,
        dry_run=False,
    )
