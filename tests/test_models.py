"""Unit tests for classifier.models (canonical message record)."""

from __future__ import annotations

from classifier.models import CanonicalMessage, Channel, Sender, TargetHub, Urgency


def test_models_defaults_and_enums():
    sender = Sender(display_name="Ada", address_or_number="ada@example.com", known_contact=True, relationship="client")
    msg = CanonicalMessage(
        message_id="m1",
        channel=Channel.EMAIL,
        received_at="2026-07-17T12:00:00Z",
        sender=sender,
        subject="Hello",
        body="Body",
        account="personal_hub",
        provenance_labels=["fwd"],
        category="news",
        subcategory="digest",
        target_hub=TargetHub.PERSONAL,
        urgency=Urgency.HIGH,
        suggested_action="label",
        confidence=0.9,
        source="rules",
    )
    assert msg.channel is Channel.EMAIL
    assert Channel.SMS.value == "sms"
    assert Channel.VOICE_VM.value == "voice_vm"
    assert Urgency.LOW.value == "low"
    assert TargetHub.SPLIT.value == "split"
    assert TargetHub.NONE.value == "n/a"
    assert msg.sender.known_contact is True
    assert msg.provenance_labels == ["fwd"]


def test_sender_defaults():
    s = Sender()
    assert s.display_name == ""
    assert s.relationship == "unknown"
