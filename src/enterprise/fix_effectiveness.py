"""Fix-effectiveness: before vs after record rates around a recorded fix."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.data.timeutil import to_iso_z, to_naive_utc, utc_now
from src.data.warehouse import domain_con, ops_con
from src.ids import new_ulid


def _as_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return to_naive_utc(val)
    try:
        return to_naive_utc(datetime.fromisoformat(str(val).replace("Z", "+00:00")))
    except ValueError:
        return None


def record_fix(
    *,
    pack_id: str,
    fixed_at: datetime,
    category: str | None = None,
    entity_2: str | None = None,
    entity_3: str | None = None,
    investigation_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Persist a fix on an affected slice. Returns the stored row."""
    fid = "fix_" + new_ulid()
    ts = to_naive_utc(fixed_at)
    with ops_con() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS recorded_fixes (
                fix_id             VARCHAR PRIMARY KEY,
                pack_id            VARCHAR NOT NULL,
                investigation_id   VARCHAR,
                entity_2           VARCHAR,
                entity_3           VARCHAR,
                category           VARCHAR,
                fixed_at           TIMESTAMP NOT NULL,
                note               TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO recorded_fixes
            (fix_id, pack_id, investigation_id, entity_2, entity_3, category, fixed_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                fid,
                pack_id,
                investigation_id,
                entity_2,
                entity_3,
                category,
                ts,
                note,
            ],
        )
    return {
        "fix_id": fid,
        "pack_id": pack_id,
        "investigation_id": investigation_id,
        "entity_2": entity_2,
        "entity_3": entity_3,
        "category": category,
        "fixed_at": to_iso_z(ts),
        "note": note,
    }


def measure_effectiveness(
    *,
    pack_id: str,
    fixed_at: datetime,
    category: str | None = None,
    entity_2: str | None = None,
    entity_3: str | None = None,
    window_days: int = 30,
) -> dict[str, Any]:
    """Count matching ``records`` in [fixed_at-window, fixed_at) vs (fixed_at, fixed_at+window].

    Rate = count / window_days. Does not use fixture literals.
    """
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    pivot = to_naive_utc(fixed_at)
    before_start = pivot - timedelta(days=window_days)
    after_end = pivot + timedelta(days=window_days)

    with domain_con(pack_id, read_only=True) as con:
        rows = con.execute(
            "SELECT received_at, category, entity_2, entity_3 FROM records"
        ).fetchall()
        cols = [d[0] for d in con.description]
        records = [dict(zip(cols, r)) for r in rows]

    def _match(r: dict[str, Any]) -> bool:
        if category and str(r.get("category") or "") != category:
            return False
        if entity_2 and str(r.get("entity_2") or "") != entity_2:
            return False
        if entity_3 and str(r.get("entity_3") or "") != entity_3:
            return False
        return True

    before_n = after_n = 0
    for r in records:
        if not _match(r):
            continue
        ts = _as_dt(r.get("received_at"))
        if ts is None:
            continue
        if before_start <= ts < pivot:
            before_n += 1
        elif pivot < ts <= after_end:
            after_n += 1

    before_rate = before_n / float(window_days)
    after_rate = after_n / float(window_days)
    return {
        "pack_id": pack_id,
        "category": category,
        "entity_2": entity_2,
        "entity_3": entity_3,
        "fixed_at": to_iso_z(pivot),
        "window_days": window_days,
        "before_count": before_n,
        "after_count": after_n,
        "before_rate": before_rate,
        "after_rate": after_rate,
        "improved": after_rate < before_rate,
        "measured_at": to_iso_z(utc_now()),
    }


__all__ = ["record_fix", "measure_effectiveness"]
