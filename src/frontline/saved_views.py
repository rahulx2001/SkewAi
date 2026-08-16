"""Saved analyst views over grounded query / KPI filters."""

from __future__ import annotations

import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_views (
            view_id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            spec_json TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )


def save_view(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    vid = "view_" + new_ulid()
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO saved_views (view_id, name, spec_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [vid, name.strip(), json.dumps(spec, default=str), utc_now()],
        )
    return {"view_id": vid, "name": name.strip(), "spec": spec}


def get_view(view_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                "SELECT view_id, name, spec_json FROM saved_views WHERE view_id = ?",
                [view_id],
            ).fetchone()
        except Exception:
            return None
    if not row:
        return None
    return {"view_id": row[0], "name": row[1], "spec": json.loads(row[2])}


def list_views() -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute("SELECT view_id, name, spec_json FROM saved_views").fetchall()
        except Exception:
            return []
    return [{"view_id": r[0], "name": r[1], "spec": json.loads(r[2])} for r in rows]


__all__ = ["save_view", "get_view", "list_views"]
