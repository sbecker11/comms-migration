from __future__ import annotations

from classifier.actions import execute_action, label_name


class _FakeLabelsResource:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self._next_id = 1

    def list(self, userId: str):  # noqa: N803 - matches Gmail API kwarg name
        labels = [{"id": v, "name": k} for k, v in self._store.items()]
        return _Executable({"labels": labels})

    def create(self, userId: str, body: dict):  # noqa: N803
        name = body["name"]
        label_id = f"Label_{self._next_id}"
        self._next_id += 1
        self._store[name] = label_id
        return _Executable({"id": label_id, "name": name})


class _FakeMessagesResource:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def modify(self, userId: str, id: str, body: dict):  # noqa: N803, A002
        self._calls.append({"message_id": id, "body": body})
        return _Executable({})


class _Executable:
    def __init__(self, result: dict) -> None:
        self._result = result

    def execute(self):
        return self._result


class FakeGmailService:
    """Minimal stand-in for the googleapiclient Gmail resource chain."""

    def __init__(self) -> None:
        self.label_store: dict[str, str] = {}
        self.modify_calls: list[dict] = []

    def users(self):
        return self

    def labels(self):
        return _FakeLabelsResource(self.label_store)

    def messages(self):
        return _FakeMessagesResource(self.modify_calls)


def test_dry_run_never_touches_gmail() -> None:
    service = FakeGmailService()
    outcome = execute_action(
        service,
        message_id="msg1",
        category="news",
        default_action="label_archive",
        dry_run=True,
    )
    assert outcome.dry_run is True
    assert outcome.archived is True
    assert outcome.label == "Category/news"
    assert service.modify_calls == []
    assert service.label_store == {}


def test_label_archive_action_labels_and_removes_inbox() -> None:
    service = FakeGmailService()
    outcome = execute_action(
        service,
        message_id="msg1",
        category="news",
        default_action="label_archive",
        dry_run=False,
    )
    assert outcome.archived is True
    assert len(service.modify_calls) == 1
    call = service.modify_calls[0]
    assert call["message_id"] == "msg1"
    assert "INBOX" in call["body"]["removeLabelIds"]
    assert call["body"]["addLabelIds"] == [service.label_store["Category/news"]]


def test_flag_action_labels_without_archiving() -> None:
    service = FakeGmailService()
    outcome = execute_action(
        service,
        message_id="msg2",
        category="billing",
        default_action="flag",
        dry_run=False,
    )
    assert outcome.archived is False
    call = service.modify_calls[0]
    assert "removeLabelIds" not in call["body"]
    assert call["body"]["addLabelIds"] == [service.label_store["Category/billing"]]


def test_recruiter_job_is_labeled_and_archived_on_personal_hub() -> None:
    # As of 2026-07-04, recruiter_job is archived like any other
    # label_archive category on personal_hub — job-tracker's own pickup
    # query for that account isn't scoped to in:inbox, so archiving here
    # doesn't hide anything from that pipeline.
    service = FakeGmailService()
    outcome = execute_action(
        service,
        message_id="msg3",
        category="recruiter_job",
        default_action="label_archive",
        account="personal_hub",
        dry_run=False,
    )
    assert outcome.archived is True
    assert outcome.label == "Category/recruiter_job"
    call = service.modify_calls[0]
    assert "INBOX" in call["body"]["removeLabelIds"]


def test_recruiter_job_is_never_archived_on_recruiting_funnel() -> None:
    # job-tracker's DEFAULT query on recruiting_funnel (its primary
    # account) IS scoped to in:inbox, unlike personal_hub — so archiving
    # there would create exactly the silent-mail-loss gap this project
    # exists to close, just on the other account.
    service = FakeGmailService()
    outcome = execute_action(
        service,
        message_id="msg3b",
        category="recruiter_job",
        default_action="label_archive",
        account="recruiting_funnel",
        dry_run=False,
    )
    assert outcome.archived is False
    call = service.modify_calls[0]
    assert "removeLabelIds" not in call["body"]


def test_never_archive_categories_override_still_works() -> None:
    # Defense in depth: NEVER_ARCHIVE_CATEGORIES stays available as an
    # override hook, even though it's empty by default today.
    service = FakeGmailService()
    from classifier import actions as actions_module

    original = actions_module.NEVER_ARCHIVE_CATEGORIES
    actions_module.NEVER_ARCHIVE_CATEGORIES = {"recruiter_job"}
    try:
        outcome = execute_action(
            service,
            message_id="msg4",
            category="recruiter_job",
            default_action="label_archive",
            dry_run=False,
        )
    finally:
        actions_module.NEVER_ARCHIVE_CATEGORIES = original
    assert outcome.archived is False
    call = service.modify_calls[0]
    assert "removeLabelIds" not in call["body"]


def test_label_cache_avoids_duplicate_label_lookups() -> None:
    service = FakeGmailService()
    cache: dict[str, str] = {}
    execute_action(
        service, message_id="m1", category="news", default_action="label_archive",
        dry_run=False, label_cache=cache,
    )
    first_label_id = cache[label_name("news")]
    # Second message, same category — should reuse the cached label id
    # rather than calling labels().create() again.
    execute_action(
        service, message_id="m2", category="news", default_action="label_archive",
        dry_run=False, label_cache=cache,
    )
    assert cache[label_name("news")] == first_label_id
    assert len(service.label_store) == 1
