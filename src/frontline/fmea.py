"""FMEA-style failure-mode library + verified-effective fix match."""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.enterprise.fix_effectiveness import measure_effectiveness
from src.ids import new_ulid


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS failure_modes (
            mode_id VARCHAR PRIMARY KEY,
            pack_id VARCHAR,
            investigation_id VARCHAR,
            category VARCHAR,
            entity_2 VARCHAR,
            entity_3 VARCHAR,
            title TEXT,
            description TEXT,
            fix_id VARCHAR,
            verified_effective BOOLEAN,
            created_at TIMESTAMP
        )
        """
    )


def record_failure_mode(
    *,
    pack_id: str,
    investigation_id: str,
    category: str,
    title: str,
    description: str = "",
    entity_2: str | None = None,
    entity_3: str | None = None,
    fix_id: str | None = None,
    verified_effective: bool = False,
) -> dict[str, Any]:
    mid = "fm_" + new_ulid()
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO failure_modes
            (mode_id, pack_id, investigation_id, category, entity_2, entity_3,
             title, description, fix_id, verified_effective, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                mid,
                pack_id,
                investigation_id,
                category,
                entity_2,
                entity_3,
                title,
                description,
                fix_id,
                verified_effective,
                utc_now(),
            ],
        )
    return {"mode_id": mid, "verified_effective": verified_effective, "title": title}


def mark_verified_from_effectiveness(
    mode_id: str,
    *,
    pack_id: str,
    category: str,
    fixed_at,
    entity_2: str | None = None,
    entity_3: str | None = None,
) -> dict[str, Any]:
    meas = measure_effectiveness(
        pack_id=pack_id,
        fixed_at=fixed_at,
        category=category,
        entity_2=entity_2,
        entity_3=entity_3,
    )
    ok = bool(meas.get("improved"))
    with ops_con() as con:
        _ensure(con)
        con.execute(
            "UPDATE failure_modes SET verified_effective = ? WHERE mode_id = ?",
            [ok, mode_id],
        )
    return {"mode_id": mode_id, "verified_effective": ok, "measurement": meas}


def suggest_seen_before(
    *,
    pack_id: str,
    category: str,
    entity_2: str | None = None,
) -> dict[str, Any]:
    """Suggest only verified-effective prior fixes for this slice."""
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT mode_id, title, description, fix_id, verified_effective, entity_2
                FROM failure_modes
                WHERE pack_id = ? AND category = ?
                """,
                [pack_id, category],
            ).fetchall()
        except Exception:
            rows = []
    effective = []
    siblings = []
    for mid, title, desc, fid, ver, ent in rows:
        item = {
            "mode_id": mid,
            "title": title,
            "description": desc,
            "fix_id": fid,
            "verified_effective": bool(ver),
            "entity_2": ent,
        }
        if entity_2 and ent and str(ent) != entity_2:
            siblings.append(item)
            continue
        if ver:
            effective.append(item)
        else:
            siblings.append(item)
    return {
        "suggested": effective,
        "non_effective_siblings": siblings,
        "suggested_effective_only": all(s["verified_effective"] for s in effective),
    }


__all__ = [
    "record_failure_mode",
    "mark_verified_from_effectiveness",
    "suggest_seen_before",
]
