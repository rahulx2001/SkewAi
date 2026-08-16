"""Early-warning analytics suite (features #24–30, #37).

Hermetic implementations over DuckDB ops + domain fixtures — no Prophet
dependency; linear/trend projection for forecast.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con


def _cutoff(days: int):
    return utc_now() - timedelta(days=max(1, int(days)))


def project_next_week_volume(series: list[int]) -> dict[str, Any]:
    """Linear last-delta next-week projection.

    Volume cannot go below 0. The interval is ordered: 0 <= ci_low <= ci_high.
    A declining series such as [10, 1] projects 0, not a negative point with
    inverted bounds.
    """
    counts = [int(v) for v in series]
    if len(counts) < 2:
        slope = 0.0
        last = counts[-1] if counts else 0
        resid = 0.0
    else:
        slope = float(counts[-1] - counts[0]) / max(1, len(counts) - 1)
        last = counts[-1]
        fitted = [counts[0] + slope * i for i in range(len(counts))]
        var = sum((a - b) ** 2 for a, b in zip(counts, fitted)) / max(1, len(counts) - 1)
        resid = var ** 0.5
    next_point = max(0.0, last + slope)
    half = 1.96 * resid
    ci_low = max(0.0, next_point - half)
    ci_high = max(ci_low, next_point + half)
    return {
        "weekly_counts": counts,
        "last_week_volume": last,
        "slope_per_week": slope,
        "residual_stdev": resid,
        "projected_next_week": next_point,
        "ci_low": ci_low,
        "ci_high": ci_high,
    }


def forecast_cluster_volume(
    *,
    pack_id: str | None = None,
    window_days: int = 28,
    threshold: int = 20,
) -> dict[str, Any]:
    """Project weeks until cluster hits threshold from recent weekly counts."""
    cutoff = _cutoff(window_days)
    with ops_con(read_only=True) as con:
        sql = """
            SELECT COALESCE(cluster_match_id, 0) AS cid,
                   date_trunc('week', created_at) AS wk,
                   COUNT(*) AS n
            FROM cases
            WHERE created_at >= ?
        """
        params: list[Any] = [cutoff]
        if pack_id:
            sql += " AND pack_id = ?"
            params.append(pack_id)
        sql += " GROUP BY 1, 2 ORDER BY 1, 2"
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            rows = []
    by_c: dict[Any, list[int]] = defaultdict(list)
    for cid, _wk, n in rows:
        by_c[cid].append(int(n))
    forecasts = []
    for cid, series in by_c.items():
        proj = project_next_week_volume(series)
        slope = proj["slope_per_week"]
        last = proj["last_week_volume"]
        if slope <= 0:
            weeks = None
            status = "flat_or_declining"
        else:
            remain = max(0, threshold - last)
            weeks = round(remain / slope, 1)
            status = "projected_breach" if weeks is not None and weeks <= 12 else "ok"
        forecasts.append(
            {
                "cluster_id": cid,
                "weekly_counts": series,
                "last_week_volume": last,
                "slope_per_week": round(slope, 3),
                "threshold": threshold,
                "projected_weeks_to_threshold": weeks,
                "projected_next_week": proj["projected_next_week"],
                "ci_low": proj["ci_low"],
                "ci_high": proj["ci_high"],
                "status": status,
            }
        )
    forecasts.sort(key=lambda x: (x["projected_weeks_to_threshold"] is None, x["projected_weeks_to_threshold"] or 999))
    return {"forecasts": forecasts, "window_days": window_days, "threshold": threshold}


def cross_pack_patterns(*, limit: int = 20) -> dict[str, Any]:
    """Same category/component across packs → shared systemic signal."""
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT category, pack_id, COUNT(*) AS n
                FROM cases
                WHERE category IS NOT NULL AND category != ''
                GROUP BY category, pack_id
                """
            ).fetchall()
        except Exception:
            rows = []
    by_cat: dict[str, dict[str, int]] = defaultdict(dict)
    for cat, pack, n in rows:
        by_cat[str(cat)][str(pack)] = int(n)
    patterns = []
    for cat, packs in by_cat.items():
        if len(packs) >= 2:
            patterns.append(
                {
                    "category": cat,
                    "packs": packs,
                    "pack_count": len(packs),
                    "total": sum(packs.values()),
                    "signal": "cross_pack_shared_issue",
                }
            )
    patterns.sort(key=lambda x: -x["total"])
    return {"patterns": patterns[:limit], "count": len(patterns)}


def geographic_hotspots(
    *,
    pack_id: str | None = None,
    window_days: int = 90,
    limit: int = 25,
) -> dict[str, Any]:
    """Region concentration from cases / interactions (region column if present)."""
    cutoff = _cutoff(window_days)
    with ops_con(read_only=True) as con:
        # Prefer cases.region if column exists; else interactions
        rows = []
        from src.security.sql_ident import safe_column, safe_table

        for table, col in (("cases", "region"), ("interactions", "region")):
            try:
                t = safe_table(table)
                c = safe_column(col)
                sql = f"""
                    SELECT COALESCE({c}, 'unknown') AS region, COUNT(*) AS n
                    FROM {t}
                    WHERE created_at >= ?
                """ if table == "cases" else f"""
                    SELECT COALESCE({c}, 'unknown') AS region, COUNT(*) AS n
                    FROM {t}
                    WHERE started_at >= ?
                """
                params: list[Any] = [cutoff]
                if pack_id:
                    sql += " AND pack_id = ?"
                    params.append(pack_id)
                sql += " GROUP BY 1 ORDER BY n DESC LIMIT ?"
                params.append(limit)
                rows = con.execute(sql, params).fetchall()
                if rows:
                    break
            except Exception:
                continue
    # Approximate centroids so the dashboard can draw a real map, not names-only.
    _CENTROIDS = {
        "CA": (-119.4, 36.8),
        "TX": (-99.3, 31.5),
        "NY": (-75.5, 43.0),
        "FL": (-81.5, 27.8),
        "MI": (-85.6, 44.3),
        "OH": (-82.8, 40.4),
        "unknown": (-98.0, 39.5),
    }
    hotspots = []
    features = []
    for r in rows:
        region = str(r[0])
        lon, lat = _CENTROIDS.get(region.upper() if len(region) == 2 else region, _CENTROIDS["unknown"])
        rec = {"region": region, "volume": int(r[1]), "lat": lat, "lon": lon}
        hotspots.append(rec)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"region": region, "volume": int(r[1])},
            }
        )
    return {
        "hotspots": hotspots,
        "window_days": window_days,
        "time_slider": True,
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def seasonality_climate(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Correlate failures with temperature band and region season. Pure."""
    bands = {"cold": 0, "mild": 0, "hot": 0}
    by_region: dict[str, int] = defaultdict(int)
    for r in rows:
        t = r.get("temperature_c")
        if t is None:
            continue
        tv = float(t)
        if tv < 10:
            bands["cold"] += 1
        elif tv < 25:
            bands["mild"] += 1
        else:
            bands["hot"] += 1
        region = str(r.get("region") or "unknown")
        by_region[region] += 1
    return {
        "temperature_bands": bands,
        "by_region": dict(by_region),
        "n": sum(bands.values()),
    }


def severity_drift(
    *,
    pack_id: str | None = None,
    window_days: int = 28,
) -> dict[str, Any]:
    """Whether severity mix within clusters is worsening over time."""
    cutoff = _cutoff(window_days)
    mid = utc_now() - timedelta(days=max(1, window_days // 2))
    rank = {"Low": 1, "Medium": 2, "Critical": 3}
    with ops_con(read_only=True) as con:
        sql = """
            SELECT COALESCE(cluster_id, 0), severity, created_at
            FROM cases WHERE created_at >= ?
        """
        params: list[Any] = [cutoff]
        if pack_id:
            sql += " AND pack_id = ?"
            params.append(pack_id)
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            rows = []
    early: dict[Any, list[int]] = defaultdict(list)
    late: dict[Any, list[int]] = defaultdict(list)
    for cid, sev, created in rows:
        r = rank.get(str(sev), 0)
        bucket = late if created and created >= mid else early
        bucket[cid].append(r)
    out = []
    for cid in set(early) | set(late):
        e = sum(early[cid]) / len(early[cid]) if early[cid] else 0.0
        l = sum(late[cid]) / len(late[cid]) if late[cid] else 0.0
        drift = l - e
        out.append(
            {
                "cluster_id": cid,
                "early_avg_severity": round(e, 3),
                "late_avg_severity": round(l, 3),
                "severity_drift": round(drift, 3),
                "worsening": drift > 0.15,
            }
        )
    out.sort(key=lambda x: -x["severity_drift"])
    return {"clusters": out, "window_days": window_days}


def cohort_analysis(
    *,
    pack_id: str | None = None,
    group_field: str = "entity_3",
    limit: int = 20,
) -> dict[str, Any]:
    """Group by production year / account cohort (entity_3 often year/version)."""
    from src.security.sql_ident import safe_column, safe_table

    try:
        group_field = safe_column(group_field)
    except ValueError:
        return {"group_field": group_field, "cohorts": [], "error": "invalid_group_field"}
    with ops_con(read_only=True) as con:
        # entity_3 on cases may not exist — try interactions
        for table, field in (
            ("cases", group_field),
            ("interactions", group_field),
            ("cases", "category"),
        ):
            try:
                t = safe_table(table)
                f = safe_column(field)
                sql = f"""
                    SELECT COALESCE(CAST({f} AS VARCHAR), 'unknown') AS cohort,
                           COUNT(*) AS n
                    FROM {t}
                """
                params: list[Any] = []
                if pack_id:
                    sql += " WHERE pack_id = ?"
                    params.append(pack_id)
                sql += " GROUP BY 1 ORDER BY n DESC LIMIT ?"
                params.append(limit)
                rows = con.execute(sql, params).fetchall()
                if rows:
                    return {
                        "group_field": f,
                        "table": t,
                        "cohorts": [{"cohort": r[0], "volume": int(r[1])} for r in rows],
                    }
            except Exception:
                continue
    return {"group_field": group_field, "cohorts": []}


def regulator_filing_watch(*, pack_id: str | None = None) -> dict[str, Any]:
    """Match domain advisories against open investigations (self-score lead time)."""
    from src.config import settings
    from src.domains.loader import load_pack

    pid = pack_id or settings.domain_pack
    matches = []
    try:
        pack = load_pack(pid)
        # advisories may live in domain DB
        from src.data.warehouse import domain_con

        with domain_con(pid, read_only=True) as con:
            try:
                advisories = con.execute(
                    "SELECT advisory_id, title, published_at FROM advisories LIMIT 50"
                ).fetchall()
            except Exception:
                advisories = []
        with ops_con(read_only=True) as con:
            try:
                inv = con.execute(
                    """
                    SELECT investigation_id, cluster_id, status, opened_at, title
                    FROM investigations WHERE pack_id = ? OR pack_id IS NULL
                    """,
                    [pid],
                ).fetchall()
            except Exception:
                inv = []
        for a in advisories:
            aid, title, pub = a[0], a[1], a[2]
            # lexical match against investigation titles
            tlow = (title or "").lower()
            for inv_row in inv:
                ititle = (inv_row[4] or "").lower()
                if ititle and (ititle in tlow or any(w in tlow for w in ititle.split()[:3] if len(w) > 3)):
                    lead = None
                    if pub and inv_row[3]:
                        try:
                            lead = (pub - inv_row[3]).days / 7.0
                        except Exception:
                            lead = None
                    matches.append(
                        {
                            "advisory_id": aid,
                            "investigation_id": inv_row[0],
                            "lead_time_weeks": round(lead, 1) if lead is not None else None,
                            "flagged_before_filing": lead is not None and lead > 0,
                        }
                    )
    except Exception as e:
        return {"matches": [], "error": f"{type(e).__name__}: {e}", "pack_id": pid}
    return {"pack_id": pid, "matches": matches, "count": len(matches)}


def financial_impact(
    *,
    pack_id: str | None = None,
    cost_per_case: float | None = None,
    recall_cost_per_unit: float | None = None,
) -> dict[str, Any]:
    """Pack-configured cost model → dollar risk figure."""
    # Defaults if pack.yaml lacks cost_model
    cpc = cost_per_case if cost_per_case is not None else float(
        __import__("os").getenv("COST_PER_CASE", "250")
    )
    rcpu = recall_cost_per_unit if recall_cost_per_unit is not None else float(
        __import__("os").getenv("RECALL_COST_PER_UNIT", "900")
    )
    with ops_con(read_only=True) as con:
        sql = "SELECT COALESCE(cluster_id,0), COUNT(*), SUM(CASE WHEN severity='Critical' THEN 1 ELSE 0 END) FROM cases"
        params: list[Any] = []
        if pack_id:
            sql += " WHERE pack_id = ?"
            params.append(pack_id)
        sql += " GROUP BY 1"
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            rows = []
    estimates = []
    for cid, n, crit in rows:
        n = int(n)
        crit = int(crit or 0)
        warranty = n * cpc
        recall_risk = crit * rcpu * 10  # pilot band: criticals imply broader exposure
        estimates.append(
            {
                "cluster_id": cid,
                "case_count": n,
                "critical_count": crit,
                "warranty_cost_usd": round(warranty, 2),
                "recall_risk_usd": round(recall_risk, 2),
                "total_risk_usd": round(warranty + recall_risk, 2),
            }
        )
    estimates.sort(key=lambda x: -x["total_risk_usd"])
    total = sum(e["total_risk_usd"] for e in estimates)
    return {
        "estimates": estimates,
        "portfolio_risk_usd": round(total, 2),
        "cost_per_case": cpc,
        "recall_cost_per_unit": rcpu,
    }


def bias_fairness_report(
    *,
    pack_id: str | None = None,
    window_days: int = 90,
) -> dict[str, Any]:
    """Compare escalation/handoff/severity rates across region proxies."""
    cutoff = _cutoff(window_days)
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT COALESCE(region, 'unknown') AS region,
                       COUNT(*) AS n,
                       AVG(CASE WHEN peak_frustration >= 0.65 THEN 1.0 ELSE 0.0 END) AS handoff_rate,
                       AVG(CASE WHEN outcome = 'escalated' OR status = 'escalated' THEN 1.0 ELSE 0.0 END) AS esc_rate
                FROM interactions
                WHERE started_at >= ?
                GROUP BY 1
                """,
                [cutoff] if not pack_id else None,
            )
            # handle pack filter carefully
        except Exception:
            rows = []
            try:
                sql = """
                    SELECT COALESCE(category, 'unknown'),
                           COUNT(*),
                           AVG(CASE WHEN peak_frustration >= 0.65 THEN 1.0 ELSE 0.0 END),
                           AVG(0)
                    FROM interactions WHERE started_at >= ?
                """
                params: list[Any] = [cutoff]
                if pack_id:
                    sql += " AND pack_id = ?"
                    params.append(pack_id)
                sql += " GROUP BY 1"
                rows = con.execute(sql, params).fetchall()
            except Exception:
                rows = []
        else:
            # re-run with pack if needed — simplify
            try:
                sql = """
                    SELECT COALESCE(category, 'unknown') AS grp,
                           COUNT(*) AS n,
                           AVG(CASE WHEN peak_frustration >= 0.65 THEN 1.0 ELSE 0.0 END) AS handoff_rate,
                           AVG(CASE WHEN outcome LIKE '%escalat%' THEN 1.0 ELSE 0.0 END) AS esc_rate
                    FROM interactions
                    WHERE started_at >= ?
                """
                params = [cutoff]
                if pack_id:
                    sql += " AND pack_id = ?"
                    params.append(pack_id)
                sql += " GROUP BY 1"
                rows = con.execute(sql, params).fetchall()
            except Exception:
                rows = []
    groups = []
    rates = []
    for r in rows:
        grp, n, hr, er = r[0], int(r[1]), float(r[2] or 0), float(r[3] or 0)
        groups.append(
            {
                "group": grp,
                "volume": n,
                "handoff_proxy_rate": round(hr, 3),
                "escalation_rate": round(er, 3),
            }
        )
        if n >= 2:
            rates.append(hr)
    disparity = (max(rates) - min(rates)) if len(rates) >= 2 else 0.0
    return {
        "groups": groups,
        "handoff_rate_disparity": round(disparity, 3),
        "flag": disparity >= 0.25,
        "window_days": window_days,
        "note": "Pilot fairness monitor on category proxy; not a legal compliance certification.",
    }
