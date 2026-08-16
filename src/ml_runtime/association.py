"""Co-occurrence / lift ranking for similar records and similar contacts.

Recency is a tie-break only. A co-occurring sibling outranks a newer
unrelated row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence


ASSOC_KEYS = ("category", "entity_2", "entity_3", "source")


def _norm(val: Any) -> str:
    return str(val or "").strip().upper()


def _ts(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, datetime):
        return val.timestamp()
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def lift_for_pair(
    query: dict[str, Any],
    candidate: dict[str, Any],
    population: Sequence[dict[str, Any]],
) -> float:
    """P(cat∧ent) / (P(cat)P(ent)) on the population using query's cat+entity_2."""
    q_cat, q_ent = _norm(query.get("category")), _norm(query.get("entity_2"))
    c_cat, c_ent = _norm(candidate.get("category")), _norm(candidate.get("entity_2"))
    if not q_cat or not q_ent:
        return 0.0
    if q_cat != c_cat or q_ent != c_ent:
        return 0.0
    n = len(population) or 1
    n_both = n_cat = n_ent = 0
    for row in population:
        cat, ent = _norm(row.get("category")), _norm(row.get("entity_2"))
        if cat == q_cat:
            n_cat += 1
        if ent == q_ent:
            n_ent += 1
        if cat == q_cat and ent == q_ent:
            n_both += 1
    p_both = n_both / n
    p_cat = n_cat / n
    p_ent = n_ent / n
    if p_cat <= 0 or p_ent <= 0:
        return 0.0
    return p_both / (p_cat * p_ent)


def association_score(
    query: dict[str, Any],
    candidate: dict[str, Any],
    population: Sequence[dict[str, Any]],
) -> float:
    shared = 0
    for k in ASSOC_KEYS:
        qv, cv = _norm(query.get(k)), _norm(candidate.get(k))
        if qv and qv == cv:
            shared += 1
    lift = lift_for_pair(query, candidate, population)
    # Recency is a tiny epsilon so it cannot beat a real co-occurrence.
    recency = _ts(candidate.get("received_at") or candidate.get("started_at"))
    return shared * 10.0 + lift + recency * 1e-12


def rank_by_association(
    query: dict[str, Any],
    candidates: Iterable[dict[str, Any]],
    population: Sequence[dict[str, Any]] | None = None,
    *,
    top_k: int = 5,
    id_key: str = "record_id",
) -> list[dict[str, Any]]:
    """Return candidates sorted by association score (adds ``assoc_score``)."""
    pop = list(population) if population is not None else list(candidates)
    qid = _norm(query.get(id_key) or query.get("interaction_id"))
    scored: list[tuple[float, dict[str, Any]]] = []
    for c in candidates:
        cid = _norm(c.get(id_key) or c.get("interaction_id"))
        if qid and cid and qid == cid:
            continue
        row = dict(c)
        row["assoc_score"] = association_score(query, c, pop)
        scored.append((row["assoc_score"], row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


__all__ = [
    "ASSOC_KEYS",
    "lift_for_pair",
    "association_score",
    "rank_by_association",
]
