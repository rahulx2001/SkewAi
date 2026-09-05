"""Sample unlabeled complaint pairs for human annotation.

Does not assign a class. Humans choose the sampling strategy at the CLI;
the tool never writes a label.
"""

from __future__ import annotations

import random
from typing import Any

from src.data.warehouse import domain_con
from src.eval.embedding_labels import enqueue_unlabeled_item


def _load_records(pack_id: str, limit: int = 400) -> list[dict[str, Any]]:
    with domain_con(pack_id, read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT record_id, text, category, entity_2, entity_3
                FROM records
                WHERE text IS NOT NULL AND length(trim(text)) > 8
                ORDER BY record_id
                LIMIT ?
                """,
                [int(limit)],
            ).fetchall()
        except Exception:
            return []
    return [
        {
            "record_id": str(r[0]),
            "text": str(r[1] or ""),
            "category": r[2],
            "entity_2": r[3],
            "entity_3": r[4],
        }
        for r in rows
    ]


def sample_unlabeled(
    pack_id: str,
    *,
    n: int,
    strategy: str = "random",
    seed: int = 0,
) -> list[str]:
    """Enqueue n unlabeled pairs. strategy is a sampling method, not a label.

    Strategies:
      random          — two distinct records
      same_category   — share category (annotator still chooses the class)
    """
    recs = _load_records(pack_id)
    if len(recs) < 2:
        return []
    rng = random.Random(seed)
    ids: list[str] = []
    attempts = 0
    while len(ids) < n and attempts < n * 20:
        attempts += 1
        a, b = rng.sample(recs, 2)
        if strategy == "same_category":
            same = [r for r in recs if r.get("category") and r["category"] == a["category"] and r["record_id"] != a["record_id"]]
            if not same:
                continue
            b = rng.choice(same)
        ids.append(
            enqueue_unlabeled_item(
                query_text=a["text"],
                candidate_text=b["text"],
                source_record_id=a["record_id"],
                candidate_record_id=b["record_id"],
                category=a.get("category"),
                entity_2=a.get("entity_2"),
                entity_3=a.get("entity_3"),
            )
        )
    return ids
