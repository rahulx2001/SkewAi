"""WhatsApp / SMS channel adapters (feature #10).

Async turn model (not realtime media). Uses the same ChannelAdapter contract.
Outbound messages go to an in-memory outbox + optional webhook (SSRF-guarded
elsewhere when HTTP is enabled).
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from src.channels.base import ChannelAdapter, ChannelCapabilities


class MessagingChannel(ChannelAdapter):
    """Shared base for SMS and WhatsApp."""

    channel_name = "messaging"

    def __init__(
        self,
        *,
        channel: str = "sms",
        to_address: str = "",
        send_hook: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.channel_name = channel  # sms | whatsapp
        self.to_address = to_address
        self._send_hook = send_hook
        self.outbox: list[dict[str, Any]] = []
        self.inbound_queue: list[str] = []

    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            voice=False,
            text=True,
            barge_in=False,
            server_tts=False,
            supervisor_takeover=True,
        )

    async def _emit(self, payload: dict[str, Any]) -> None:
        payload = {**payload, "channel": self.channel_name, "to": self.to_address}
        self.outbox.append(payload)
        if self._send_hook:
            await self._send_hook(payload)

    async def send_turn(
        self, text: str, *, speaker: str = "agent", meta: dict[str, Any] | None = None
    ) -> None:
        await self._emit(
            {
                "type": "message",
                "text": text,
                "speaker": speaker,
                "meta": meta or {},
            }
        )

    async def send_activity(self, payload: dict[str, Any]) -> None:
        # Messaging channels do not surface activity cards to the customer.
        self.outbox.append({"type": "activity_suppressed", **payload})

    async def send_slots_update(self, slots: dict[str, str]) -> None:
        clean = {k: v for k, v in slots.items() if not k.startswith("__")}
        self.outbox.append({"type": "slots_internal", "slots": clean})

    async def send_handoff_offer(self) -> None:
        await self.send_turn(
            "A human agent can take over this conversation if you prefer. Reply YES for a human."
        )

    async def send_interaction_ended(self, payload: dict[str, Any]) -> None:
        case_id = payload.get("case_id") or ""
        await self.send_turn(
            f"Thanks — we've logged your case{(' ' + case_id) if case_id else ''}. You'll get a follow-up here."
        )
        self.outbox.append({"type": "interaction_ended", **payload})

    async def hangup(self) -> None:
        self.outbox.append({"type": "session_closed", "channel": self.channel_name})

    def receive_inbound(self, text: str) -> str:
        """Queue an inbound customer message; return normalized text for orchestrator."""
        t = (text or "").strip()
        self.inbound_queue.append(t)
        return t


class SmsChannel(MessagingChannel):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(channel="sms", **kwargs)


class WhatsAppChannel(MessagingChannel):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(channel="whatsapp", **kwargs)
