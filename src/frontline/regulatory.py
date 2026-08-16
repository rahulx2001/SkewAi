"""Recall decision-support, regulatory drafts, statutory clocks, FSN."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.data.timeutil import to_naive_utc, utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.ledger import AgentAction, record_action
from src.qubot.claims import BoundClaim, audit_bound_claims


def recall_decision(
    *,
    cluster_id: int,
    live_count: int,
    historical_threshold: int,
    evidence_ids: list[str],
    pack_id: str = "automotive_nhtsa",
) -> dict[str, Any]:
    """Grounded iff live_count crosses a historical recall-warranting threshold."""
    crossed = int(live_count) >= int(historical_threshold) > 0
    bundle_id = None
    if crossed:
        from src.qubot.locker import export_locker

        iid = f"int_recall_{cluster_id}"
        with ops_con() as con:
            exists = con.execute(
                "SELECT 1 FROM interactions WHERE interaction_id = ?", [iid]
            ).fetchone()
            if not exists:
                con.execute(
                    """
                    INSERT INTO interactions
                    (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
                    VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
                    """,
                    [iid, pack_id, utc_now()],
                )
        record_action(
            AgentAction(
                interaction_id=iid,
                agent="investigator",
                action_type="cluster_matched",
                output_summary=f"recall threshold {historical_threshold} crossed at {live_count}",
                evidence_ids=list(evidence_ids),
            )
        )
        try:
            path = export_locker(iid)
            bundle_id = str(path)
        except Exception:
            bundle_id = f"locker:{iid}"
    return {
        "cluster_id": cluster_id,
        "live_count": int(live_count),
        "historical_threshold": int(historical_threshold),
        "crossed": crossed,
        "grounded": crossed and bool(evidence_ids),
        "evidence_ids": list(evidence_ids),
        "evidence_bundle": bundle_id,
    }


def draft_filing(
    kind: str,
    *,
    case: dict[str, Any],
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Draft NHTSA EWR quarterly, FDA MDR, or CPSC 15(b) from an audited case."""
    forms = {
        "ewr": "NHTSA EWR quarterly",
        "mdr": "FDA MDR",
        "15b": "CPSC 15(b)",
    }
    key = kind.lower().replace(" ", "").replace("-", "")
    if key not in forms:
        raise ValueError(f"unknown filing kind {kind}")
    eids = [str(e) for e in (evidence_ids or case.get("evidence_ids") or [])]
    case_id = case.get("case_id") or ""
    return {
        "kind": key,
        "form": forms[key],
        "case_id": case_id,
        "evidence_ids": eids,
        "body": (
            f"{forms[key]} draft for case {case_id}. "
            f"Category={case.get('category')}; severity={case.get('severity')}. "
            f"Cited evidence: {', '.join(eids) or 'none'}."
        ),
        "grounded": bool(eids),
    }


def clock_status(
    opened_at: datetime,
    *,
    days: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    start = to_naive_utc(opened_at)
    due = start + timedelta(days=int(days))
    t = to_naive_utc(now or utc_now())
    overdue = t > due
    remaining = (due - t).total_seconds() / 86400.0
    return {
        "opened_at": start.isoformat(),
        "due_at": due.isoformat(),
        "days": int(days),
        "overdue": overdue,
        "days_remaining": remaining,
    }


def fire_clock_alert(
    *,
    ref_id: str,
    opened_at: datetime,
    days: int = 5,
    channel: str = "slack",
) -> dict[str, Any]:
    st = clock_status(opened_at, days=days)
    if not st["overdue"]:
        return {"fired": False, **st}
    from src.frontline.webhook_catalog import fire_due_tick

    payload = fire_due_tick(force=True, channel=channel)
    payload["event"] = "statutory_clock_overdue"
    payload["ref_id"] = ref_id
    payload["clock"] = st
    payload["fired"] = True
    return payload


def draft_field_safety_notice(
    claims: list[BoundClaim] | list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Customer-facing notice: only span-supported claims are included."""
    from src.qubot.claims import cited_text_from_snapshot, span_supported

    by_id = {
        str(s.get("evidence_id")): cited_text_from_snapshot(s.get("body_json") or {})
        for s in snapshots
    }
    kept: list[dict[str, Any]] = []
    withheld: list[str] = []
    for raw in claims:
        if isinstance(raw, BoundClaim):
            c = raw
        else:
            c = BoundClaim(
                str(raw.get("claim_text") or ""),
                str(raw.get("evidence_id") or ""),
                int(raw.get("span_start") or 0),
                int(raw.get("span_end") or 0),
            )
        src = by_id.get(c.evidence_id)
        if src is None or not span_supported(src, c.span_start, c.span_end, c.claim_text):
            withheld.append(c.claim_text or c.evidence_id)
            continue
        kept.append(
            {
                "claim_text": c.claim_text,
                "evidence_id": c.evidence_id,
                "span_start": c.span_start,
                "span_end": c.span_end,
            }
        )
    return {
        "ok": bool(kept) and not withheld,
        "claims": kept,
        "withheld": withheld,
        "notice": " ".join(k["claim_text"] for k in kept).strip(),
        "grounded": bool(kept),
    }


__all__ = [
    "recall_decision",
    "draft_filing",
    "clock_status",
    "fire_clock_alert",
    "draft_field_safety_notice",
]
