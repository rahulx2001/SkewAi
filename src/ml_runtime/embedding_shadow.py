"""Shadow-mode comparison telemetry. Never changes customer-visible outcomes.

Stores record/cluster IDs and scores only — no complaint text.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.ml_runtime.embedding_store import SHADOW_COMPARISONS_DDL, ensure_shadow_table

logger = logging.getLogger(__name__)


def record_shadow_comparison(
    *,
    interaction_id: str,
    pack_id: str,
    query_embedding_version: str,
    candidate_embedding_version: str | None,
    cluster_build_id: str | None,
    hash_top_ids: Sequence[str],
    semantic_top_ids: Sequence[str],
    hash_top_score: float | None,
    semantic_top_score: float | None,
    hash_cluster_id: int | None,
    semantic_cluster_id: int | None,
    hash_novel: bool,
    semantic_novel: bool,
    semantic_status: str,
    latency_ms: int | None,
) -> str:
    hid = [str(x) for x in hash_top_ids if x]
    sid = [str(x) for x in semantic_top_ids if x]
    overlap = 0.0
    if hid and sid:
        overlap = len(set(hid) & set(sid)) / float(max(len(hid), len(sid)))
    cid = "esc_" + new_ulid()
    with ops_con() as con:
        ensure_shadow_table(con)
        con.execute(
            """
            INSERT INTO embedding_shadow_comparisons (
                comparison_id, interaction_id, pack_id,
                query_embedding_version, candidate_embedding_version, cluster_build_id,
                hash_top_ids, semantic_top_ids, rank_overlap,
                hash_top_score, semantic_top_score, hash_cluster_id, semantic_cluster_id,
                hash_novel, semantic_novel, semantic_status, latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                cid,
                interaction_id,
                pack_id,
                query_embedding_version,
                candidate_embedding_version,
                cluster_build_id,
                json.dumps(hid),
                json.dumps(sid),
                round(overlap, 4),
                hash_top_score,
                semantic_top_score,
                hash_cluster_id,
                semantic_cluster_id,
                bool(hash_novel),
                bool(semantic_novel),
                semantic_status,
                latency_ms,
            ],
        )
    maybe_alert_divergence(pack_id)
    return cid


def load_shadow_comparisons(interaction_id: str) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            cur = con.execute(
                "SELECT * FROM embedding_shadow_comparisons WHERE interaction_id = ? ORDER BY created_at DESC",
                [interaction_id],
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []


def latest_shadow(interaction_id: str) -> dict[str, Any] | None:
    rows = load_shadow_comparisons(interaction_id)
    return rows[0] if rows else None


def flag_shadow_wrong(interaction_id: str, *, reviewer: str, comment: str = "") -> str:
    """Supervisor flag: shadow looks wrong. Feeds the unlabeled eval queue."""
    from src.eval.embedding_labels import enqueue_unlabeled_item

    row = latest_shadow(interaction_id)
    fid = "sflag_" + new_ulid()
    with ops_con() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_shadow_flags (
                flag_id VARCHAR PRIMARY KEY,
                interaction_id VARCHAR NOT NULL,
                comparison_id VARCHAR,
                reviewer VARCHAR NOT NULL,
                comment VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        con.execute(
            """
            INSERT INTO embedding_shadow_flags (flag_id, interaction_id, comparison_id, reviewer, comment)
            VALUES (?, ?, ?, ?, ?)
            """,
            [fid, interaction_id, (row or {}).get("comparison_id"), reviewer, comment[:400]],
        )
    enqueue_unlabeled_item(
        query_text=f"[shadow-flag interaction {interaction_id}]",
        candidate_text="supervisor flagged shadow cluster match; review source contact offline",
        source_record_id=interaction_id,
        category="shadow_flag",
    )
    return fid


def maybe_alert_divergence(pack_id: str, *, window: int = 50) -> dict[str, Any] | None:
    import os

    try:
        thresh = float(os.getenv("FRONTLINE_SHADOW_DIVERGENCE_PCT") or "0.35")
    except ValueError:
        thresh = 0.35
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT hash_cluster_id, semantic_cluster_id
                FROM embedding_shadow_comparisons
                WHERE pack_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [pack_id, int(window)],
            ).fetchall()
        except Exception:
            return None
    if len(rows) < 10:
        return None
    disagree = 0
    for h, s in rows:
        if h != s:
            disagree += 1
    rate = disagree / len(rows)
    if rate <= thresh:
        return {"rate": round(rate, 4), "window": len(rows), "alerted": False}
    with ops_con() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_divergence_alerts (
                alert_id VARCHAR PRIMARY KEY,
                pack_id VARCHAR,
                rate DOUBLE,
                window_n INTEGER,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        con.execute(
            """
            INSERT INTO shadow_divergence_alerts (alert_id, pack_id, rate, window_n)
            VALUES (?, ?, ?, ?)
            """,
            ["sdv_" + new_ulid(), pack_id, round(rate, 4), len(rows)],
        )
    logger.warning("shadow_divergence pack=%s rate=%.3f window=%s", pack_id, rate, len(rows))
    return {"rate": round(rate, 4), "window": len(rows), "alerted": True}


__all__ = [
    "record_shadow_comparison",
    "load_shadow_comparisons",
    "latest_shadow",
    "flag_shadow_wrong",
    "maybe_alert_divergence",
    "SHADOW_COMPARISONS_DDL",
]
