from __future__ import annotations

import json

import pytest

from classifier.llm_classify import (
    LLMClassificationError,
    classify_message,
    classify_message_safe,
)

VALID_CATEGORIES = ["news", "social", "spam_unknown", "active_client"]


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text: str, input_tokens: int = 100, output_tokens: int = 20) -> None:
        self.content = [_FakeTextBlock(text)]
        self.usage = _FakeUsage(input_tokens, output_tokens)


class _FakeMessagesAPI:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeMessage(self._response_text)


class _FakeClient:
    def __init__(self, response_text: str) -> None:
        self.messages = _FakeMessagesAPI(response_text)


def _response(category: str, **overrides) -> str:
    payload = {
        "category": category,
        "subcategory": "",
        "confidence": 0.9,
        "rationale": "test rationale",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_classify_message_parses_valid_response() -> None:
    client = _FakeClient(_response("news", subcategory="digest"))
    result = classify_message(
        from_address="digest@example.com",
        subject="Today's news",
        body="Top stories...",
        valid_categories=VALID_CATEGORIES,
        client=client,
    )
    assert result.category == "news"
    assert result.subcategory == "digest"
    assert result.confidence == 0.9
    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.cost_usd > 0


def test_classify_message_strips_markdown_fence() -> None:
    client = _FakeClient("```json\n" + _response("social") + "\n```")
    result = classify_message(
        from_address="notify@example.com",
        subject="New comment",
        body="...",
        valid_categories=VALID_CATEGORIES,
        client=client,
    )
    assert result.category == "social"


def test_classify_message_rejects_unknown_category() -> None:
    client = _FakeClient(_response("not_a_real_category"))
    with pytest.raises(LLMClassificationError):
        classify_message(
            from_address="x@example.com",
            subject="s",
            body="b",
            valid_categories=VALID_CATEGORIES,
            client=client,
        )


def test_classify_message_rejects_unparseable_json() -> None:
    client = _FakeClient("not json at all")
    with pytest.raises(LLMClassificationError):
        classify_message(
            from_address="x@example.com",
            subject="s",
            body="b",
            valid_categories=VALID_CATEGORIES,
            client=client,
        )


def test_classify_message_clamps_confidence_range() -> None:
    client = _FakeClient(_response("news", confidence=5.0))
    result = classify_message(
        from_address="x@example.com",
        subject="s",
        body="b",
        valid_categories=VALID_CATEGORIES,
        client=client,
    )
    assert result.confidence == 1.0


def test_classify_message_safe_returns_none_on_failure() -> None:
    client = _FakeClient("garbage")
    result = classify_message_safe(
        from_address="x@example.com",
        subject="s",
        body="b",
        valid_categories=VALID_CATEGORIES,
        client=client,
    )
    assert result is None


def test_classify_message_safe_returns_result_on_success() -> None:
    client = _FakeClient(_response("active_client"))
    result = classify_message_safe(
        from_address="x@example.com",
        subject="s",
        body="b",
        valid_categories=VALID_CATEGORIES,
        client=client,
    )
    assert result is not None
    assert result.category == "active_client"


def test_classify_message_raises_without_categories(monkeypatch) -> None:
    import classifier.llm_classify as llm_classify_module

    # Force the `valid_categories or _load_category_names()` fallback to
    # also come up empty, exercising the "nothing to classify against" guard.
    monkeypatch.setattr(llm_classify_module, "_load_category_names", lambda *a, **k: [])
    client = _FakeClient(_response("news"))
    with pytest.raises(LLMClassificationError):
        classify_message(
            from_address="x@example.com",
            subject="s",
            body="b",
            valid_categories=[],
            client=client,
        )


def test_client_requires_api_key(monkeypatch) -> None:
    import classifier.llm_classify as m

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMClassificationError, match="ANTHROPIC_API_KEY"):
        m._client()


def test_load_category_names_missing_and_present(tmp_path) -> None:
    import classifier.llm_classify as m

    missing = tmp_path / "nope.yaml"
    assert m._load_category_names(missing) == []
    path = tmp_path / "actions.yaml"
    path.write_text("categories:\n  news: {}\n  social: {}\n")
    assert m._load_category_names(path) == ["news", "social"]


def test_parse_response_rejects_non_object() -> None:
    import classifier.llm_classify as m

    with pytest.raises(LLMClassificationError, match="JSON object"):
        m._parse_response_text("[1,2,3]")


def test_cost_usd_unknown_model() -> None:
    import classifier.llm_classify as m

    assert m._cost_usd("nope", 100, 50) == 0.0


def test_classify_message_bad_confidence_falls_back() -> None:
    client = _FakeClient(_response("news", confidence="not-a-number"))
    result = classify_message(
        from_address="x@example.com",
        subject="s",
        body="b",
        valid_categories=VALID_CATEGORIES,
        client=client,
    )
    assert result.confidence == 0.5
