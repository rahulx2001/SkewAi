"""Auditor-gated hypothesis RCA, adversarial scoring, exec briefing, thumbs."""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.qubot.claims import BoundClaim, audit_bound_claims
from src.frontline.provenance import list_kpis


def _as_claim(raw: BoundClaim | dict[str, Any]) -> BoundClaim:
    if isinstance(raw, BoundClaim):
        return raw
    return BoundClaim(
        str(raw.get("claim_text") or raw.get("text") or ""),
        str(raw.get("evidence_id") or ""),
        int(raw.get("span_start") or 0),
        int(raw.get("span_end") or 0),
    )


def run_hypothesis_rca(
    hypotheses: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Show only hypotheses whose claims Qubot grounds; withhold the rest."""
    shown: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for h in hypotheses:
        claims = [_as_claim(c) for c in (h.get("claims") or [])]
        audit = audit_bound_claims(claims, snapshots)
        item = {
            "id": h.get("id") or "h",
            "text": h.get("text") or "",
            "audit": {"ok": audit.ok, "rejected": audit.rejected},
        }
        if audit.ok and claims:
            shown.append(item)
        else:
            withheld.append(item)
    return {"shown": shown, "withheld": withheld}


def adversarial_score(
    left: dict[str, Any],
    right: dict[str, Any],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Higher score = more grounded claims / fewer rejects."""

    def _score(h: dict[str, Any]) -> tuple[int, int, bool]:
        claims = [_as_claim(c) for c in (h.get("claims") or [])]
        audit = audit_bound_claims(claims, snapshots)
        grounded_n = max(0, audit.checked - len(audit.rejected))
        return grounded_n, len(audit.rejected), audit.ok

    lg, lr, lok = _score(left)
    rg, rr, rok = _score(right)
    # Prefer more grounded, then fewer rejects
    left_key = (lg, -lr)
    right_key = (rg, -rr)
    if left_key > right_key:
        winner = "left"
    elif right_key > left_key:
        winner = "right"
    else:
        winner = "tie"
    return {
        "winner": winner,
        "left": {"grounded_claims": lg, "rejected": lr, "ok": lok},
        "right": {"grounded_claims": rg, "rejected": rr, "ok": rok},
    }


def weekly_exec_briefing(*, pack_id: str | None = None) -> dict[str, Any]:
    kpis = list_kpis()
    lines = [f"{k['kpi_id']}={k['value']}" for k in kpis]
    return {
        "title": "Weekly quality briefing",
        "pack_id": pack_id,
        "kpis": kpis,
        "body": "Grounded ops snapshot: " + "; ".join(lines),
        "generated_at": utc_now().isoformat(),
        "grounded": True,
    }


def record_thumbs(
    *,
    suggestion_id: str,
    up: bool,
    interaction_id: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    tid = "th_" + new_ulid()
    with ops_con() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS suggestion_feedback (
                feedback_id VARCHAR PRIMARY KEY,
                suggestion_id VARCHAR NOT NULL,
                thumbs_up BOOLEAN NOT NULL,
                note TEXT,
                interaction_id VARCHAR,
                created_at TIMESTAMP
            )
            """
        )
        con.execute(
            """
            INSERT INTO suggestion_feedback
            (feedback_id, suggestion_id, thumbs_up, note, interaction_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [tid, suggestion_id, bool(up), note, interaction_id, utc_now()],
        )
    return {
        "feedback_id": tid,
        "suggestion_id": suggestion_id,
        "thumbs_up": bool(up),
        "stored": True,
    }


def list_thumbs(suggestion_id: str | None = None) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            if suggestion_id:
                rows = con.execute(
                    "SELECT feedback_id, suggestion_id, thumbs_up FROM suggestion_feedback WHERE suggestion_id = ?",
                    [suggestion_id],
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT feedback_id, suggestion_id, thumbs_up FROM suggestion_feedback"
                ).fetchall()
        except Exception:
            return []
    return [
        {"feedback_id": a, "suggestion_id": b, "thumbs_up": bool(c)} for a, b, c in rows
    ]


__all__ = [
    "run_hypothesis_rca",
    "adversarial_score",
    "weekly_exec_briefing",
    "record_thumbs",
    "list_thumbs",
]
