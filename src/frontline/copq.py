"""COPQ, dollar rank, ROI, warranty reserve, failure rate per 1,000 units."""

from __future__ import annotations

import math
from typing import Any, Iterable

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid


def issue_copq(
    *,
    warranty_per_claim: float,
    labor_per_claim: float = 0.0,
    recall_cost: float = 0.0,
    claim_count: int = 1,
) -> dict[str, Any]:
    """Cost of poor quality for one issue slice. Pure."""
    n = max(0, int(claim_count))
    warranty = float(warranty_per_claim) * n
    labor = float(labor_per_claim) * n
    recall = float(recall_cost)
    total = warranty + labor + recall
    return {
        "claim_count": n,
        "warranty": warranty,
        "labor": labor,
        "recall": recall,
        "total": total,
        "per_claim": (warranty + labor) / n if n else 0.0,
    }


def cluster_copq(
    issues: Iterable[dict[str, Any]],
    *,
    projected_extra_claims: int = 0,
) -> dict[str, Any]:
    """Sum issue costs; project extra claims at the mean per-claim cost."""
    rows = [issue_copq(**_issue_kwargs(i)) for i in issues]
    total = sum(r["total"] for r in rows)
    claims = sum(r["claim_count"] for r in rows)
    mean = (sum(r["warranty"] + r["labor"] for r in rows) / claims) if claims else 0.0
    extra = max(0, int(projected_extra_claims))
    projected = total + mean * extra
    return {
        "issue_count": len(rows),
        "claim_count": claims,
        "total": total,
        "projected_extra_claims": extra,
        "projected_total": projected,
        "issues": rows,
    }


def _issue_kwargs(i: dict[str, Any]) -> dict[str, Any]:
    return {
        "warranty_per_claim": float(i.get("warranty_per_claim") or 0),
        "labor_per_claim": float(i.get("labor_per_claim") or 0),
        "recall_cost": float(i.get("recall_cost") or 0),
        "claim_count": int(i.get("claim_count") or 1),
    }


def rank_by_dollar(slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank slices by dollar impact (not volume). Ties keep input order."""
    scored = []
    for i, sl in enumerate(slices):
        dollars = float(sl.get("dollar_impact") or sl.get("total") or 0)
        scored.append({**sl, "dollar_impact": dollars, "_ord": i})
    scored.sort(key=lambda x: (-x["dollar_impact"], x["_ord"]))
    out = []
    for rank, sl in enumerate(scored, 1):
        sl = dict(sl)
        sl.pop("_ord", None)
        sl["dollar_rank"] = rank
        out.append(sl)
    return out


def roi_attribution(
    *,
    issues_caught: int,
    copq_per_issue: float,
    lead_time_weeks: float,
) -> dict[str, Any]:
    """N issues caught = $X avoided. Lead-time scales the avoided window."""
    n = max(0, int(issues_caught))
    per = float(copq_per_issue)
    weeks = max(0.0, float(lead_time_weeks))
    avoided = n * per
    return {
        "issues_caught": n,
        "copq_per_issue": per,
        "lead_time_weeks": weeks,
        "dollars_avoided": avoided,
        "headline": f"This platform caught {n} issues = ${avoided:,.0f} avoided",
    }


def warranty_reserve(
    weekly_volumes: list[int],
    *,
    cost_per_claim: float,
    weeks_ahead: int = 13,
) -> dict[str, Any]:
    """Project reserve from recent weekly claim counts (linear + residual band)."""
    series = [max(0, int(v)) for v in weekly_volumes]
    if len(series) < 2:
        slope = 0.0
        last = series[-1] if series else 0
        resid = 0.0
    else:
        slope = (series[-1] - series[0]) / max(1, len(series) - 1)
        last = series[-1]
        fitted = [series[0] + slope * i for i in range(len(series))]
        resid = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(series, fitted)) / max(1, len(series) - 1)
        )
    ahead = max(1, int(weeks_ahead))
    path = []
    acc = 0.0
    for w in range(1, ahead + 1):
        vol = max(0.0, last + slope * w)
        acc += vol * float(cost_per_claim)
        path.append({"week": w, "projected_claims": vol, "accrual": acc})
    return {
        "weekly_volumes": series,
        "slope_per_week": slope,
        "residual_stdev": resid,
        "cost_per_claim": float(cost_per_claim),
        "weeks_ahead": ahead,
        "projected_reserve": acc,
        "ci_low": max(0.0, acc - 1.96 * resid * ahead * float(cost_per_claim)),
        "ci_high": acc + 1.96 * resid * ahead * float(cost_per_claim),
        "path": path,
    }


def failure_rate_per_1000(failures: int, units_in_service: int) -> dict[str, Any]:
    """Rate-based metric. Denominator is required; raw counts are not enough."""
    u = int(units_in_service)
    f = max(0, int(failures))
    if u <= 0:
        raise ValueError("units_in_service must be > 0")
    rate = (f / u) * 1000.0
    return {
        "failures": f,
        "units_in_service": u,
        "rate_per_1000": rate,
    }


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cluster_cost_models (
            model_id VARCHAR PRIMARY KEY,
            pack_id VARCHAR,
            cluster_id INTEGER,
            warranty_per_claim DOUBLE,
            labor_per_claim DOUBLE,
            recall_cost DOUBLE,
            claim_count INTEGER,
            created_at TIMESTAMP
        )
        """
    )


def save_cluster_cost(
    *,
    pack_id: str,
    cluster_id: int,
    warranty_per_claim: float,
    labor_per_claim: float = 0.0,
    recall_cost: float = 0.0,
    claim_count: int = 1,
) -> dict[str, Any]:
    mid = "cm_" + new_ulid()
    scored = issue_copq(
        warranty_per_claim=warranty_per_claim,
        labor_per_claim=labor_per_claim,
        recall_cost=recall_cost,
        claim_count=claim_count,
    )
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO cluster_cost_models
            (model_id, pack_id, cluster_id, warranty_per_claim, labor_per_claim,
             recall_cost, claim_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                mid,
                pack_id,
                int(cluster_id),
                warranty_per_claim,
                labor_per_claim,
                recall_cost,
                claim_count,
                utc_now(),
            ],
        )
    return {"model_id": mid, "cluster_id": cluster_id, **scored}


def load_cluster_costs(pack_id: str | None = None) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            sql = "SELECT pack_id, cluster_id, warranty_per_claim, labor_per_claim, recall_cost, claim_count FROM cluster_cost_models"
            params: list[Any] = []
            if pack_id:
                sql += " WHERE pack_id = ?"
                params.append(pack_id)
            rows = con.execute(sql, params).fetchall()
        except Exception:
            return []
    out = []
    for pack, cid, w, labor, rec, n in rows:
        scored = issue_copq(
            warranty_per_claim=w or 0,
            labor_per_claim=labor or 0,
            recall_cost=rec or 0,
            claim_count=int(n or 1),
        )
        out.append({"pack_id": pack, "cluster_id": cid, **scored})
    return out


__all__ = [
    "issue_copq",
    "cluster_copq",
    "rank_by_dollar",
    "roi_attribution",
    "warranty_reserve",
    "failure_rate_per_1000",
    "save_cluster_cost",
    "load_cluster_costs",
]
