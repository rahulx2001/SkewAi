"""Backward-compatible export — real adapter lives in twilio_media.py.

Historical name ``twilio_stub`` remains importable; it no longer raises on
construct. Prefer ``from src.channels.twilio_media import TwilioMediaChannel``.
"""

from __future__ import annotations

from src.channels.twilio_media import TwilioChannel, TwilioMediaChannel

__all__ = ["TwilioChannel", "TwilioMediaChannel"]
