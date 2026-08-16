"""Channel adapters — the orchestrator talks only to `ChannelAdapter`.

Public API:
    from src.channels import ChannelAdapter, ChannelCapabilities
    from src.channels import WebVoiceChannel, SimulatedChannel
"""

from src.channels.base import ChannelAdapter, ChannelCapabilities
from src.channels.email_intake import EmailIntakeChannel
from src.channels.messaging import MessagingChannel, SmsChannel, WhatsAppChannel
from src.channels.simulated import SimulatedChannel
from src.channels.stt_tts import ServerSpeechStack
from src.channels.twilio_media import TwilioMediaChannel
from src.channels.web_voice import WebVoiceChannel

__all__ = [
    "ChannelAdapter",
    "ChannelCapabilities",
    "WebVoiceChannel",
    "SimulatedChannel",
    "TwilioMediaChannel",
    "ServerSpeechStack",
    "MessagingChannel",
    "SmsChannel",
    "WhatsAppChannel",
    "EmailIntakeChannel",
]
