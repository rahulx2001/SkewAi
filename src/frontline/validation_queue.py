"""Validation Queue: needs_review / unverifiable / low-confidence with span evidence."""

from __future__ import annotations

import json
from typing import Any

from src.data.warehouse import ops_con
from src.qubot.claims import load_bound_claims
from src.qubot.evidence_pin import snapshots_for_action


def _span_highlight(text: str, start: int, end: int) -> dict[str, Any]:
    if start < 0 or end < start:
        return {"before": text, "hit": "", "after": "", "start": start, "end": end}
    return {
        "before": text[:start],
        "hit": text[start:end],
        "after": text[end:],
        "start": start,
        "end": end,
    }


def _evidence_payload(action_id: str | None) -> list[dict[str, Any]]:
    if not action_id:
        return []
    claims = load_bound_claims(action_id)
    snaps = {str(s.get("evidence_id")): s for s in snapshots_for_action(action_id)}
    out: list[dict[str, Any]] = []
    for c in claims:
        snap = snaps.get(c.evidence_id) or {}
        body = snap.get("body_json") or "{}"
        try:
            text = json.loads(body).get("text") or "" if isinstance(body, str) else str(
                (body or {}).get("text") or ""
            )
        except json.JSONDecodeError:
            text = str(body)
        out.append(
            {
                "claim_text": c.claim_text,
                "evidence_id": c.evidence_id,
                "span": _span_highlight(text, c.span_start, c.span_end),
                "snapshot_hash": snap.get("body_hash"),
            }
        )
    if not out and snaps:
        for eid, snap in snaps.items():
            body = snap.get("body_json") or "{}"
            try:
                text = json.loads(body).get("text") or "" if isinstance(body, str) else ""
            except json.JSONDecodeError:
                text = ""
            out.append(
                {
                    "claim_text": text[:48],
                    "evidence_id": eid,
                    "span": _span_highlight(text, 0, min(48, len(text))),
                    "snapshot_hash": snap.get("body_hash"),
                }
            )
    return out


def _action_for_case(case_id: str, interaction_id: str) -> str | None:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                """
                SELECT action_id FROM agent_actions
                WHERE (case_id = ? OR interaction_id = ?)
                  AND action_type IN ('brief_written', 'similar_search')
                ORDER BY ts DESC LIMIT 1
                """,
                [case_id, interaction_id],
            ).fetchone()
        except Exception:
            return None
    return str(row[0]) if row else None


def list_queue() -> list[dict[str, Any]]:
    """needs_review cases, unverifiable audit actions, low-confidence intake."""
    items: list[dict[str, Any]] = []
    with ops_con(read_only=True) as con:
        try:
            cases = con.execute(
                """
                SELECT case_id, interaction_id, status, category, description_summary,
                       severity
                FROM cases
                WHERE status = 'pending_followup'
                """
            ).fetchall()
        except Exception:
            cases = []
        try:
            unv = con.execute(
                """
                SELECT a.action_id, a.interaction_id, a.action_type, a.output_summary
                FROM agent_actions a
                WHERE a.ok = FALSE
                   OR a.action_type = 'brief_written'
                LIMIT 50
                """
            ).fetchall()
        except Exception:
            unv = []
        try:
            low = con.execute(
                """
                SELECT action_id, interaction_id, output_summary
                FROM agent_actions
                WHERE action_type = 'slot_extracted'
                  AND (output_summary ILIKE '%low%confidence%'
                       OR output_summary ILIKE '%confidence=low%')
                """
            ).fetchall()
        except Exception:
            low = []

    for case_id, iid, status, cat, desc, sev in cases:
        aid = _action_for_case(str(case_id), str(iid))
        items.append(
            {
                "queue_kind": "needs_review",
                "ref_id": str(case_id),
                "interaction_id": str(iid),
                "summary": desc or cat or case_id,
                "severity": sev,
                "status": status,
                "span_evidence": _evidence_payload(aid),
            }
        )

    seen_actions = set()
    for action_id, iid, atype, out in unv:
        if action_id in seen_actions:
            continue
        # Only treat as unverifiable when the action itself failed or auditor
        # marked it; failed actions always qualify.
        if atype == "brief_written":
            continue
        seen_actions.add(action_id)
        items.append(
            {
                "queue_kind": "unverifiable",
                "ref_id": str(action_id),
                "interaction_id": str(iid),
                "summary": out or atype,
                "span_evidence": _evidence_payload(str(action_id)),
            }
        )

    for action_id, iid, out in low:
        items.append(
            {
                "queue_kind": "low_confidence",
                "ref_id": str(action_id),
                "interaction_id": str(iid),
                "summary": out or "low confidence extraction",
                "span_evidence": _evidence_payload(str(action_id)),
            }
        )

    return items


def enqueue_insight(
    *,
    kind: str,
    interaction_id: str,
    summary: str,
    action_id: str | None = None,
    case_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a queue row (test + reviewer path). Stored as an insight_queue table."""
    if kind not in {"needs_review", "unverifiable", "low_confidence"}:
        raise ValueError(kind)
    from src.data.timeutil import utc_now
    from src.ids import new_ulid

    qid = "vq_" + new_ulid()
    with ops_con() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS insight_queue (
                queue_id VARCHAR PRIMARY KEY,
                kind VARCHAR NOT NULL,
                interaction_id VARCHAR,
                case_id VARCHAR,
                action_id VARCHAR,
                summary TEXT,
                extra_json TEXT,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO insight_queue
            (queue_id, kind, interaction_id, case_id, action_id, summary, extra_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                qid,
                kind,
                interaction_id,
                case_id,
                action_id,
                summary,
                json.dumps(extra or {}),
                utc_now(),
            ],
        )
    return {
        "queue_id": qid,
        "queue_kind": kind,
        "interaction_id": interaction_id,
        "summary": summary,
        "span_evidence": _evidence_payload(action_id),
    }


def list_queue_all() -> list[dict[str, Any]]:
    """Union of live cases/actions plus explicit insight_queue rows."""
    items = list_queue()
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT queue_id, kind, interaction_id, case_id, action_id, summary
                FROM insight_queue ORDER BY created_at DESC
                """
            ).fetchall()
        except Exception:
            rows = []
    for qid, kind, iid, case_id, aid, summary in rows:
        items.append(
            {
                "queue_id": qid,
                "queue_kind": kind,
                "ref_id": qid,
                "interaction_id": iid,
                "case_id": case_id,
                "summary": summary,
                "span_evidence": _evidence_payload(aid),
            }
        )
    return items


__all__ = ["list_queue", "list_queue_all", "enqueue_insight"]
