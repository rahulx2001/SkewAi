"""Simulated channel — in-process adapter for the traffic simulator + eval.

Replays corpus records as scripted contacts through the real orchestrator
without any WebSocket, browser, or LLM. Captures all output for assertions.

This is the deterministic path for tests/eval: same agents, same ledger, same
audits as the live voice channel, but guaranteed LLM-free and $0.
"""

from __future__ import annotations

from typing import Any

from src.channels.base import ChannelAdapter, ChannelCapabilities


class SimulatedChannel(ChannelAdapter):
    """In-process adapter that records output instead of emitting over a socket."""

    channel_name = "simulated"

    def __init__(self) -> None:
        # Captured output for assertions / replay inspection.
        self.turns: list[dict[str, Any]] = []          # agent/supervisor turns
        self.activities: list[dict[str, Any]] = []
        self.slots_updates: list[dict[str, str]] = []
        self.handoff_offers: int = 0
        self.ended: dict[str, Any] | None = None
        self.hung_up: bool = False

    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            voice=False,
            text=True,
            barge_in=False,
            server_tts=False,
            supervisor_takeover=True,
        )

    async def send_turn(self, text: str, *, speaker: str = "agent", meta: dict[str, Any] | None = None) -> None:
        self.turns.append({"speaker": speaker, "text": text, "meta": meta or {}})

    async def send_activity(self, payload: dict[str, Any]) -> None:
        self.activities.append(dict(payload))

    async def send_slots_update(self, slots: dict[str, str]) -> None:
        self.slots_updates.append({k: v for k, v in slots.items() if not k.startswith("__")})

    async def send_handoff_offer(self) -> None:
        self.handoff_offers += 1

    async def send_interaction_ended(self, payload: dict[str, Any]) -> None:
        self.ended = dict(payload)

    async def hangup(self) -> None:
        self.hung_up = True

    # ── Assertion helpers ─────────────────────────────────────────────────
    def agent_texts(self) -> list[str]:
        return [t["text"] for t in self.turns if t["speaker"] == "agent"]

    def full_transcript(self) -> str:
        return "\n".join(f"[{t['speaker']}] {t['text']}" for t in self.turns)
