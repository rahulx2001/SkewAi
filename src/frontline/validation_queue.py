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

    from src.security.pii import reveal_subject_text

    for case_id, iid, status, cat, desc, sev in cases:
        desc_plain = reveal_subject_text(str(iid), desc)
        aid = _action_for_case(str(case_id), str(iid))
        items.append(
            {
                "queue_kind": "needs_review",
                "ref_id": str(case_id),
                "interaction_id": str(iid),
                "summary": desc_plain or cat or case_id,
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


__all__ = ["list_queue", "list_queue_all", "enqueue_insight", "export_audit_regressions",
           "create_review", "list_reviews", "assign_review", "resolve_review",
           "REVIEW_SLA_HOURS"]


#: Review SLA (board #10): a mismatch gets an owner and a verdict within 72h,
#: otherwise the queue grows unbounded and findings evaporate.
REVIEW_SLA_HOURS = 72


def create_review(
    *,
    interaction_id: str | None = None,
    case_id: str | None = None,
    reason: str = "audit_mismatch",
    sla_hours: int = REVIEW_SLA_HOURS,
) -> dict[str, Any]:
    """Open a review-queue row with owner=null (unassigned) and an SLA."""
    from datetime import timedelta as _td

    from src.data.timeutil import utc_now as _now
    from src.ids import new_ulid as _ulid

    rid = "rvw_" + _ulid()
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO review_queue
            (review_id, interaction_id, case_id, reason, status, owner,
             sla_due_at, verdict, created_at)
            VALUES (?, ?, ?, ?, 'open', NULL, ?, NULL, ?)
            """,
            [rid, interaction_id, case_id, reason, now + _td(hours=sla_hours), now],
        )
    return {"review_id": rid, "status": "open", "owner": None,
            "sla_due_at": (now + _td(hours=sla_hours)).isoformat()}


def list_reviews(*, status: str | None = None) -> list[dict[str, Any]]:
    """Review rows, oldest SLA first (unassigned bubble up)."""
    with ops_con(read_only=True) as con:
        try:
            sql = "SELECT review_id, interaction_id, case_id, reason, status, owner, sla_due_at, verdict, created_at FROM review_queue"
            params: list[Any] = []
            if status:
                sql += " WHERE status = ?"
                params.append(status)
            sql += " ORDER BY sla_due_at NULLS LAST, created_at"
            cur = con.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []


def assign_review(review_id: str, owner: str) -> dict[str, Any]:
    """Claim a review: open → assigned (owner recorded)."""
    owner = (owner or "").strip()
    if not owner:
        raise ValueError("owner required")
    with ops_con() as con:
        row = con.execute(
            "SELECT status FROM review_queue WHERE review_id = ?", [review_id]
        ).fetchone()
        if not row:
            raise LookupError(f"review not found: {review_id}")
        if row[0] not in ("open", "assigned"):
            raise ValueError(f"review is {row[0]}, cannot assign")
        con.execute(
            "UPDATE review_queue SET status = 'assigned', owner = ? WHERE review_id = ?",
            [owner[:80], review_id],
        )
    return {"review_id": review_id, "status": "assigned", "owner": owner[:80]}


def resolve_review(
    review_id: str,
    verdict: str,
    *,
    actor: str = "",
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """Close a review with a verdict (board #9 taxonomy).

    ``ai_wrong`` verdicts are the labeled examples that feed the eval
    harness (see export_audit_regressions); ``false_alarm`` tunes Qubot
    precision tracking.
    """
    verdict = (verdict or "").strip().lower()
    if verdict not in ("ai_wrong", "data_drift", "false_alarm"):
        raise ValueError("verdict must be ai_wrong|data_drift|false_alarm")
    iid = interaction_id
    with ops_con() as con:
        row = con.execute(
            "SELECT status, interaction_id FROM review_queue WHERE review_id = ?",
            [review_id],
        ).fetchone()
        if not row:
            raise LookupError(f"review not found: {review_id}")
        if row[0] not in ("open", "assigned"):
            raise ValueError(f"review is {row[0]}, cannot resolve")
        iid = iid or row[1]
        con.execute(
            "UPDATE review_queue SET status = 'resolved', verdict = ? WHERE review_id = ?",
            [verdict, review_id],
        )
    try:
        from src.ledger import AgentAction, record_action

        record_action(AgentAction(
            interaction_id=str(iid or review_id),
            agent="supervisor",
            action_type="human_override",
            input_summary=f"review {review_id} actor={actor or 'unknown'}",
            output_summary=f"verdict={verdict}",
            ok=True,
        ))
    except Exception:
        pass
    return {"review_id": review_id, "status": "resolved", "verdict": verdict, "actor": actor}


def export_audit_regressions(
    *,
    since_days: int = 7,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Export review-queue mismatches as eval regression fixtures (board #9).

    Every ``needs_review`` / ``unverifiable`` insight becomes one JSONL case
    with the contact's customer turns (input) and the flagged summary
    (expected failure signature). The eval harness consumes this directory
    to stop the same audit finding from recurring silently. Returns counts.
    """
    from datetime import timedelta as _td
    from pathlib import Path as _Path

    from src.data.timeutil import utc_now as _now

    dest = _Path(out_dir) if out_dir else _Path("reports") / "regression"
    dest.mkdir(parents=True, exist_ok=True)
    cutoff = _now() - _td(days=max(1, int(since_days)))
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT review_id, reason, interaction_id, case_id, NULL,
                       verdict, created_at
                FROM review_queue
                WHERE verdict = 'ai_wrong'
                  AND created_at >= ?
                ORDER BY created_at
                """,
                [cutoff],
            ).fetchall()
        except Exception:
            rows = []
    import json as _json

    day = _now().date().isoformat()
    path = dest / f"audit_{day}.jsonl"
    written = 0
    with open(path, "a", encoding="utf-8") as fh:
        for qid, kind, iid, cid, aid, summary, created in rows:
            turns: list[str] = []
            if iid:
                try:
                    with ops_con(read_only=True) as con2:
                        from src.data.turns import reveal_turn_text
                        from src.security.pii import redact_pii

                        turns = []
                        for r in con2.execute(
                            "SELECT text FROM interaction_turns"
                            " WHERE interaction_id = ? AND speaker = 'customer'"
                            " ORDER BY seq",
                            [iid],
                        ).fetchall():
                            turns.append(redact_pii(reveal_turn_text(iid, str(r[0] or ""))))
                except Exception:
                    turns = []
            fh.write(_json.dumps({
                "queue_id": qid,
                "kind": kind,
                "interaction_id": iid,
                "case_id": cid,
                "action_id": aid,
                "customer_turns": turns,
                "expected_failure": summary or kind,
                "exported_at": _now().isoformat(),
            }) + "\n")
            written += 1
    return {"path": str(path), "written": written, "since_days": since_days}
