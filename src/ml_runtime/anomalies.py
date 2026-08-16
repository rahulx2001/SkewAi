"""Weekly volume anomalies computed from ``records`` (not seed literals).

For each (iso_week, category, entity_2) slice, z-score is
``(count - mean) / std`` over that category+entity's weekly counts.
``is_anomaly`` is true when z >= 2.0 and there are at least two weeks.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from src.data.warehouse import apply_domain_schema, domain_con

ANOMALY_Z = 2.0


def iso_week_label(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def count_weekly_slices(records: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str], int]:
    """(iso_week, category, entity_2) → count."""
    out: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in records:
        week = iso_week_label(r.get("received_at") or r.get("occurred_at"))
        if not week:
            continue
        cat = str(r.get("category") or "")
        ent = str(r.get("entity_2") or "")
        out[(week, cat, ent)] += 1
    return dict(out)


def score_weekly_slices(
    counts: dict[tuple[str, str, str], int],
    *,
    pack_id: str,
) -> list[dict[str, Any]]:
    """Attach z_score / is_anomaly. Pure; no I/O."""
    by_group: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for (week, cat, ent), n in counts.items():
        by_group[(cat, ent)].append((week, n))

    rows: list[dict[str, Any]] = []
    for (cat, ent), weeks in by_group.items():
        for week, n in weeks:
            others = [c for w, c in weeks if w != week]
            if len(others) < 2:
                mean = sum(c for _, c in weeks) / len(weeks)
                std = 0.0
                z = 0.0
            else:
                mean = sum(others) / len(others)
                var = sum((v - mean) ** 2 for v in others) / (len(others) - 1)
                std = math.sqrt(var)
                z = 0.0 if std == 0.0 else (n - mean) / std
                if std == 0.0 and n > mean:
                    # Constant baseline, then a jump: treat as anomaly.
                    z = float(n - mean)
            rows.append(
                {
                    "pack_id": pack_id,
                    "iso_week": week,
                    "category": cat,
                    "entity_2": ent,
                    "record_count": n,
                    "baseline_mean": mean,
                    "baseline_std": std,
                    "z_score": z,
                    "is_anomaly": bool(z >= ANOMALY_Z),
                }
            )
    return rows


def recompute_weekly_anomalies(
    pack_id: str,
    *,
    category: str | None = None,
    entity_2: str | None = None,
) -> list[dict[str, Any]]:
    """Read ``records``, replace ``weekly_anomalies`` for *pack_id*, return rows.

    Optional category / entity_2 restrict the recompute to one slice so a live
    contact does not rescan the whole warehouse.
    """
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        sql = "SELECT received_at, occurred_at, category, entity_2 FROM records"
        params: list[Any] = []
        wheres: list[str] = []
        if category:
            wheres.append("category = ?")
            params.append(category)
        if entity_2:
            wheres.append("entity_2 = ?")
            params.append(entity_2)
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        raw = con.execute(sql, params).fetchall()
        cols = [d[0] for d in con.description]
        records = [dict(zip(cols, r)) for r in raw]
        scored = score_weekly_slices(count_weekly_slices(records), pack_id=pack_id)
        if category or entity_2:
            dsql = "DELETE FROM weekly_anomalies WHERE pack_id = ?"
            dparams: list[Any] = [pack_id]
            if category:
                dsql += " AND category = ?"
                dparams.append(category)
            if entity_2:
                dsql += " AND entity_2 = ?"
                dparams.append(entity_2)
            con.execute(dsql, dparams)
        else:
            con.execute("DELETE FROM weekly_anomalies WHERE pack_id = ?", [pack_id])
        for row in scored:
            con.execute(
                """
                INSERT INTO weekly_anomalies (
                    pack_id, iso_week, category, entity_2, record_count,
                    baseline_mean, baseline_std, z_score, is_anomaly
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["pack_id"],
                    row["iso_week"],
                    row["category"],
                    row["entity_2"],
                    row["record_count"],
                    row["baseline_mean"],
                    row["baseline_std"],
                    row["z_score"],
                    row["is_anomaly"],
                ],
            )
    return scored


__all__ = [
    "ANOMALY_Z",
    "iso_week_label",
    "count_weekly_slices",
    "score_weekly_slices",
    "recompute_weekly_anomalies",
]
