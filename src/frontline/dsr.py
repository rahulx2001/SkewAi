"""Data-subject request tooling: export/delete by interaction (feature #34)."""

from __future__ import annotations

import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con


def export_interaction(interaction_id: str) -> dict[str, Any]:
    """Export all ops rows linked to one interaction."""
    iid = interaction_id
    out: dict[str, Any] = {"interaction_id": iid, "exported_at": utc_now().isoformat() + "Z"}
    with ops_con(read_only=True) as con:
        for name, sql, params in (
            ("interaction", "SELECT * FROM interactions WHERE interaction_id = ?", [iid]),
            ("turns", "SELECT * FROM interaction_turns WHERE interaction_id = ? ORDER BY seq", [iid]),
            ("actions", "SELECT * FROM agent_actions WHERE interaction_id = ? ORDER BY ts", [iid]),
            ("cases", "SELECT * FROM cases WHERE interaction_id = ?", [iid]),
            (
                "version_stamps",
                "SELECT * FROM interaction_version_stamps WHERE interaction_id = ?",
                [iid],
            ),
        ):
            try:
                cur = con.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                for r in rows:
                    for k, v in list(r.items()):
                        if hasattr(v, "isoformat"):
                            r[k] = v.isoformat()
                out[name] = rows if name != "interaction" else (rows[0] if rows else None)
            except Exception as e:
                out[name] = {"error": f"{type(e).__name__}:{e}"}

        # notes for cases
        case_ids = [c["case_id"] for c in (out.get("cases") or []) if c.get("case_id")]
        notes = []
        for cid in case_ids:
            try:
                cur = con.execute(
                    "SELECT * FROM case_notes WHERE case_id = ?", [cid]
                )
                cols = [d[0] for d in cur.description]
                for r in cur.fetchall():
                    d = dict(zip(cols, r))
                    for k, v in list(d.items()):
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    notes.append(d)
            except Exception:
                pass
        out["case_notes"] = notes
    return out


def delete_interaction(interaction_id: str) -> dict[str, Any]:
    """Delete linked ops rows for one interaction (hard delete)."""
    iid = interaction_id
    deleted: dict[str, int] = {}
    with ops_con() as con:
        # case notes first
        case_ids = [
            r[0]
            for r in con.execute(
                "SELECT case_id FROM cases WHERE interaction_id = ?", [iid]
            ).fetchall()
        ]
        n = 0
        for cid in case_ids:
            con.execute("DELETE FROM case_notes WHERE case_id = ?", [cid])
            n += 1
        deleted["case_notes_batches"] = n
        from src.security.sql_ident import safe_column, safe_table

        for table, col in (
            ("cases", "interaction_id"),
            ("agent_actions", "interaction_id"),
            ("interaction_turns", "interaction_id"),
            ("interaction_version_stamps", "interaction_id"),
            ("risk_snapshots", "interaction_id"),
            ("interactions", "interaction_id"),
        ):
            try:
                t = safe_table(table)
                c = safe_column(col)
                before = con.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE {c} = ?", [iid]
                ).fetchone()[0]
                con.execute(f"DELETE FROM {t} WHERE {c} = ?", [iid])
                deleted[table] = int(before)
            except Exception:
                deleted[table] = -1
    return {"interaction_id": iid, "deleted": deleted, "ok": True}


__all__ = ["export_interaction", "delete_interaction"]
