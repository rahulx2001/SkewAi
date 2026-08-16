"""Email intake channel (feature #11).

IMAP poll is represented as ``poll_mailbox`` over a list of message dicts
(tests inject fixtures). Pre-extracts slots from body text, then produces a
single clarifying reply when required slots remain empty.
"""

from __future__ import annotations

import re
from typing import Any

from src.channels.base import ChannelAdapter, ChannelCapabilities


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_slots_from_email(
    subject: str,
    body: str,
    *,
    pack_slot_names: list[str] | None = None,
) -> dict[str, str]:
    """Heuristic pre-extraction for email → orchestrator slots."""
    text = f"{subject}\n{body}"
    slots: dict[str, str] = {}
    # Generic: description = first 500 chars of body
    slots["description"] = (body or subject or "").strip()[:500]
    # entity-ish tokens: ALLCAPS words, product codes
    makes = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", text)
    if makes:
        slots["entity_1"] = makes[0]
    if len(makes) > 1:
        slots["entity_2"] = makes[1]
    # year
    years = re.findall(r"\b(19|20)\d{2}\b", text)
    if years:
        slots["entity_3"] = years[0] if len(years[0]) == 4 else (years[0] + "")
        # fix full year match
        ym = re.search(r"\b((?:19|20)\d{2})\b", text)
        if ym:
            slots["entity_3"] = ym.group(1)
    # category keywords
    for kw in ("brake", "airbag", "fraud", "overdraft", "steering", "engine"):
        if kw in text.lower():
            slots["category"] = kw
            break
    if pack_slot_names:
        return {k: slots[k] for k in pack_slot_names if k in slots}
    return slots


def missing_required(slots: dict[str, str], required: list[str]) -> list[str]:
    return [s for s in required if not (slots.get(s) or "").strip()]


def clarifying_reply(missing: list[str], *, language: str = "en") -> str:
    if not missing:
        return "Thank you — we have everything we need and opened a case from your email."
    labels = ", ".join(missing)
    if language.startswith("es"):
        return f"Gracias por su correo. ¿Puede confirmar: {labels}?"
    return f"Thanks for your email. To finish intake, please reply with: {labels}."


class EmailIntakeChannel(ChannelAdapter):
    channel_name = "email"

    def __init__(self) -> None:
        self.outbox: list[dict[str, Any]] = []
        self.last_slots: dict[str, str] = {}

    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(voice=False, text=True, barge_in=False, server_tts=False)

    def process_message(
        self,
        *,
        subject: str,
        body: str,
        from_addr: str = "",
        required_slots: list[str] | None = None,
    ) -> dict[str, Any]:
        required = required_slots or ["entity_1", "description"]
        slots = extract_slots_from_email(subject, body)
        if from_addr and _EMAIL_RE.search(from_addr):
            slots["__contact_email"] = from_addr
        miss = missing_required(slots, required)
        reply = clarifying_reply(miss)
        self.last_slots = slots
        result = {
            "slots": slots,
            "missing": miss,
            "complete": len(miss) == 0,
            "reply": reply,
            "channel": "email",
        }
        self.outbox.append(result)
        return result

    def poll_mailbox(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process a batch of IMAP-like message dicts."""
        return [
            self.process_message(
                subject=str(m.get("subject") or ""),
                body=str(m.get("body") or ""),
                from_addr=str(m.get("from") or ""),
                required_slots=m.get("required_slots"),
            )
            for m in messages
        ]

    async def send_turn(self, text: str, *, speaker: str = "agent", meta: dict[str, Any] | None = None) -> None:
        self.outbox.append({"type": "email_reply", "text": text, "speaker": speaker})

    async def send_activity(self, payload: dict[str, Any]) -> None:
        self.outbox.append({"type": "activity", **payload})

    async def send_slots_update(self, slots: dict[str, str]) -> None:
        self.last_slots = dict(slots)

    async def send_handoff_offer(self) -> None:
        await self.send_turn("A specialist will email you shortly.")

    async def send_interaction_ended(self, payload: dict[str, Any]) -> None:
        self.outbox.append({"type": "interaction_ended", **payload})

    async def hangup(self) -> None:
        self.outbox.append({"type": "closed"})
