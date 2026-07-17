"""LLM fallback categorization for senders the rule engine can't resolve.

Only called for the tail of unknown/ambiguous senders — `rules_engine.py`
handles known contacts and known bulk-mail domains for free. This keeps
per-message cost near zero for the bulk of recurring mail while still
covering new/one-off senders.

Uses Claude Haiku: this is a high-volume, low-complexity classification
task (pick one of ~13 fixed categories), not a nuanced judgment call, so
the cheapest capable model is the right default.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("COMMS_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5")
MAX_BODY_CHARS = 4_000

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ACTIONS_PATH = REPO_ROOT / "rules" / "actions.yaml"

# claude-haiku-4-5 pricing (USD per million tokens). Update if pricing changes.
_MODEL_PRICING_USD_PER_MTOK = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}


@dataclass
class ClassificationResult:
    category: str
    subcategory: str | None
    confidence: float
    rationale: str
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_s: float = 0.0
    cost_usd: float = 0.0


class LLMClassificationError(RuntimeError):
    """Raised when the LLM call fails or returns unusable output."""


def _client():
    import anthropic  # imported lazily so `anthropic` is only required when this path is used

    api_key = os.environ.get("ANTHROPIC_API_KEY")  # pragma: allowlist secret
    if not api_key:
        raise LLMClassificationError(
            "ANTHROPIC_API_KEY is not set. Add it to comms-migration/.env (see .env.example)."
        )
    return anthropic.Anthropic(api_key=api_key)  # pragma: allowlist secret


def _load_category_names(actions_path: Path = DEFAULT_ACTIONS_PATH) -> list[str]:
    if not actions_path.exists():
        return []
    with actions_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list((data.get("categories") or {}).keys())


def _build_system_prompt(categories: list[str]) -> str:
    category_list = "\n".join(f"- {c}" for c in categories)
    return f"""You classify a single email into exactly one category for a personal \
communications triage system.

Valid categories (use exactly one of these strings, nothing else):
{category_list}

**Classify by the message's INTENT/PURPOSE, not by surface topic keywords.**
The single most common mistake is matching on subject-line/topic words instead
of asking "why was this email actually sent?" Two emails can mention the same
topic (e.g. "stocks", "your account") for completely different reasons:
  - A brokerage's actual trade confirmation or statement -> transactional intent.
  - A newsletter/blog using stock-market drama as clickbait to sell a
    subscription or course -> marketing/content intent, even though it
    "sounds financial."
Always classify by the second question, never the first.

Guidance per category, in priority order (check these before anything else):
- "security_alert": ALWAYS use this — overriding any other category below —
  for account sign-in/new-device notices, password reset/change
  confirmations, 2FA/MFA codes, "verify it's you" prompts, or
  suspicious-activity/account-recovery warnings, from ANY sender (Google,
  Apple, Microsoft, a bank, a social network, etc.). These must never be
  filed under financial_admin, billing, or any topic-based category just
  because the sender is a bank or the content mentions an account —
  intent (a security/identity event) always wins over sender identity.
- "financial_admin" / "investing" / "billing" / "insurance": only for an
  actual administrative/transactional notice **from an entity you hold an
  account/policy/subscription with** — a statement, trade confirmation,
  invoice, payment receipt, policy document, or account notice. A
  newsletter, blog, or promotional email that merely *discusses* investing,
  banking, or insurance topics (market commentary, "hot stock" tips,
  financial advice content, insurance-comparison marketing) is NOT this —
  classify those as "news" (if genuinely journalistic/informational) or
  "spam_unknown" (if promotional/clickbait), based on intent, not topic.
- "vendor_transactional": receipts, order confirmations, shipping/delivery
  notices only — NOT general marketing/promotional email from a company
  you've bought from before (that's spam_unknown, or news/social/ai if it
  fits one of those better).
- "news": genuine news-outlet or subscribed news-digest content — NOT
  generic lifestyle-blog, self-help, or content-farm marketing newsletters
  that merely use a news-style format to sell something.
- "active_client" / "recruiter_job": only if the email is clearly business \
correspondence from a known-relationship sender or an actual recruiting/job \
posting message. Most mail is NOT this.
- "spam_unknown": the correct default for promotional/marketing content of
  any topic once you've ruled out the categories above — not just for
  "genuinely unrecognizable" senders.
- Prefer the most specific matching category over a vague catch-all.
- Never invent a category not in the list above.

Respond with ONLY a raw JSON object (no markdown fences, no prose), with \
exactly these keys:
  "category": one of the valid category strings above
  "subcategory": short free-text refinement, or "" if none applies
  "confidence": number 0.0-1.0
  "rationale": one short sentence explaining the call — state the message's
    intent/purpose, not just its topic
"""


def _build_user_prompt(*, from_address: str, subject: str, body: str) -> str:
    return (
        f"From: {from_address}\n"
        f"Subject: {subject}\n"
        "---- BODY START ----\n"
        f"{body[:MAX_BODY_CHARS]}\n"
        "---- BODY END ----"
    )


def _parse_response_text(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise LLMClassificationError(f"expected a JSON object, got {type(data).__name__}")
    return data


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _MODEL_PRICING_USD_PER_MTOK.get(model)
    if not pricing:
        return 0.0
    return (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]


def classify_message(
    *,
    from_address: str,
    subject: str,
    body: str,
    valid_categories: list[str] | None = None,
    model: str = DEFAULT_MODEL,
    client=None,
) -> ClassificationResult:
    """Classify one message. Raises LLMClassificationError on any failure —
    callers should catch this and fall back to `spam_unknown` or leave the
    message unclassified for manual review, rather than guessing.
    """
    categories = valid_categories or _load_category_names()
    if not categories:
        raise LLMClassificationError("No categories loaded from rules/actions.yaml")

    client = client or _client()
    system_prompt = _build_system_prompt(categories)
    user_prompt = _build_user_prompt(from_address=from_address, subject=subject, body=body)

    max_tokens = 512
    est_in = max(1, (len(system_prompt) + len(user_prompt) + 3) // 4)
    est_out = max(64, min(max_tokens, max_tokens // 4))
    pred = _cost_usd(model, est_in, est_out)
    print(
        f"    [llm classify] pred ~${pred:.4f} (est. {est_in} in / ~{est_out} out)",
        flush=True,
    )

    start = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    elapsed_s = time.monotonic() - start

    raw_text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    try:
        data = _parse_response_text(raw_text)
    except (json.JSONDecodeError, LLMClassificationError) as exc:
        raise LLMClassificationError(f"unparseable LLM response: {raw_text!r}") from exc

    category = str(data.get("category") or "").strip()
    if category not in categories:
        raise LLMClassificationError(f"LLM returned unknown category: {category!r}")

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(confidence, 1.0))

    cost = _cost_usd(model, input_tokens, output_tokens)
    print(
        f"    [llm classify] actual ~${cost:.4f} "
        f"({input_tokens} in / {output_tokens} out, {elapsed_s:.1f}s)",
        flush=True,
    )
    return ClassificationResult(
        category=category,
        subcategory=(str(data.get("subcategory") or "").strip() or None),
        confidence=confidence,
        rationale=str(data.get("rationale") or "").strip(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_s=elapsed_s,
        cost_usd=cost,
    )


def classify_message_safe(
    *,
    from_address: str,
    subject: str,
    body: str,
    valid_categories: list[str] | None = None,
    model: str = DEFAULT_MODEL,
    client=None,
) -> ClassificationResult | None:
    """Same as `classify_message` but swallows failures and returns None,
    for batch runs where one bad message shouldn't halt the run.
    """
    try:
        return classify_message(
            from_address=from_address,
            subject=subject,
            body=body,
            valid_categories=valid_categories,
            model=model,
            client=client,
        )
    except Exception:
        logger.warning("LLM classification failed for sender %s", from_address, exc_info=True)
        return None
