"""CSAT proxy + product-gap quality board from real ops rows.

Honest labeling: we do not invent survey NPS. Satisfaction is a **friction
proxy** from peak_frustration, outcomes, and safety flags.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con

_SEV_RANK = {"Low": 1, "Medium": 2, "Critical": 3}


def _cutoff_days(window_days: int):
    return utc_now() - timedelta(days=max(1, int(window_days)))


def build_csat_themes(*, window_days: int = 7, pack_id: str | None = None) -> dict[str, Any]:
    """Satisfaction-and-themes surface from interactions + cases."""
    cutoff = _cutoff_days(window_days)
    with ops_con(read_only=True) as con:
        # Interactions in window
        sql_ix = """
            SELECT interaction_id, pack_id, category, outcome, status,
                   peak_frustration, last_frustration, started_at
            FROM interactions
            WHERE started_at >= ?
        """
        params: list[Any] = [cutoff]
        if pack_id:
            sql_ix += " AND pack_id = ?"
            params.append(pack_id)
        rows = con.execute(sql_ix, params).fetchall()
        cols = [
            "interaction_id",
            "pack_id",
            "category",
            "outcome",
            "status",
            "peak_frustration",
            "last_frustration",
            "started_at",
        ]
        interactions = [dict(zip(cols, r)) for r in rows]

        n = len(interactions)
        frust_vals = [
            float(i["peak_frustration"])
            for i in interactions
            if i.get("peak_frustration") is not None
        ]
        avg_frust = sum(frust_vals) / len(frust_vals) if frust_vals else 0.0
        # Proxy: 1 - clamped frustration (higher = better satisfaction)
        satisfaction_proxy = max(0.0, min(1.0, 1.0 - avg_frust))
        angry = sum(1 for v in frust_vals if v >= 0.65)

        outcomes: dict[str, int] = defaultdict(int)
        for i in interactions:
            outcomes[str(i.get("outcome") or i.get("status") or "unknown")] += 1

        # Themes from categories (cases preferred, then interactions)
        sql_cat = """
            SELECT category, COUNT(*) AS n,
                   AVG(CASE severity
                         WHEN 'Critical' THEN 3
                         WHEN 'Medium' THEN 2
                         WHEN 'Low' THEN 1 ELSE 0 END) AS avg_sev
            FROM cases
            WHERE created_at >= ?
              AND category IS NOT NULL AND category != ''
        """
        p2: list[Any] = [cutoff]
        if pack_id:
            sql_cat += " AND pack_id = ?"
            p2.append(pack_id)
        sql_cat += " GROUP BY category ORDER BY n DESC LIMIT 10"
        themes = [
            {
                "theme": r[0],
                "volume": int(r[1]),
                "avg_severity_rank": float(r[2] or 0),
            }
            for r in con.execute(sql_cat, p2).fetchall()
        ]
        if not themes:
            cat_counts: dict[str, int] = defaultdict(int)
            for i in interactions:
                if i.get("category"):
                    cat_counts[str(i["category"])] += 1
            themes = [
                {"theme": k, "volume": v, "avg_severity_rank": 0.0}
                for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])[:10]
            ]

        safety_n = con.execute(
            """
            SELECT COUNT(*) FROM cases
            WHERE created_at >= ?
              AND safety_flags IS NOT NULL
              AND safety_flags != '{}'
              AND safety_flags != 'null'
            """
            + (" AND pack_id = ?" if pack_id else ""),
            ([cutoff, pack_id] if pack_id else [cutoff]),
        ).fetchone()[0]

    return {
        "label": "friction_proxy_not_survey_nps",
        "window_days": window_days,
        "pack_id": pack_id,
        "contact_count": n,
        "satisfaction_proxy": round(satisfaction_proxy, 3),
        "avg_peak_frustration": round(avg_frust, 3),
        "angry_contacts": angry,
        "safety_flagged_cases": int(safety_n or 0),
        "outcome_mix": dict(outcomes),
        "top_themes": themes,
        "ts": utc_now().isoformat() + "Z",
    }


def build_product_gap_board(
    *,
    window_days: int = 14,
    pack_id: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Top product issues + severity mix + drift (recent vs prior half-window)."""
    window_days = max(2, int(window_days))
    now = utc_now()
    cutoff = now - timedelta(days=window_days)
    mid = now - timedelta(days=window_days // 2)

    with ops_con(read_only=True) as con:
        sql = """
            SELECT
              COALESCE(CAST(cluster_match_id AS VARCHAR), category, 'uncategorized') AS issue_key,
              cluster_match_id,
              category,
              COUNT(*) AS volume,
              SUM(CASE WHEN severity = 'Critical' THEN 1 ELSE 0 END) AS n_critical,
              SUM(CASE WHEN severity = 'Medium' THEN 1 ELSE 0 END) AS n_medium,
              SUM(CASE WHEN severity = 'Low' THEN 1 ELSE 0 END) AS n_low,
              SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS recent_n,
              SUM(CASE WHEN created_at < ? THEN 1 ELSE 0 END) AS prior_n,
              SUM(CASE WHEN created_at >= ? AND severity = 'Critical' THEN 1 ELSE 0 END) AS recent_crit,
              SUM(CASE WHEN created_at < ? AND severity = 'Critical' THEN 1 ELSE 0 END) AS prior_crit
            FROM cases
            WHERE created_at >= ?
        """
        params: list[Any] = [mid, mid, mid, mid, cutoff]
        if pack_id:
            sql += " AND pack_id = ?"
            params.append(pack_id)
        sql += """
            GROUP BY 1, 2, 3
            ORDER BY volume DESC
            LIMIT ?
        """
        params.append(int(limit))
        rows = con.execute(sql, params).fetchall()

    issues = []
    for r in rows:
        volume = int(r[3] or 0)
        recent_n = int(r[7] or 0)
        prior_n = int(r[8] or 0)
        recent_crit = int(r[9] or 0)
        prior_crit = int(r[10] or 0)
        recent_crit_rate = (recent_crit / recent_n) if recent_n else 0.0
        prior_crit_rate = (prior_crit / prior_n) if prior_n else 0.0
        drift = recent_crit_rate - prior_crit_rate
        getting_worse = drift > 0.05 or (recent_n > prior_n and recent_crit > prior_crit)
        issues.append(
            {
                "issue_key": r[0],
                "cluster_id": r[1],
                "category": r[2],
                "volume": volume,
                "severity_mix": {
                    "Critical": int(r[4] or 0),
                    "Medium": int(r[5] or 0),
                    "Low": int(r[6] or 0),
                },
                "recent_volume": recent_n,
                "prior_volume": prior_n,
                "severity_drift": round(drift, 3),
                "getting_worse": bool(getting_worse),
            }
        )

    # Rank critical-heavy above low-only when volume equal (stable sort)
    issues.sort(
        key=lambda x: (
            -x["volume"],
            -x["severity_mix"]["Critical"],
            -x["severity_drift"],
        )
    )

    rising = [i for i in issues if i["getting_worse"]][:5]
    return {
        "window_days": window_days,
        "pack_id": pack_id,
        "top_issues": issues,
        "rising_issues": rising,
        "ts": utc_now().isoformat() + "Z",
    }


__all__ = ["build_csat_themes", "build_product_gap_board"]
