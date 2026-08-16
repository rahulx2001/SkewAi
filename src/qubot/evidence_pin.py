"""Content-addressed snapshots of *cited* domain rows (not a full dump).

On action write we pin sha256(canonical JSON) of each cited ``records`` row.
The auditor compares the pin to the live row and flags ``source-drifted``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import domain_con, ops_con
from src.ids import new_ulid


def _ensure_pin_table(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cited_evidence_snapshots (
            snapshot_id    VARCHAR PRIMARY KEY,
            action_id      VARCHAR NOT NULL,
            interaction_id VARCHAR,
            pack_id        VARCHAR NOT NULL,
            evidence_id    VARCHAR NOT NULL,
            body_json      TEXT NOT NULL,
            body_hash      VARCHAR NOT NULL,
            pinned_at      TIMESTAMP NOT NULL
        )
        """
    )


def canonical_row_hash(row: dict[str, Any]) -> str:
    body = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def fetch_record_row(pack_id: str, record_id: str) -> dict[str, Any] | None:
    try:
        with domain_con(pack_id) as con:
            cur = con.execute("SELECT * FROM records WHERE record_id = ?", [record_id])
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
    except FileNotFoundError:
        return None


def fetch_record_rows(pack_id: str, record_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One domain read for many record_ids."""
    ids = [str(r) for r in record_ids if r]
    if not pack_id or not ids:
        return {}
    try:
        with domain_con(pack_id) as con:
            ph = ",".join("?" * len(ids))
            cur = con.execute(
                f"SELECT * FROM records WHERE record_id IN ({ph})",
                ids,
            )
            cols = [d[0] for d in cur.description]
            out: dict[str, dict[str, Any]] = {}
            for raw in cur.fetchall():
                rec = {k: v for k, v in zip(cols, raw) if k != "embedding"}
                rid = str(rec.get("record_id") or "")
                if rid:
                    out[rid] = rec
            return out
    except FileNotFoundError:
        return {}


def insert_pins_on_con(
    con,
    *,
    action_id: str,
    interaction_id: str | None,
    pack_id: str,
    rows: dict[str, dict[str, Any]],
) -> int:
    _ensure_pin_table(con)
    n = 0
    for rid, row in rows.items():
        body = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
        h = hashlib.sha256(body.encode("utf-8")).hexdigest()
        con.execute(
            """
            INSERT INTO cited_evidence_snapshots
            (snapshot_id, action_id, interaction_id, pack_id, evidence_id,
             body_json, body_hash, pinned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "pin_" + new_ulid(),
                action_id,
                interaction_id,
                pack_id,
                rid,
                body,
                h,
                utc_now(),
            ],
        )
        n += 1
    return n


def pin_cited_records(
    *,
    action_id: str,
    interaction_id: str | None,
    pack_id: str,
    evidence_ids: list[Any],
) -> int:
    """Snapshot each cited record_id that exists. Returns pin count."""
    if not pack_id or not evidence_ids:
        return 0
    found = fetch_record_rows(pack_id, [str(e) for e in evidence_ids])
    if not found:
        return 0
    with ops_con() as con:
        return insert_pins_on_con(
            con,
            action_id=action_id,
            interaction_id=interaction_id,
            pack_id=pack_id,
            rows=found,
        )


def detect_source_drift(action_id: str) -> list[dict[str, Any]]:
    """Return pins whose live source row no longer matches the snapshot hash."""
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT evidence_id, pack_id, body_hash, body_json
                FROM cited_evidence_snapshots WHERE action_id = ?
                """,
                [action_id],
            ).fetchall()
        except Exception:
            return []
    drifted: list[dict[str, Any]] = []
    for eid, pack_id, pinned_hash, _body in rows:
        live = fetch_record_row(str(pack_id), str(eid))
        if live is None:
            drifted.append(
                {"evidence_id": eid, "reason": "source_row_missing", "pinned_hash": pinned_hash}
            )
            continue
        live = {k: v for k, v in live.items() if k != "embedding"}
        now_hash = canonical_row_hash(live)
        if now_hash != pinned_hash:
            drifted.append(
                {
                    "evidence_id": eid,
                    "reason": "source-drifted",
                    "pinned_hash": pinned_hash,
                    "live_hash": now_hash,
                }
            )
    return drifted


def snapshots_for_action(action_id: str) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            cur = con.execute(
                """
                SELECT snapshot_id, evidence_id, pack_id, body_json, body_hash
                FROM cited_evidence_snapshots WHERE action_id = ?
                """,
                [action_id],
            )
        except Exception:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


__all__ = [
    "canonical_row_hash",
    "fetch_record_row",
    "fetch_record_rows",
    "pin_cited_records",
    "insert_pins_on_con",
    "detect_source_drift",
    "snapshots_for_action",
]
