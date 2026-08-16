"""Supervisor whisper / coach mode (feature #53).

Suggest replies during takeover; private coach text to an agent mid-call.
"""

from __future__ import annotations

from typing import Any

from src.data.warehouse import ops_con
from src.ids import new_ulid


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS coach_messages (
            message_id VARCHAR PRIMARY KEY,
            interaction_id VARCHAR NOT NULL,
            from_role VARCHAR,
            to_role VARCHAR,
            kind VARCHAR,
            text VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def suggest_replies(
    *,
    slots: dict[str, str] | None = None,
    last_customer_text: str = "",
    severity: str | None = None,
) -> list[dict[str, str]]:
    """Deterministic coach suggestions for supervisor takeover."""
    slots = slots or {}
    suggestions = []
    if last_customer_text:
        suggestions.append(
            {
                "id": "ack",
                "text": f"I hear you about \"{last_customer_text[:80]}\". Let me pull up the details.",
            }
        )
    ent = slots.get("entity_1") or slots.get("entity_2")
    if ent:
        suggestions.append(
            {
                "id": "entity",
                "text": f"Confirming this is about {ent} — is that right?",
            }
        )
    if (severity or "").lower() in {"critical", "p1", "high"}:
        suggestions.append(
            {
                "id": "safety",
                "text": "For your safety, please stop using the product until we complete this case.",
            }
        )
    suggestions.append(
        {
            "id": "close",
            "text": "I'll open a case and make sure the right team follows up within one business day.",
        }
    )
    return suggestions


def whisper(
    interaction_id: str,
    text: str,
    *,
    from_role: str = "coach",
    to_role: str = "agent",
) -> dict[str, Any]:
    mid = f"coach_{new_ulid()}"
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO coach_messages
              (message_id, interaction_id, from_role, to_role, kind, text)
            VALUES (?, ?, ?, ?, 'whisper', ?)
            """,
            [mid, interaction_id, from_role, to_role, text],
        )
    try:
        from src.ledger import AgentAction, record_action

        record_action(
            AgentAction(
                interaction_id=interaction_id,
                agent="supervisor",
                action_type="coach_whisper",
                input_summary=f"{from_role}->{to_role}",
                output_summary=text[:500],
                ok=True,
            )
        )
        ledgered = True
    except Exception:
        ledgered = False
    return {
        "message_id": mid,
        "interaction_id": interaction_id,
        "kind": "whisper",
        "from_role": from_role,
        "to_role": to_role,
        "text": text,
        "private": True,
        "ledgered": ledgered,
    }


def list_whispers(interaction_id: str) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
            rows = con.execute(
                """
                SELECT message_id, from_role, to_role, kind, text, created_at
                FROM coach_messages WHERE interaction_id = ?
                ORDER BY created_at ASC
                """,
                [interaction_id],
            ).fetchall()
        except Exception:
            return []
    cols = ["message_id", "from_role", "to_role", "kind", "text", "created_at"]
    return [dict(zip(cols, r)) for r in rows]
