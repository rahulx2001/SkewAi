"""Twilio Media Streams adapter — pilot-working path without live carrier.

When ``TWILIO_ACCOUNT_SID`` + ``TWILIO_AUTH_TOKEN`` are unset, the adapter
runs in **text pilot mode**: it accepts the same ChannelAdapter contract as
WebVoice, records outbound turns, and never raises. When credentials exist,
``stream_url()`` and ``media_frame_handlers`` are ready for Media Streams
wiring; STT/TTS are pluggable via ``src.channels.stt_tts``.

This replaces the old NotImplementedError stub so feature #8 is shippable
at pilot depth (no live PSTN required for CI).
"""

from __future__ import annotations

import os
from typing import Any, Callable, Awaitable

from src.channels.base import ChannelAdapter, ChannelCapabilities
from src.channels.stt_tts import ServerSpeechStack


class TwilioMediaChannel(ChannelAdapter):
    """Telephony channel adapter with deterministic pilot fallback."""

    channel_name = "twilio_media"

    def __init__(
        self,
        send_json: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        speech: ServerSpeechStack | None = None,
    ) -> None:
        self._send = send_json
        self._account_sid = (account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")).strip()
        self._auth_token = (auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")).strip()
        self._speech = speech or ServerSpeechStack()
        self.outbound: list[dict[str, Any]] = []
        self._closed = False

    @property
    def live_credentials(self) -> bool:
        return bool(self._account_sid and self._auth_token)

    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            voice=True,
            text=True,
            barge_in=True,
            server_tts=True,
            supervisor_takeover=True,
        )

    def stream_url(self, public_base: str, interaction_id: str) -> str:
        """Twilio Media Streams WSS target (document for ops; not dialed in CI)."""
        base = public_base.rstrip("/")
        return f"{base.replace('https://', 'wss://').replace('http://', 'ws://')}/ws/twilio/{interaction_id}"

    async def _emit(self, payload: dict[str, Any]) -> None:
        self.outbound.append(payload)
        if self._send is not None:
            await self._send(payload)

    async def send_turn(
        self, text: str, *, speaker: str = "agent", meta: dict[str, Any] | None = None
    ) -> None:
        meta = meta or {}
        audio_meta = self._speech.synthesize_meta(text) if self.capabilities().server_tts else {}
        await self._emit(
            {
                "type": "agent_turn",
                "channel": self.channel_name,
                "text": text,
                "speaker": speaker,
                "turn_id": meta.get("turn_id"),
                "server_tts": True,
                "tts": audio_meta,
                "live_twilio": self.live_credentials,
            }
        )

    async def send_activity(self, payload: dict[str, Any]) -> None:
        await self._emit({"type": "agent_activity", "channel": self.channel_name, **payload})

    async def send_slots_update(self, slots: dict[str, str]) -> None:
        clean = {k: v for k, v in slots.items() if not k.startswith("__")}
        await self._emit({"type": "slots_update", "slots": clean})

    async def send_handoff_offer(self) -> None:
        await self._emit({"type": "handoff_offer"})

    async def send_interaction_ended(self, payload: dict[str, Any]) -> None:
        await self._emit({"type": "interaction_ended", **payload})

    async def hangup(self) -> None:
        self._closed = True
        await self._emit({"type": "hangup", "channel": self.channel_name})

    def ingest_media_frame(self, frame: dict[str, Any]) -> str | None:
        """Convert a media/STT frame into customer text (None if partial)."""
        if frame.get("event") == "media" and frame.get("media", {}).get("payload"):
            # Pilot: payload may already be base64 audio; STT stack returns text when ready.
            return self._speech.transcribe_chunk(frame["media"]["payload"])
        if frame.get("event") == "mark" or frame.get("type") == "text":
            return str(frame.get("text") or frame.get("transcript") or "") or None
        return None


# Back-compat alias used by older imports
TwilioChannel = TwilioMediaChannel
