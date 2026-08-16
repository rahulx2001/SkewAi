"""Engineer-registered diagnostic questions asked mid-contact + spoken confirm."""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.ledger import AgentAction, record_action


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_questions (
            question_id    VARCHAR PRIMARY KEY,
            pack_id        VARCHAR NOT NULL,
            prompt         TEXT NOT NULL,
            category       VARCHAR,
            entity_2       VARCHAR,
            created_at     TIMESTAMP NOT NULL
        )
        """
    )


def register_question(
    pack_id: str,
    prompt: str,
    *,
    category: str | None = None,
    entity_2: str | None = None,
) -> dict[str, Any]:
    qid = "dq_" + new_ulid()
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO diagnostic_questions
            (question_id, pack_id, prompt, category, entity_2, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [qid, pack_id, prompt.strip(), category, entity_2, utc_now()],
        )
    return {
        "question_id": qid,
        "pack_id": pack_id,
        "prompt": prompt.strip(),
        "category": category,
        "entity_2": entity_2,
    }


def next_question(pack_id: str, slots: dict[str, Any] | None = None) -> dict[str, Any] | None:
    slots = slots or {}
    cat = (slots.get("category") or "").strip()
    ent = (slots.get("entity_2") or "").strip()
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT question_id, prompt, category, entity_2
                FROM diagnostic_questions WHERE pack_id = ?
                ORDER BY created_at
                """,
                [pack_id],
            ).fetchall()
        except Exception:
            return None
    for qid, prompt, qcat, qent in rows:
        if qcat and cat and str(qcat) != cat:
            continue
        if qent and ent and str(qent) != ent:
            continue
        return {
            "question_id": qid,
            "prompt": prompt,
            "category": qcat,
            "entity_2": qent,
        }
    return None


def record_spoken_confirmation(
    interaction_id: str,
    utterance: str,
    *,
    confirmed: bool,
    question_id: str | None = None,
) -> str:
    """Ledger a hash-chained spoken confirmation (read-back)."""
    return record_action(
        AgentAction(
            interaction_id=interaction_id,
            agent="orchestrator",
            action_type="spoken_confirmation",
            input_summary=(question_id or "")[:200],
            output_summary=f"confirmed={confirmed}; utterance={utterance[:400]}",
            # question_id is not a warehouse row — citing dq_* makes Qubot red.
            evidence_ids=[],
            ok=True,
        )
    )


def looks_like_confirmation(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"yes", "y", "correct", "yeah", "yep", "that's right", "that is right"} or (
        "correct" in t and "not" not in t
    )


__all__ = [
    "register_question",
    "next_question",
    "record_spoken_confirmation",
    "looks_like_confirmation",
]
