"""Log supervisor disagreements with lexicon sentiment / handoff.

Do not train a sentiment model until SENTIMENT_REVISIT_N reviewed rows exist.
"""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

SENTIMENT_REVISIT_N = 300

DDL = """
CREATE TABLE IF NOT EXISTS sentiment_disagreements (
    review_id VARCHAR PRIMARY KEY,
    interaction_id VARCHAR NOT NULL,
    human_decision VARCHAR NOT NULL,
    system_sentiment_score DOUBLE,
    system_handoff_decision BOOLEAN,
    reviewer_comment VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp
)
"""


def log_sentiment_disagreement(
    *,
    interaction_id: str,
    human_decision: str,
    system_sentiment_score: float | None,
    system_handoff_decision: bool | None,
    reviewer_comment: str = "",
) -> str:
    rid = "srev_" + new_ulid()
    with ops_con() as con:
        con.execute(DDL)
        con.execute(
            """
            INSERT INTO sentiment_disagreements (
                review_id, interaction_id, human_decision, system_sentiment_score,
                system_handoff_decision, reviewer_comment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                rid,
                interaction_id,
                human_decision,
                system_sentiment_score,
                system_handoff_decision,
                (reviewer_comment or "")[:500],
                utc_now().replace(tzinfo=None),
            ],
        )
    return rid


def disagreement_count() -> int:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute("SELECT COUNT(*) FROM sentiment_disagreements").fetchone()
        except Exception:
            return 0
    return int(row[0] if row else 0)


def revisit_ready() -> bool:
    return disagreement_count() >= SENTIMENT_REVISIT_N
