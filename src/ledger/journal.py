"""Agent action journal and voice playback reconciliation."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AgentActionJournal:
    """Journal tracking action lifecycle, including mid-utterance audio interruptions."""

    def __init__(self, db_con: Any = None) -> None:
        self._con = db_con
        self.truncations: list[dict[str, Any]] = []

    def record_action_truncation(
        self,
        *,
        interaction_id: str,
        action_id: str,
        spoken_text: str,
        interrupted_at_ms: int,
    ) -> str | None:
        """Record an append-only compensating action row to preserve cryptographic hash chain integrity."""
        record = {
            "interaction_id": interaction_id,
            "action_id": action_id,
            "spoken_text": spoken_text,
            "interrupted_at_ms": interrupted_at_ms,
        }
        self.truncations.append(record)

        try:
            from src.ledger.writer import AgentAction, record_action

            truncation_action = AgentAction(
                interaction_id=interaction_id,
                agent="voice_reconciler",
                action_type="spoken_turn_truncated",
                input_summary=f"target_action_id={action_id} interrupted_at_ms={interrupted_at_ms}",
                output_summary=spoken_text[:500],
                evidence_ids=[action_id],
                ok=True,
            )
            new_action_id = record_action(truncation_action)
            logger.info(
                "action_truncation_appended",
                extra={
                    "interaction_id": interaction_id,
                    "target_action_id": action_id,
                    "truncation_action_id": new_action_id,
                    "interrupted_at_ms": interrupted_at_ms,
                },
            )
            return new_action_id
        except Exception as e:
            logger.debug("action_truncation_append_skipped", extra={"error": str(e)})
            return None
