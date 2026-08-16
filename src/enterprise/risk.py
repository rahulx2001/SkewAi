"""Predictive escalation engine — live risk scores from contact signals.

Deterministic scoring (no ML model): frustration trend, safety, turn depth,
severity/priority when present. Useful for Live Console risk chips.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con
from src.ids import new_ulid


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score_from_signals(
    *,
    peak_frustration: float = 0.0,
    last_frustration: float = 0.0,
    turn_count: int = 0,
    safety_flag_count: int = 0,
    supervised: bool = False,
    severity: str | None = None,
    priority: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Pure risk scorer — unit-testable without DB."""
    peak = float(peak_frustration or 0.0)
    last = float(last_frustration or 0.0)
    trend = last - (peak * 0.5)  # rough: recent vs peak context
    # Escalation: frustration + safety dominate
    esc = 0.15
    esc += 0.55 * peak
    esc += 0.25 * min(1.0, safety_flag_count / 2.0)
    if (severity or "").lower() == "critical":
        esc += 0.2
    if priority is not None and int(priority) <= 1:
        esc += 0.15
    if turn_count >= 8:
        esc += 0.1
    if supervised:
        esc -= 0.1  # human already engaged
    esc = _clamp(esc)

    # Churn proxy: abandonment risk from high last frustration + long calls
    churn = 0.1 + 0.5 * last + 0.15 * min(1.0, turn_count / 12.0)
    if safety_flag_count:
        churn += 0.1
    churn = _clamp(churn)

    # Sentiment trend: negative if last high and rising toward peak
    sentiment_trend = _clamp(0.5 + (last - 0.4), 0.0, 1.0)  # higher = worse

    # Est remaining turns (inverse of progress signals)
    if status in ("completed", "escalated", "abandoned"):
        eta = 0.0
    else:
        eta = max(1.0, 10.0 - turn_count * 0.8 - peak * 3.0)
        if safety_flag_count:
            eta = min(eta, 2.0)

    factors = {
        "peak_frustration": peak,
        "last_frustration": last,
        "turn_count": turn_count,
        "safety_flag_count": safety_flag_count,
        "supervised": supervised,
        "severity": severity,
        "priority": priority,
    }
    return {
        "escalation_prob": round(esc, 3),
        "churn_prob": round(churn, 3),
        "sentiment_trend": round(sentiment_trend, 3),
        "est_resolution_turns": round(eta, 1),
        "risk_level": (
            "critical" if esc >= 0.75 else "high" if esc >= 0.5 else "medium" if esc >= 0.3 else "low"
        ),
        "factors": factors,
    }


def score_interaction_risk(
    interaction_id: str,
    *,
    persist: bool = False,
) -> dict[str, Any]:
    """Score one interaction from warehouse state."""
    with ops_con(read_only=True) as con:
        h = con.execute(
            """
            SELECT interaction_id, status, supervised, peak_frustration, last_frustration
            FROM interactions WHERE interaction_id = ?
            """,
            [interaction_id],
        ).fetchone()
        if not h:
            raise LookupError(f"interaction not found: {interaction_id}")
        ix = {
            "interaction_id": h[0],
            "status": h[1],
            "supervised": h[2],
            "peak_frustration": h[3],
            "last_frustration": h[4],
        }
        turn_count = con.execute(
            "SELECT COUNT(*) FROM interaction_turns WHERE interaction_id = ? AND speaker = 'customer'",
            [interaction_id],
        ).fetchone()[0]
        case = con.execute(
            "SELECT severity, priority, safety_flags FROM cases WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()

    safety_n = 0
    severity = None
    priority = None
    if case:
        severity, priority, sf = case[0], case[1], case[2]
        if isinstance(sf, str):
            try:
                sf = json.loads(sf)
            except Exception:
                sf = {}
        if isinstance(sf, dict):
            safety_n = sum(1 for v in sf.values() if v)

    scores = score_from_signals(
        peak_frustration=float(ix.get("peak_frustration") or 0.0),
        last_frustration=float(ix.get("last_frustration") or 0.0),
        turn_count=int(turn_count or 0),
        safety_flag_count=safety_n,
        supervised=bool(ix.get("supervised")),
        severity=severity,
        priority=priority,
        status=ix.get("status"),
    )
    scores["interaction_id"] = interaction_id
    scores["status"] = ix.get("status")

    if persist:
        from src.data.timeutil import utc_now

        sid = "rsk_" + new_ulid()
        now = utc_now()
        with ops_con() as con:
            con.execute(
                """
                INSERT INTO risk_snapshots
                (snapshot_id, interaction_id, ts, escalation_prob, churn_prob,
                 sentiment_trend, est_resolution_turns, factors_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    sid,
                    interaction_id,
                    now,
                    scores["escalation_prob"],
                    scores["churn_prob"],
                    scores["sentiment_trend"],
                    scores["est_resolution_turns"],
                    json.dumps(scores["factors"]),
                ],
            )
        scores["snapshot_id"] = sid

    return scores


def score_active_risks(limit: int = 50, *, persist: bool = False) -> list[dict[str, Any]]:
    """Score all active interactions for Live Console risk board.

    When ``persist=True``, each score is also written to ``risk_snapshots``
    so operators can chart history (pilot; not a streaming ML pipeline).
    """
    with ops_con(read_only=True) as con:
        rows = con.execute(
            """
            SELECT interaction_id FROM interactions
            WHERE status = 'active'
            ORDER BY started_at DESC
            LIMIT ?
            """,
            [min(max(int(limit), 1), 200)],
        ).fetchall()
    out = []
    for (iid,) in rows:
        try:
            out.append(score_interaction_risk(iid, persist=persist))
        except Exception:
            continue
    out.sort(key=lambda r: r.get("escalation_prob", 0), reverse=True)
    return out


def list_risk_history(interaction_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return stored risk_snapshots for one interaction (newest first)."""
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        # Ensure interaction exists
        exists = con.execute(
            "SELECT 1 FROM interactions WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()
        if not exists:
            raise LookupError(f"interaction not found: {interaction_id}")
        cur = con.execute(
            """
            SELECT snapshot_id, interaction_id, ts, escalation_prob, churn_prob,
                   sentiment_trend, est_resolution_turns, factors_json
            FROM risk_snapshots
            WHERE interaction_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            [interaction_id, limit],
        )
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            if isinstance(d.get("ts"), datetime):
                d["ts"] = d["ts"].isoformat()
            fj = d.get("factors_json")
            if isinstance(fj, str):
                try:
                    d["factors"] = json.loads(fj)
                except Exception:
                    d["factors"] = {}
            else:
                d["factors"] = {}
            rows.append(d)
    return rows
