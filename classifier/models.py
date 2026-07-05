"""Canonical message record — Appendix B of comms-migration-runbook.md.

Every channel (email today, voice/SMS eventually) normalizes into this
record before the rule engine or LLM classifier looks at it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Channel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    VOICE_VM = "voice_vm"


class Urgency(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TargetHub(str, Enum):
    PROFESSIONAL = "professional"
    PERSONAL = "personal"
    SPLIT = "split"
    NONE = "n/a"


@dataclass
class Sender:
    display_name: str = ""
    address_or_number: str = ""
    known_contact: bool = False
    relationship: str = "unknown"  # client | recruiter | vendor | personal | unknown


@dataclass
class CanonicalMessage:
    """Appendix B canonical record."""

    message_id: str
    channel: Channel
    received_at: str  # ISO-8601
    sender: Sender
    subject: str = ""
    body: str = ""
    thread_id: str = ""

    # Provenance — which of the mapped accounts this arrived through, and
    # (for forwarded mail) which original address the sender actually used.
    account: str = ""  # e.g. "scbboston_gmail", "recruiting_funnel"
    provenance_labels: list[str] = field(default_factory=list)

    # Assigned by the rule engine / LLM classifier.
    category: str | None = None
    subcategory: str | None = None
    target_hub: TargetHub | None = None
    urgency: Urgency = Urgency.NORMAL
    suggested_action: str | None = None
    confidence: float = 0.0
    source: str = "unclassified"  # "rules" | "llm" | "unclassified"
