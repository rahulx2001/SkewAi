"""Engineer-registered diagnostic questions asked mid-contact + spoken confirm."""

from __future__ import annotations

import re
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
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_answers (
            answer_id      VARCHAR PRIMARY KEY,
            interaction_id VARCHAR NOT NULL,
            question_id    VARCHAR NOT NULL,
            prompt         TEXT NOT NULL,
            answer         TEXT NOT NULL,
            confirmed      BOOLEAN NOT NULL DEFAULT TRUE,
            created_at     TIMESTAMP NOT NULL
        )
        """
    )
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_diag_answers_qa "
            "ON diagnostic_answers (interaction_id, question_id)"
        )
    except Exception:
        pass


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


def next_question(
    pack_id: str,
    slots: dict[str, Any] | None = None,
    *,
    interaction_id: str | None = None,
) -> dict[str, Any] | None:
    """First matching unanswered question (item 35: no duplicate questioning).

    When ``interaction_id`` is given, questions already answered in this
    contact (see ``diagnostic_answers``) are skipped — the contact is never
    asked the same diagnostic question twice.
    """
    slots = slots or {}
    cat = (slots.get("category") or "").strip()
    ent = (slots.get("entity_2") or "").strip()
    answered: set[str] = set()
    if interaction_id:
        with ops_con(read_only=True) as con:
            try:
                _ensure(con)
                answered = {
                    str(r[0])
                    for r in con.execute(
                        "SELECT question_id FROM diagnostic_answers WHERE interaction_id = ?",
                        [interaction_id],
                    ).fetchall()
                }
            except Exception:
                answered = set()
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
        if str(qid) in answered:
            continue
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


def record_elicitation_answer(
    interaction_id: str,
    question_id: str,
    answer: str,
    *,
    prompt: str = "",
    confirmed: bool = True,
) -> dict[str, Any]:
    """Persist a diagnostic answer with provenance (item 35).

    Idempotent per (interaction, question): a repeated answer UPDATES the
    stored text rather than duplicating the question. Returns the record —
    investigators attach it to the brief, case agents to hypotheses.
    """
    aid = "da_" + new_ulid()
    with ops_con() as con:
        _ensure(con)
        existing = con.execute(
            "SELECT answer_id FROM diagnostic_answers WHERE interaction_id = ? AND question_id = ?",
            [interaction_id, question_id],
        ).fetchone()
        if existing:
            con.execute(
                """
                UPDATE diagnostic_answers
                SET answer = ?, prompt = ?, confirmed = ?, created_at = ?
                WHERE interaction_id = ? AND question_id = ?
                """,
                [answer.strip()[:1000], prompt[:500], confirmed, utc_now(),
                 interaction_id, question_id],
            )
            return {
                "answer_id": existing[0], "interaction_id": interaction_id,
                "question_id": question_id, "prompt": prompt,
                "answer": answer.strip()[:1000], "updated": True,
            }
        con.execute(
            """
            INSERT INTO diagnostic_answers
            (answer_id, interaction_id, question_id, prompt, answer, confirmed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [aid, interaction_id, question_id, prompt[:500],
             answer.strip()[:1000], confirmed, utc_now()],
        )
    return {
        "answer_id": aid, "interaction_id": interaction_id,
        "question_id": question_id, "prompt": prompt,
        "answer": answer.strip()[:1000], "updated": False,
    }


def answers_for_interaction(interaction_id: str) -> list[dict[str, Any]]:
    """All diagnostic answers for a contact, oldest first (brief attachment)."""
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
            cur = con.execute(
                """
                SELECT answer_id, question_id, prompt, answer, confirmed, created_at
                FROM diagnostic_answers WHERE interaction_id = ?
                ORDER BY created_at
                """,
                [interaction_id],
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []


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
    t = (text or "").strip().lower().rstrip(".!?").strip()
    if t in {"yes", "y", "correct", "yeah", "yep", "that's right", "that is right"}:
        return True
    if "correct" in t and "not" not in t:
        return True
    # "Yes, that's right." — yes-led with no correction cue.
    if re.match(r"^(yes|yeah|yep|y|correct)[,!\s]", t):
        if not re.search(r"\b(but|actually|however|though|no\b|not|wrong|instead|rather)\b", t):
            return True
    return False


__all__ = [
    "register_question",
    "next_question",
    "record_spoken_confirmation",
    "record_elicitation_answer",
    "answers_for_interaction",
    "looks_like_confirmation",
]
