"""Pilot ops helpers — case lifecycle, notes, investigation status, metrics, CSV.

Keeps HTTP routes thin. All writes ledger before/with the mutation where
applicable. Never invents CRM workflows: status enums are the pack-agnostic
pilot set documented on the schema.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.ledger import AgentAction, record_action

CASE_STATUSES = frozenset({"open", "pending_followup", "closed"})
INV_STATUSES = frozenset({"open", "monitoring", "closed"})


def _now() -> datetime:
    from src.data.timeutil import utc_now

    return utc_now()


def _parse_json_field(row: dict[str, Any], key: str) -> None:
    v = row.get(key)
    if isinstance(v, str):
        try:
            row[key] = json.loads(v)
        except Exception:
            pass


def get_case_row(case_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute("SELECT * FROM cases WHERE case_id = ?", [case_id])
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))
    _parse_json_field(d, "safety_flags")
    return d


def update_case(
    case_id: str,
    *,
    status: str | None = None,
    followup_draft: str | None = None,
    author: str = "operator",
) -> dict[str, Any]:
    """Update case status and/or follow-up draft. Raises ValueError on bad input."""
    row = get_case_row(case_id)
    if row is None:
        raise LookupError(f"case not found: {case_id}")

    from src.security.sql_ident import SAFE_CASE_UPDATE_FIELDS, safe_ident

    fields: list[str] = []
    params: list[Any] = []
    if status is not None:
        if status not in CASE_STATUSES:
            raise ValueError(f"invalid status {status!r}; allowed: {sorted(CASE_STATUSES)}")
        col = safe_ident("status", SAFE_CASE_UPDATE_FIELDS, kind="column")
        fields.append(f"{col} = ?")
        params.append(status)
    if followup_draft is not None:
        col = safe_ident("followup_draft", SAFE_CASE_UPDATE_FIELDS, kind="column")
        fields.append(f"{col} = ?")
        params.append(followup_draft)
    if not fields:
        return row

    params.append(case_id)
    with ops_con() as con:
        con.execute(f"UPDATE cases SET {', '.join(fields)} WHERE case_id = ?", params)

    iid = row.get("interaction_id") or "platform"
    if status is not None and status != row.get("status"):
        record_action(
            AgentAction(
                interaction_id=iid,
                agent="supervisor",
                action_type="case_status_updated",
                input_summary=f"from={row.get('status')}",
                output_summary=f"to={status}; by={author}",
                case_id=case_id,
            )
        )
    if followup_draft is not None:
        record_action(
            AgentAction(
                interaction_id=iid,
                agent="supervisor",
                action_type="followup_saved",
                input_summary=f"by={author}",
                output_summary=(followup_draft or "")[:500],
                case_id=case_id,
            )
        )
    updated = get_case_row(case_id)
    assert updated is not None
    return updated


def add_case_note(
    case_id: str,
    body: str,
    *,
    author: str = "operator",
) -> dict[str, Any]:
    row = get_case_row(case_id)
    if row is None:
        raise LookupError(f"case not found: {case_id}")
    text = (body or "").strip()
    if not text:
        raise ValueError("note body required")
    if len(text) > 4000:
        text = text[:4000]
    note_id = "note_" + new_ulid()
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO case_notes (note_id, case_id, author, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [note_id, case_id, (author or "operator")[:80], text, now],
        )
    record_action(
        AgentAction(
            interaction_id=row.get("interaction_id") or "platform",
            agent="supervisor",
            action_type="case_note_added",
            input_summary=f"author={author}",
            output_summary=text[:500],
            case_id=case_id,
        )
    )
    from src.data.timeutil import to_iso_z

    return {
        "note_id": note_id,
        "case_id": case_id,
        "author": author or "operator",
        "body": text,
        "created_at": to_iso_z(now),
    }


def list_case_notes(case_id: str, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        cur = con.execute(
            """
            SELECT note_id, case_id, author, body, created_at
            FROM case_notes
            WHERE case_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [case_id, limit],
        )
        cols = [d[0] for d in cur.description]
        from src.data.timeutil import to_iso_z

        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = to_iso_z(d["created_at"])
            rows.append(d)
    return rows


def update_investigation(
    investigation_id: str,
    *,
    status: str,
    author: str = "operator",
) -> dict[str, Any]:
    if status not in INV_STATUSES:
        raise ValueError(f"invalid status {status!r}; allowed: {sorted(INV_STATUSES)}")
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT investigation_id, status, pack_id, title FROM investigations WHERE investigation_id = ?",
            [investigation_id],
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f"investigation not found: {investigation_id}")
        cols = [d[0] for d in cur.description]
        before = dict(zip(cols, row))
    with ops_con() as con:
        con.execute(
            "UPDATE investigations SET status = ? WHERE investigation_id = ?",
            [status, investigation_id],
        )
    record_action(
        AgentAction(
            interaction_id="platform",
            agent="supervisor",
            action_type="investigation_status_updated",
            input_summary=f"from={before.get('status')}; inv={investigation_id}",
            output_summary=f"to={status}; by={author}",
            evidence_ids=[investigation_id],
        )
    )
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM investigations WHERE investigation_id = ?",
            [investigation_id],
        )
        r = cur.fetchone()
        cols = [d[0] for d in cur.description]
        out = dict(zip(cols, r))
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


def build_cases_csv(
    *,
    status: str | None = None,
    severity: str | None = None,
    q: str | None = None,
    limit: int = 500,
) -> tuple[str, int]:
    """Return (csv_text, row_count) for case export."""
    limit = min(max(int(limit), 1), 2000)
    sql = """
        SELECT case_id, interaction_id, pack_id, created_at, category,
               description_summary, severity, priority, status,
               cluster_match_id, investigation_id, advisory_match_id
        FROM cases
    """
    params: list[Any] = []
    clauses: list[str] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if q and q.strip():
        like = f"%{q.strip()}%"
        clauses.append(
            "(case_id ILIKE ? OR interaction_id ILIKE ? OR category ILIKE ? "
            "OR description_summary ILIKE ? OR investigation_id ILIKE ?)"
        )
        params.extend([like, like, like, like, like])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with ops_con(read_only=True) as con:
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        for k, v in list(row.items()):
            if isinstance(v, datetime):
                row[k] = v.isoformat()
        writer.writerow(row)
    return buf.getvalue(), len(rows)


def ops_metrics(*, window_days: int = 7) -> dict[str, Any]:
    """Pilot ops snapshot for dashboard header / health-adjacent views."""
    window_days = min(max(int(window_days), 1), 90)
    with ops_con(read_only=True) as con:
        case_open = con.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'open'"
        ).fetchone()[0]
        case_pending = con.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'pending_followup'"
        ).fetchone()[0]
        case_closed = con.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'closed'"
        ).fetchone()[0]
        case_critical = con.execute(
            "SELECT COUNT(*) FROM cases WHERE status != 'closed' AND severity = 'Critical'"
        ).fetchone()[0]
        inv_open = con.execute(
            "SELECT COUNT(*) FROM investigations WHERE status = 'open'"
        ).fetchone()[0]
        inv_mon = con.execute(
            "SELECT COUNT(*) FROM investigations WHERE status = 'monitoring'"
        ).fetchone()[0]
        active_ix = con.execute(
            "SELECT COUNT(*) FROM interactions WHERE status = 'active'"
        ).fetchone()[0]
        cases_window = con.execute(
            """
            SELECT COUNT(*) FROM cases
            WHERE created_at >= now() - INTERVAL (? || ' days')
            """,
            [str(window_days)],
        ).fetchone()[0]
        try:
            dl_pending = con.execute(
                "SELECT COUNT(*) FROM alert_dead_letter WHERE status = 'pending'"
            ).fetchone()[0]
        except Exception:
            dl_pending = 0
        try:
            conn_pending = con.execute(
                "SELECT COUNT(*) FROM connector_deliveries WHERE status = 'pending'"
            ).fetchone()[0]
        except Exception:
            conn_pending = 0
        notes_window = con.execute(
            """
            SELECT COUNT(*) FROM case_notes
            WHERE created_at >= now() - INTERVAL (? || ' days')
            """,
            [str(window_days)],
        ).fetchone()[0]

    return {
        "window_days": window_days,
        "cases": {
            "open": int(case_open),
            "pending_followup": int(case_pending),
            "closed": int(case_closed),
            "critical_open": int(case_critical),
            "created_in_window": int(cases_window),
        },
        "investigations": {
            "open": int(inv_open),
            "monitoring": int(inv_mon),
        },
        "interactions_active": int(active_ix),
        "alert_dead_letters_pending": int(dl_pending),
        "connector_deliveries_pending": int(conn_pending),
        "case_notes_in_window": int(notes_window),
        "ts": _now().isoformat(),
    }


__all__ = [
    "CASE_STATUSES",
    "INV_STATUSES",
    "get_case_row",
    "update_case",
    "add_case_note",
    "list_case_notes",
    "update_investigation",
    "build_cases_csv",
    "ops_metrics",
]
