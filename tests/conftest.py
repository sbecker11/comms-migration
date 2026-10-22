import pytest

from classifier import llm_verdict_cache


@pytest.fixture(autouse=True)
def _isolated_llm_verdicts(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_verdict_cache, "STATE_DIR", tmp_path / "llm-verdicts")
    monkeypatch.setenv("LLM_CALL_LOG", str(tmp_path / "llm-calls.jsonl"))
