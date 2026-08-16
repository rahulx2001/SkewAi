"""Cross-contact entity memory — recall prior issues when the same entity returns.

Keyed by pack_id + entity fingerprint (entity_1|entity_2|entity_3). Deterministic.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con
from src.ids import new_ulid


def entity_key(entity_1: str | None, entity_2: str | None, entity_3: str | None) -> str:
    parts = [
        (entity_1 or "").strip().lower(),
        (entity_2 or "").strip().lower(),
        (entity_3 or "").strip().lower(),
    ]
    raw = "|".join(parts)
    if raw == "||":
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def lookup_memory(
    pack_id: str,
    *,
    entity_1: str | None = None,
    entity_2: str | None = None,
    entity_3: str | None = None,
    entity_key_hex: str | None = None,
) -> dict[str, Any] | None:
    key = entity_key_hex or entity_key(entity_1, entity_2, entity_3)
    if not key:
        return None
    with ops_con(read_only=True) as con:
        cur = con.execute(
            """
            SELECT * FROM contact_memory
            WHERE pack_id = ? AND entity_key = ?
            """,
            [pack_id, key],
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def upsert_memory_from_interaction(interaction_id: str) -> dict[str, Any] | None:
    """Upsert memory after a contact ends. No-op if entities empty."""
    with ops_con(read_only=True) as con:
        h = con.execute(
            """
            SELECT interaction_id, pack_id, entity_1, entity_2, entity_3,
                   category, peak_frustration, outcome, status
            FROM interactions WHERE interaction_id = ?
            """,
            [interaction_id],
        ).fetchone()
        if not h:
            return None
        ix = {
            "interaction_id": h[0],
            "pack_id": h[1],
            "entity_1": h[2],
            "entity_2": h[3],
            "entity_3": h[4],
            "category": h[5],
            "peak_frustration": h[6],
            "outcome": h[7],
            "status": h[8],
        }
        case = con.execute(
            """
            SELECT case_id, severity, status FROM cases WHERE interaction_id = ?
            """,
            [interaction_id],
        ).fetchone()

    key = entity_key(ix.get("entity_1"), ix.get("entity_2"), ix.get("entity_3"))
    if not key:
        return None

    from src.data.timeutil import utc_now

    now = utc_now()
    case_id = case[0] if case else None
    severity = case[1] if case else None
    case_status = case[2] if case else None
    open_delta = 1 if case_status in ("open", "pending_followup") else 0
    new_peak = float(ix.get("peak_frustration") or 0)

    existing = lookup_memory(ix["pack_id"], entity_key_hex=key)
    if existing:
        # Aggregate in Python so UPDATE uses a flat, unambiguous param list.
        # (DuckDB prepared CASE/COALESCE mixes previously mismatched param counts.)
        prev_peak = float(existing.get("peak_frustration") or 0)
        peak = max(prev_peak, new_peak)
        open_count = int(existing.get("open_case_count") or 0) + open_delta
        next_case_id = case_id or existing.get("last_case_id")
        next_severity = severity or existing.get("last_severity")
        next_category = ix.get("category") or existing.get("last_category")
        with ops_con() as con:
            con.execute(
                """
                UPDATE contact_memory SET
                    last_interaction_id = ?,
                    last_case_id = ?,
                    last_severity = ?,
                    last_category = ?,
                    last_outcome = ?,
                    peak_frustration = ?,
                    open_case_count = ?,
                    interaction_count = interaction_count + 1,
                    note_summary = ?,
                    last_seen_at = ?
                WHERE pack_id = ? AND entity_key = ?
                """,
                [
                    interaction_id,
                    next_case_id,
                    next_severity,
                    next_category,
                    ix.get("outcome") or ix.get("status"),
                    peak,
                    open_count,
                    (
                        f"Last contact {interaction_id}; "
                        f"category={ix.get('category')}; "
                        f"outcome={ix.get('outcome')}"
                    ),
                    now,
                    ix["pack_id"],
                    key,
                ],
            )
        return lookup_memory(ix["pack_id"], entity_key_hex=key)

    mid = "mem_" + new_ulid()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO contact_memory (
                memory_id, pack_id, entity_key, entity_1, entity_2, entity_3,
                last_interaction_id, last_case_id, last_severity, last_category,
                last_outcome, peak_frustration, open_case_count, interaction_count,
                note_summary, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            [
                mid,
                ix["pack_id"],
                key,
                ix.get("entity_1"),
                ix.get("entity_2"),
                ix.get("entity_3"),
                interaction_id,
                case_id,
                severity,
                ix.get("category"),
                ix.get("outcome") or ix.get("status"),
                new_peak,
                open_delta,
                f"First seen on {interaction_id}",
                now,
                now,
            ],
        )
    return lookup_memory(ix["pack_id"], entity_key_hex=key)


def list_memories(pack_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        if pack_id:
            cur = con.execute(
                """
                SELECT * FROM contact_memory WHERE pack_id = ?
                ORDER BY last_seen_at DESC LIMIT ?
                """,
                [pack_id, limit],
            )
        else:
            cur = con.execute(
                "SELECT * FROM contact_memory ORDER BY last_seen_at DESC LIMIT ?",
                [limit],
            )
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            for k, v in list(d.items()):
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
            rows.append(d)
    return rows
