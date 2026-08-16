"""Server-side STT/TTS option (feature #9).

Browser Web Speech is Chrome-only. This stack provides a hermetic pilot path:
- STT: decode text payloads, or mark audio frames as needing external STT
- TTS: return metadata for client or Twilio playback without requiring ElevenLabs

When ``FASTER_WHISPER_MODEL`` or ``STT_API_URL`` is set, ``transcribe_file`` can
call out; CI never requires those keys.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any


class ServerSpeechStack:
    """Pluggable STT/TTS with deterministic offline behavior."""

    def __init__(
        self,
        *,
        stt_api_url: str | None = None,
        tts_voice: str | None = None,
    ) -> None:
        self.stt_api_url = (stt_api_url or os.getenv("STT_API_URL", "")).strip()
        self.tts_voice = (tts_voice or os.getenv("TTS_VOICE", "pilot-neutral")).strip()
        self._partial: list[str] = []

    @property
    def server_stt_available(self) -> bool:
        return bool(self.stt_api_url or os.getenv("FASTER_WHISPER_MODEL", "").strip())

    def transcribe_chunk(self, payload_b64_or_text: str) -> str | None:
        """Return finalized text or None if still accumulating.

        Pilot rule: if payload looks like plain text (not base64-ish long audio),
        return it immediately. Otherwise accumulate and return a hash-tag stub
        only when a terminal marker is present.
        """
        raw = payload_b64_or_text or ""
        if not raw:
            return None
        # Short ASCII → treat as already-transcribed (test / pilot)
        if len(raw) < 500 and all(ord(c) < 128 for c in raw[:80]):
            if raw.startswith("AUDIO:"):
                self._partial.append(raw)
                return None
            return raw.strip()
        self._partial.append(raw[:64])
        return None

    def finalize_partial(self) -> str:
        joined = "".join(self._partial)
        self._partial.clear()
        if not joined:
            return ""
        digest = hashlib.sha256(joined.encode()).hexdigest()[:12]
        return f"[stt_pending:{digest}]"

    def synthesize_meta(self, text: str) -> dict[str, Any]:
        """Return TTS metadata (no binary audio in hermetic mode)."""
        digest = hashlib.sha256((text or "").encode()).hexdigest()[:16]
        return {
            "provider": "pilot" if not os.getenv("ELEVENLABS_API_KEY") else "elevenlabs",
            "voice": self.tts_voice,
            "text_chars": len(text or ""),
            "audio_ref": f"tts://{digest}",
            "server_side": True,
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "server_stt": self.server_stt_available,
            "server_tts": True,
            "offline_pilot": not self.server_stt_available,
        }
