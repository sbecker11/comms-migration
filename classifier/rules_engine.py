"""Layer 2 + Layer 3 rule lookups: sender -> (hub, category).

Combines:
  - `rules/senders.yaml` (Layer 2, generated, gitignored/PII) -> hub
  - `rules/rules.yaml`    (Layer 3, committed, no PII)         -> category,
     via the Mail.app-style rule engine in `classifier/rules_v2_engine.py`
  - `rules/actions.yaml`  (Layer 3 policy, committed)          -> action

Returns `None` category when nothing matches, signaling the caller to fall
back to the LLM classifier (`classifier/llm_classify.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from classifier import rules_v2_engine
from classifier.rules_v2_engine import MessageFields

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SENDERS_PATH = REPO_ROOT / "rules" / "senders.yaml"
DEFAULT_RULES_PATH = rules_v2_engine.DEFAULT_RULES_PATH
DEFAULT_ACTIONS_PATH = REPO_ROOT / "rules" / "actions.yaml"


@dataclass
class RuleMatch:
    category: str
    target_hub: str
    default_action: str
    human_in_loop: bool
    sensitivity: str
    matched_on: str  # "rules" | "senders_known_professional" | "senders_known_personal"
    confidence: float = 1.0


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _email_domain(email: str) -> str | None:
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    return email.rsplit("@", 1)[1]


def _domain_matches(sender_domain: str | None, registered_domain: str) -> bool:
    """True if sender_domain is registered_domain or a subdomain of it.

    Bulk mail almost always ships from tracking subdomains (e.g.
    `rs.email.nextdoor.com` for `nextdoor.com`), so exact equality alone
    misses most real traffic — every miss here is a wasted, billed LLM call.
    Uses a `.`-boundary suffix check so `notnextdoor.com` does NOT
    incorrectly match `nextdoor.com`.
    """
    return rules_v2_engine.domain_matches(sender_domain, registered_domain)


class RulesEngine:
    def __init__(
        self,
        *,
        senders_path: Path = DEFAULT_SENDERS_PATH,
        rules_path: Path = DEFAULT_RULES_PATH,
        actions_path: Path = DEFAULT_ACTIONS_PATH,
    ) -> None:
        self.senders = _load_yaml(senders_path)
        self.rules = rules_v2_engine.load_rules(rules_path, actions_path=actions_path)
        self.actions = (_load_yaml(actions_path) or {}).get("categories", {})

    def action_for_category(self, category: str) -> dict[str, Any]:
        return self.actions.get(category, self.actions.get("spam_unknown", {}))

    def _known_hub(self, email: str) -> str | None:
        email_lc = (email or "").strip().lower()
        domain = _email_domain(email)
        for override in self.senders.get("overrides", []) or []:
            if override.get("match", "").lower() == email_lc:
                return override.get("hub")
        for hub in ("professional", "personal"):
            hub_data = self.senders.get(hub, {}) or {}
            if email_lc in (hub_data.get("emails") or []):
                return hub
            if any(_domain_matches(domain, d) for d in (hub_data.get("domains") or [])):
                return hub
        return None

    @staticmethod
    def _build_message(
        from_address: str,
        *,
        to_address: str = "",
        cc_address: str = "",
        subject: str = "",
        body: str = "",
        date_sent: str = "",
        date_received: str = "",
    ) -> MessageFields:
        return MessageFields(
            from_address=from_address,
            to_address=to_address,
            cc_address=cc_address,
            subject=subject,
            body=body,
            date_sent=date_sent,
            date_received=date_received,
        )

    def all_rule_hits(self, from_address: str, **kwargs: str) -> list[str]:
        """Every active rule's description that matches this message,
        independent of rule order — see `rules_v2_engine.all_rule_hits`.
        Diagnostic-only: `classify()` below is what actually determines
        the category acted on.
        """
        message = self._build_message(from_address, **kwargs)
        return rules_v2_engine.all_rule_hits(self.rules, message)

    def classify(
        self,
        from_address: str,
        *,
        to_address: str = "",
        cc_address: str = "",
        subject: str = "",
        body: str = "",
        date_sent: str = "",
        date_received: str = "",
    ) -> RuleMatch | None:
        """Resolve a message to a category via rules only (no LLM). None = unresolved.

        `from_address` is the only required field (existing call sites and
        tests only ever had that available); the rest are optional and only
        matter for rules/rules.yaml expressions that reference to/cc/subject/
        body/date fields — most rules today are still from/from_url_pattern-only.
        """
        message = self._build_message(
            from_address,
            to_address=to_address,
            cc_address=cc_address,
            subject=subject,
            body=body,
            date_sent=date_sent,
            date_received=date_received,
        )
        category = rules_v2_engine.match_rules(self.rules, message)
        matched_on = "rules"

        if category is None:
            hub = self._known_hub(from_address)
            if hub == "professional":
                category, matched_on = "active_client", "senders_known_professional"
            elif hub == "personal":
                category, matched_on = "personal", "senders_known_personal"

        if category is None:
            return None

        action = self.action_for_category(category)
        return RuleMatch(
            category=category,
            target_hub=action.get("target_hub", "n/a"),
            default_action=action.get("default_action", "flag"),
            human_in_loop=bool(action.get("human_in_loop", True)),
            sensitivity=action.get("sensitivity", "low"),
            matched_on=matched_on,
        )
