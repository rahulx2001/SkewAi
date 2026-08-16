"""Continuous learning engine — proposals from failure/audit signals.

Pipeline (deterministic):
  failure-like interactions → root_cause analyzer → proposal rows → human review.

Does not auto-deploy model weights or open GitHub PRs; stores reviewable proposals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con
from src.enterprise.root_cause import analyze_root_cause, list_failure_postmortems
from src.ids import new_ulid

PROPOSAL_STATUSES = frozenset({"proposed", "approved", "rejected", "deployed"})

# Map root-cause codes → suggested platform improvements (offline templates).
_CHANGE_TEMPLATES = {
    "agent_error": (
        "Review failed agent_action rows for this path; add a regression fixture "
        "and tighten error handling for the blamed agent."
    ),
    "abandoned_or_incomplete": (
        "Shorten intake first-ask; reduce required slots for first resolution; "
        "A/B test greeting length in experiment registry."
    ),
    "safety_or_escalation": (
        "Validate kill-switch terms and escalation script; ensure P1 case + "
        "connector export fire; audit safety_policy artifact version."
    ),
    "high_frustration": (
        "Offer human handoff earlier; tune FRUSTRATION_THRESHOLD; experiment "
        "with de-escalation prompt/template version."
    ),
    "incomplete_slots": (
        "Expand gazetteers for missing entity slots; add pack-specific slot "
        "examples; measure fill rate in next eval run."
    ),
    "early_drop": (
        "Lead with highest-value question; reduce greeting verbosity; track "
        "turns-to-first-slot in experiments."
    ),
    "no_failure_signal": (
        "No corrective action required; retain as baseline for comparison."
    ),
    "knowledge_gap": (
        "Add advisory/corpus coverage for unmatched category; seed domain "
        "records; open investigation if cluster threshold met."
    ),
}


def _now() -> datetime:
    from src.data.timeutil import utc_now

    return utc_now()


def _iso_row(d: dict[str, Any]) -> dict[str, Any]:
    from src.data.timeutil import to_iso_z

    out = dict(d)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = to_iso_z(v)
        if k == "evidence_ids" and isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except Exception:
                out[k] = []
    return out


def _existing_open_for_interaction(interaction_id: str) -> bool:
    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT 1 FROM learning_proposals
            WHERE interaction_id = ? AND status IN ('proposed', 'approved')
            LIMIT 1
            """,
            [interaction_id],
        ).fetchone()
    return bool(row)


def generate_proposal_for_interaction(
    interaction_id: str,
    *,
    source: str = "root_cause",
) -> dict[str, Any] | None:
    """Create one proposal from root-cause analysis. None if not a failure / already open."""
    try:
        rc = analyze_root_cause(interaction_id)
    except LookupError:
        return None
    if not rc.get("is_failure"):
        return None
    if _existing_open_for_interaction(interaction_id):
        return None

    weakness = rc.get("primary_cause") or "unknown"
    if weakness == "no_failure_signal":
        return None

    # Knowledge gap heuristic: incomplete slots or no advisory with abandoned
    if weakness == "incomplete_slots" and rc.get("status") == "abandoned":
        weakness = "knowledge_gap" if not rc.get("case") else weakness

    title = f"{weakness} on {interaction_id}"
    detail = (
        f"blame={rc.get('blame_agent')}; confidence={rc.get('confidence')}; "
        f"why={rc.get('why')}; status={rc.get('status')}; outcome={rc.get('outcome')}"
    )
    suggested = _CHANGE_TEMPLATES.get(
        weakness,
        rc.get("suggested_fix") or "Review incident timeline and ledger.",
    )
    impact = float(rc.get("confidence") or 0.5)
    evidence = [interaction_id]
    if rc.get("blame_agent"):
        evidence.append(f"agent:{rc['blame_agent']}")

    pid = "prop_" + new_ulid()
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO learning_proposals
            (proposal_id, created_at, updated_at, status, weakness_class, title, detail,
             evidence_ids, suggested_change, impact_score, source, interaction_id)
            VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                pid,
                now,
                now,
                weakness,
                title,
                detail,
                json.dumps(evidence),
                suggested,
                impact,
                source,
                interaction_id,
            ],
        )
    return get_proposal(pid)


def generate_proposals_from_failures(*, limit: int = 25) -> dict[str, Any]:
    """Scan recent failure-like contacts and insert new proposals."""
    posts = list_failure_postmortems(limit=limit)
    created: list[dict[str, Any]] = []
    skipped = 0
    for p in posts:
        iid = p.get("interaction_id")
        if not iid:
            continue
        prop = generate_proposal_for_interaction(iid, source="batch_scan")
        if prop:
            created.append(prop)
        else:
            skipped += 1
    return {
        "created": len(created),
        "skipped": skipped,
        "proposals": created,
    }


def get_proposal(proposal_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM learning_proposals WHERE proposal_id = ?",
            [proposal_id],
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return _iso_row(dict(zip(cols, row)))


def list_proposals(
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        if status:
            cur = con.execute(
                """
                SELECT * FROM learning_proposals
                WHERE status = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                [status, limit],
            )
        else:
            cur = con.execute(
                """
                SELECT * FROM learning_proposals
                ORDER BY created_at DESC LIMIT ?
                """,
                [limit],
            )
        cols = [d[0] for d in cur.description]
        return [_iso_row(dict(zip(cols, r))) for r in cur.fetchall()]


def review_proposal(
    proposal_id: str,
    *,
    status: str,
    reviewed_by: str = "operator",
    review_note: str = "",
) -> dict[str, Any]:
    if status not in PROPOSAL_STATUSES or status == "proposed":
        raise ValueError(
            f"status must be one of approved|rejected|deployed (got {status!r})"
        )
    row = get_proposal(proposal_id)
    if not row:
        raise LookupError(f"proposal not found: {proposal_id}")
    if row["status"] not in ("proposed", "approved") and status == "deployed":
        # allow deploy only from proposed/approved
        pass
    if row["status"] in ("rejected",) and status != "rejected":
        raise ValueError("cannot reopen rejected proposal")
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            UPDATE learning_proposals
            SET status = ?, updated_at = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?
            WHERE proposal_id = ?
            """,
            [
                status,
                now,
                (reviewed_by or "operator")[:80],
                now,
                (review_note or "")[:1000],
                proposal_id,
            ],
        )
    out = get_proposal(proposal_id)
    assert out is not None
    return out


def learning_trends(*, window_days: int = 30) -> dict[str, Any]:
    """Aggregate proposal counts by status and weakness class."""
    window_days = min(max(int(window_days), 1), 365)
    with ops_con(read_only=True) as con:
        by_status = con.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM learning_proposals
            WHERE created_at >= now() - INTERVAL (? || ' days')
            GROUP BY status
            """,
            [str(window_days)],
        ).fetchall()
        by_class = con.execute(
            """
            SELECT weakness_class, COUNT(*) AS n
            FROM learning_proposals
            WHERE created_at >= now() - INTERVAL (? || ' days')
            GROUP BY weakness_class
            ORDER BY n DESC
            """,
            [str(window_days)],
        ).fetchall()
        total = con.execute(
            """
            SELECT COUNT(*) FROM learning_proposals
            WHERE created_at >= now() - INTERVAL (? || ' days')
            """,
            [str(window_days)],
        ).fetchone()[0]
    return {
        "window_days": window_days,
        "total": int(total or 0),
        "by_status": {str(s): int(n) for s, n in by_status},
        "by_weakness_class": {str(c): int(n) for c, n in by_class},
    }


def maybe_propose_from_interaction(interaction_id: str) -> None:
    """Best-effort hook after contact finalize — never raises."""
    try:
        generate_proposal_for_interaction(interaction_id, source="contact_finalize")
    except Exception:
        pass
