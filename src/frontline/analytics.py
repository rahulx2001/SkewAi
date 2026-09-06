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


#: Minimum weekly observations for a forecast (item 33/42). Fewer points
#: cannot support a slope estimate — callers get "insufficient_history".
MIN_FORECAST_WEEKS = 4


def _t_crit_95(df: int) -> float:
    """Two-sided 95% t critical value (item 33).

    Exact table for df 1..30, Normal approximation beyond. Documented
    approximation — adequate for pilot confidence bands, not metrology.
    """
    table = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
        13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
        19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
        25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
    }
    if df <= 0:
        return float("nan")
    if df in table:
        return table[df]
    # Normal approximation plus 1/(4n) correction; 1.96 is slightly anti-conservative.
    return 1.96 + 1.0 / (4.0 * float(df))


def project_next_week_volume(series: list[int]) -> dict[str, Any]:
    """OLS next-week projection with t-based confidence interval (item 33).

    Slope comes from ordinary least squares over the whole series (not the
    last-delta, which amplified single-week noise). Residual standard error
    and the 95% interval use the t distribution with n-2 degrees of freedom.
    Series shorter than MIN_FORECAST_WEEKS return ``insufficient_history``
    with no projection — a slope from 2-3 points is not evidence.

    Volume cannot go below 0. The interval is ordered: 0 <= ci_low <= ci_high.
    """
    counts = [int(v) for v in series]
    n = len(counts)
    last = counts[-1] if counts else 0
    if n < MIN_FORECAST_WEEKS:
        return {
            "weekly_counts": counts,
            "last_week_volume": last,
            "slope_per_week": 0.0,
            "slope_se": None,
            "t_crit_95": None,
            "residual_stdev": 0.0,
            "projected_next_week": None,
            "ci_low": None,
            "ci_high": None,
            "method": "insufficient_history",
            "n": n,
        }
    xs = list(range(n))
    xbar = sum(xs) / n
    ybar = sum(counts) / n
    sxx = sum((x - xbar) ** 2 for x in xs)
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, counts)) / sxx if sxx else 0.0
    intercept = ybar - slope * xbar
    fitted = [intercept + slope * x for x in xs]
    sse = sum((a - b) ** 2 for a, b in zip(counts, fitted))
    df = n - 2
    resid = (sse / df) ** 0.5 if df > 0 else 0.0
    slope_se = (resid / (sxx ** 0.5)) if sxx > 0 else 0.0
    tcrit = _t_crit_95(df)
    # Prediction interval for the next point (x = n): accounts for both slope
    # uncertainty and residual noise.
    pred_se = resid * (1 + 1 / n + (n - xbar) ** 2 / sxx) ** 0.5 if sxx > 0 else resid
    next_point = max(0.0, fitted[-1] + slope)
    half = tcrit * pred_se
    ci_low = max(0.0, next_point - half)
    ci_high = max(ci_low, next_point + half)
    return {
        "weekly_counts": counts,
        "last_week_volume": last,
        "slope_per_week": slope,
        "slope_se": slope_se,
        "t_crit_95": tcrit,
        "residual_stdev": resid,
        "projected_next_week": next_point,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "method": "ols",
        "n": n,
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
              AND COALESCE(case_kind, 'customer') = 'customer'
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
        if proj.get("method") == "insufficient_history":
            # N < 4: no slope estimate, no projection (item 33).
            weeks, status = None, "insufficient_history"
        elif last >= threshold:
            # Breach-first: an already-breached threshold is never "flat".
            weeks, status = 0.0, "breached"
        elif slope <= 0:
            weeks, status = None, "flat_or_declining"
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
                "slope_se": proj.get("slope_se"),
                "threshold": threshold,
                "projected_weeks_to_threshold": weeks,
                "projected_next_week": proj["projected_next_week"],
                "ci_low": proj["ci_low"],
                "ci_high": proj["ci_high"],
                "forecast_method": proj.get("method"),
                "status": status,
            }
        )
    forecasts.sort(key=lambda x: (x["projected_weeks_to_threshold"] is None, x["projected_weeks_to_threshold"] or 999))
    return {"forecasts": forecasts, "window_days": window_days, "threshold": threshold}


def cross_pack_patterns(*, limit: int = 20) -> dict[str, Any]:
    """Shared systemic signal across packs via the concept ontology (item 34).

    Raw categories are mapped to cross-pack concepts (see
    src/domains/concepts.py) — NHTSA "AIR BAGS" and CFPB "Fraud or scam" are
    both ``safety_security`` incidents, while genuinely unrelated categories
    (ENGINE vs Incorrect charges) never merge. A pattern requires the SAME
    shared concept in >= 2 packs; pack-scoped concepts are reported
    separately for transparency, never as cross-pack signal.
    """
    from src.domains.concepts import concept_for, is_cross_pack_concept

    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                """
                SELECT category, pack_id, COUNT(*) AS n
                FROM cases
                WHERE category IS NOT NULL AND category != ''
                  AND COALESCE(case_kind, 'customer') = 'customer'
                GROUP BY category, pack_id
                """
            ).fetchall()
        except Exception:
            rows = []
    try:
        from src.config import settings
        from src.domains.loader import load_pack

        _tax: dict[str, Any] = {}
        for _pid in {str(p) for _, p, _ in rows}:
            try:
                _tax[_pid] = load_pack(_pid).taxonomy or {}
            except Exception:
                _tax[_pid] = {}
    except Exception:
        _tax = {}
    by_concept: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for cat, pack, n in rows:
        concept = concept_for(str(pack), str(cat), _tax.get(str(pack)))
        by_concept[concept][str(pack)][str(cat)] = int(n)
    patterns = []
    pack_specific = []
    for concept, packs in by_concept.items():
        entry = {
            "concept": concept,
            "packs": {p: sum(cats.values()) for p, cats in packs.items()},
            "categories": {p: cats for p, cats in packs.items()},
            "pack_count": len(packs),
            "total": sum(sum(cats.values()) for cats in packs.values()),
        }
        if is_cross_pack_concept(concept) and len(packs) >= 2:
            entry["signal"] = "cross_pack_shared_issue"
            patterns.append(entry)
        else:
            entry["signal"] = "pack_specific"
            pack_specific.append(entry)
    patterns.sort(key=lambda x: -x["total"])
    return {
        "patterns": patterns[:limit],
        "count": len(patterns),
        "pack_specific": pack_specific[:limit],
    }


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
    # Centroids are evidence-backed map pins (item 33): the pack's
    # region_centroids win; anything else is explicitly labeled an
    # approximate demo coordinate — never presented as measured truth.
    _FALLBACK_CENTROIDS = {
        "CA": (-119.4, 36.8),
        "TX": (-99.3, 31.5),
        "NY": (-75.5, 43.0),
        "FL": (-81.5, 27.8),
        "MI": (-85.6, 44.3),
        "OH": (-82.8, 40.4),
        "unknown": (-98.0, 39.5),
    }
    _pack_centroids: dict[str, list[float]] = {}
    try:
        from src.config import settings
        from src.domains.loader import load_pack

        _pack_centroids = dict(
            load_pack(pack_id or settings.domain_pack).manifest.region_centroids or {}
        )
    except Exception:
        pass
    hotspots = []
    features = []
    for r in rows:
        region = str(r[0])
        key = region.upper() if len(region) == 2 else region
        pin = _pack_centroids.get(key) or _pack_centroids.get(region)
        if pin and len(pin) == 2:
            lon, lat = float(pin[0]), float(pin[1])
            source = "pack.yaml region_centroids"
        else:
            lon, lat = _FALLBACK_CENTROIDS.get(key, _FALLBACK_CENTROIDS["unknown"])
            source = "approximate-demo-coordinate"
        rec = {"region": region, "volume": int(r[1]), "lat": lat, "lon": lon,
               "coordinate_source": source}
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
    """Correlate failures with temperature band and region season. Pure.

    .. deprecated::
        The ``temperature_c`` input is dead — no producer writes it — and
        this helper will be removed once dashboard consumers migrate to the
        weekly-anomaly series. It still runs for backward compatibility but
        reports ``deprecated: True`` so callers stop depending on it.
    """
    import warnings

    warnings.warn(
        "seasonality_climate(temperature_c) is deprecated: no producer writes "
        "temperature_c; use weekly anomaly series instead",
        DeprecationWarning,
        stacklevel=2,
    )
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
        "deprecated": True,
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
            SELECT COALESCE(cluster_match_id, 0), severity, created_at
            FROM cases WHERE created_at >= ?
              AND COALESCE(case_kind, 'customer') = 'customer'
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
    """Pack-configured cost model → dollar risk figure (item 33).

    Figures come from the pack's ``cost_model`` (pack.yaml) — never env-var
    guessing. Explicit overrides still win for what-if analysis. The recall
    exposure term uses the pack's named ``exposure_multiplier`` assumption
    (replacing the old arbitrary ``*10``).
    """
    cpc = cost_per_case
    rcpu = recall_cost_per_unit
    exposure = 1.0
    currency = "USD"
    cost_source = "pack.yaml cost_model"
    explicit = cost_per_case is not None or recall_cost_per_unit is not None
    # Cost uncertainty band for COPQ ranges (audit 8.4): pack-owned when
    # declared, else an explicit ±25% default — labeled, never hidden.
    uncertainty = 0.25
    pack_loaded = False
    if cpc is None or rcpu is None:
        try:
            from src.config import settings
            from src.domains.loader import load_pack

            pack = load_pack(pack_id or settings.domain_pack)
            cm = pack.manifest.cost_model
            if cpc is None:
                cpc = float(cm.cost_per_case)
            if rcpu is None:
                rcpu = float(cm.recall_cost_per_unit)
            exposure = float(cm.exposure_multiplier)
            currency = str(cm.currency or currency)
            pack_loaded = True
        except Exception:
            pack_loaded = False
    if cpc is None:
        cpc = 250.0
    if rcpu is None:
        rcpu = 900.0
    if explicit:
        cost_source = "explicit_override"
    elif not pack_loaded:
        cost_source = "default_fallback"
    with ops_con(read_only=True) as con:
        sql = "SELECT COALESCE(cluster_match_id,0), COUNT(*), SUM(CASE WHEN severity='Critical' THEN 1 ELSE 0 END) FROM cases WHERE COALESCE(case_kind, 'customer') = 'customer'"
        params: list[Any] = []
        if pack_id:
            sql += " AND pack_id = ?"
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
        # Exposure-banded recall risk: criticals imply broader exposure, scaled
        # by the pack-owned exposure_multiplier (a named assumption, not magic).
        recall_risk = crit * rcpu * exposure
        # COPQ as a RANGE (audit 8.4): point estimates pretend a precision the
        # cost model does not have. Band defaults to ±25% cost uncertainty.
        lo, hi = 1.0 - uncertainty, 1.0 + uncertainty
        total_risk = warranty + recall_risk
        estimates.append(
            {
                "cluster_id": cid,
                "case_count": n,
                "critical_count": crit,
                "warranty_cost_usd": round(warranty, 2),
                "recall_risk_usd": round(recall_risk, 2),
                "total_risk_usd": round(total_risk, 2),
                "total_risk_range_usd": [round(total_risk * lo, 2), round(total_risk * hi, 2)],
            }
        )
    estimates.sort(key=lambda x: -x["total_risk_usd"])
    total = sum(e["total_risk_usd"] for e in estimates)
    return {
        "estimates": estimates,
        "portfolio_risk_usd": round(total, 2),
        "portfolio_risk_range_usd": [round(total * (1.0 - uncertainty), 2), round(total * (1.0 + uncertainty), 2)],
        "cost_per_case": cpc,
        "recall_cost_per_unit": rcpu,
        "exposure_multiplier": exposure,
        "cost_uncertainty": uncertainty,
        "currency": currency,
        "cost_source": cost_source,
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
            sql = """
                SELECT COALESCE(channel, 'unknown') AS grp,
                       COUNT(*) AS n,
                       AVG(CASE WHEN COALESCE(last_frustration, peak_frustration, 0) >= 0.65
                            THEN 1.0 ELSE 0.0 END) AS handoff_rate,
                       AVG(CASE WHEN outcome LIKE '%escalat%' OR status = 'escalated' THEN 1.0 ELSE 0.0 END) AS esc_rate
                FROM interactions
                WHERE started_at >= ?
            """
            params: list[Any] = [cutoff]
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
        "note": "Pilot fairness monitor on channel proxy (last_frustration); not a legal compliance certification.",
    }


def evaluate_fairness_circuit_breaker(
    *,
    pack_id: str | None = None,
    window_days: int = 90,
    disparate_impact_floor: float = 0.80,
) -> dict[str, Any]:
    """Runtime bias/fairness circuit breaker (audit 5.3).

    Calculates the four-fifths (80%) disparate impact ratio across proxy groups.
    If the ratio drops below disparate_impact_floor (0.80), flags circuit_breaker_tripped=True
    and signals supervisor_required=True to halt unmonitored automated decisions.
    """
    report = bias_fairness_report(pack_id=pack_id, window_days=window_days)
    groups = report.get("groups") or []
    valid_groups = [g for g in groups if g.get("volume", 0) >= 2]
    if len(valid_groups) < 2:
        return {
            "circuit_breaker_tripped": False,
            "disparate_impact_ratio": 1.0,
            "supervisor_required": False,
            "reason": "insufficient group volume for disparate impact evaluation",
            "groups_evaluated": len(valid_groups),
        }

    # Compare non-escalation / automated resolution rate: (1.0 - escalation_rate)
    success_rates = [max(0.01, 1.0 - g.get("escalation_rate", 0.0)) for g in valid_groups]
    max_rate = max(success_rates)
    min_rate = min(success_rates)
    ratio = round(min_rate / max_rate, 3) if max_rate > 0 else 1.0

    tripped = ratio < disparate_impact_floor
    return {
        "circuit_breaker_tripped": tripped,
        "disparate_impact_ratio": ratio,
        "disparate_impact_floor": disparate_impact_floor,
        "supervisor_required": tripped,
        "reason": f"disparate impact ratio {ratio:.3f} < floor {disparate_impact_floor:.2f}" if tripped else "within fairness tolerance",
        "groups_evaluated": len(valid_groups),
    }
