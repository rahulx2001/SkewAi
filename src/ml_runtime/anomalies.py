"""Weekly volume anomalies computed from ``records`` (not seed literals).

Method (item 10) — quasi-Poisson standardized residuals on zero-filled
weekly buckets, with Benjamini-Hochberg FDR control:

- Event clock: ``occurred_at`` is the event time; ``received_at`` (ingestion
  time) is only a fallback when ``occurred_at`` is missing. Ingestion lag
  must never masquerade as an event spike.
- Zero-fill: every (category, entity_2) series is expanded to the continuous
  Monday-to-Monday week range it spans; missing weeks count 0. Without this,
  quiet weeks vanish and any observed week looks anomalous.
- Leave-one-out baseline: week *w* is scored against the OTHER weeks only,
  so a spike cannot inflate its own baseline.
- Quasi-Poisson z: ``z = (x - mu) / max(sample_std, sqrt(mu))``. Counts are
  not Gaussian: Poisson variance grows with the mean, so dividing a raw
  count difference by an empirical std mixes units (the old ``z = n - mean``
  bug) and tiny-variance baselines (1000,1000,1000) produce bogus huge z.
  ``max(std, sqrt(mu))`` degrades gracefully to the Poisson floor and also
  absorbs overdispersion. z is unitless by construction.
- Zero baseline (mu == 0): Poisson tail is degenerate, so only an absolute
  floor can fire: ``x >= MIN_ZERO_BASELINE_COUNT`` (default 5). Documented
  heuristic, not a p-value.
- Minimum history (item 42): full-power flags require at least
  ``MIN_BASELINE_WEEKS`` (default 4) baseline weeks — i.e. 5 total weekly
  observations. With 2-3 baseline weeks only the absolute+relative heuristic
  guard may fire (``method='low-history-heuristic'``); with <2, never.
- Multiple comparisons: one-sided Normal-approx p-values from z are adjusted
  with Benjamini-Hochberg across ALL scored slices; ``is_anomaly`` requires
  ``z >= 2.0`` AND ``p_bh <= 0.05`` AND the absolute/relative lift gates
  (``x - mu >= 5`` AND ``(x - mu)/mu >= 50%`` when ``mu > 0``). The lift
  gates keep trivial relative moves (1000 -> 1002) unflagged even when a
  degenerate baseline yields z >= 2.

Assumptions: weekly counts are conditionally independent given the baseline;
no seasonality adjustment (holiday dips can false-positive — check
``baseline_weeks`` and the raw series before acting); population is the
observed warehouse slice, not an external denominator.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

from src.data.warehouse import apply_domain_schema, domain_con

ANOMALY_Z = 2.0
FDR_Q = 0.05
MIN_BASELINE_WEEKS = 4
MIN_HISTORY_WEEKS_HEURISTIC = 2
MIN_ABSOLUTE_LIFT = 5
MIN_RELATIVE_LIFT = 0.5
MIN_ZERO_BASELINE_COUNT = 5


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


def _event_time(record: dict[str, Any]) -> datetime | None:
    """Actual event clock: occurred_at first, ingestion (received_at) fallback."""
    for key in ("occurred_at", "received_at"):
        raw = record.get(key)
        if raw is None:
            continue
        if isinstance(raw, datetime):
            return raw.replace(tzinfo=None) if raw.tzinfo else raw
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def count_weekly_slices(records: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str], int]:
    """(iso_week, category, entity_2) → count, on the EVENT clock."""
    out: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in records:
        # occurred_at is the event clock; received_at only a fallback.
        week = iso_week_label(_event_time(r))
        if not week:
            continue
        cat = str(r.get("category") or "")
        ent = str(r.get("entity_2") or "")
        out[(week, cat, ent)] += 1
    return dict(out)


def _week_monday(label: str) -> datetime | None:
    try:
        y, w = label.split("-W")
        return datetime.fromisocalendar(int(y), int(w), 1)
    except (ValueError, TypeError):
        return None


def zero_fill_weeks(
    counts: dict[tuple[str, str, str], int],
) -> dict[tuple[str, str, str], int]:
    """Expand every (category, entity_2) series to its continuous week range.

    Missing weeks in between count 0 — a silent week is evidence of quiet,
    not a gap in the data.
    """
    by_group: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (week, cat, ent) in counts:
        by_group[(cat, ent)].add(week)
    filled = dict(counts)
    for (cat, ent), weeks in by_group.items():
        starts = sorted(
            (m for w in weeks if (m := _week_monday(w)) is not None)
        )
        if len(starts) < 2:
            continue
        cur, end = starts[0], starts[-1]
        while cur <= end:
            y, w, _ = cur.isocalendar()
            label = f"{y}-W{w:02d}"
            filled.setdefault((label, cat, ent), 0)
            cur += timedelta(weeks=1)
    return filled


def _upper_tail_p(z: float) -> float:
    """One-sided Normal-approx upper-tail p-value for z (spike test)."""
    if z <= 0:
        return 1.0
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _bh_adjust(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (same order as input)."""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    adj = [0.0] * m
    running_min = 1.0
    for rank_rev, idx in enumerate(reversed(order)):
        rank = m - rank_rev  # 1-based rank of this p in ascending order
        val = p_values[idx] * m / rank
        running_min = min(running_min, val)
        adj[idx] = min(1.0, running_min)
    return adj


def set_exposure(
    pack_id: str,
    iso_week: str,
    category: str | None,
    entity_2: str | None,
    exposure_units: float,
    *,
    unit: str = "units",
) -> dict[str, Any]:
    """Record exposure (vehicles-in-operation / active accounts / shipped).

    Audit 8.1: rates beat raw counts. Slice-weeks with exposure score on
    rate (count per 1000 units, Poisson offset semantics); slices without
    exposure score on raw counts and are labeled ``normalized=False``
    (boards must render those as 'unnormalised').
    """
    if exposure_units is None or float(exposure_units) <= 0:
        raise ValueError("exposure_units must be positive")
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        con.execute(
            """
            INSERT OR REPLACE INTO exposure
            (pack_id, iso_week, category, entity_2, exposure_units, unit)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [pack_id, iso_week, category, entity_2, float(exposure_units), unit],
        )
    return {
        "pack_id": pack_id, "iso_week": iso_week, "category": category,
        "entity_2": entity_2, "exposure_units": float(exposure_units), "unit": unit,
    }


def load_exposure(
    pack_id: str,
    *,
    category: str | None = None,
    entity_2: str | None = None,
) -> dict[tuple[str, str, str], float]:
    """(iso_week, category, entity_2) → exposure units. Empty when unrecorded."""
    with domain_con(pack_id) as con:
        try:
            sql = "SELECT iso_week, category, entity_2, exposure_units FROM exposure WHERE pack_id = ?"
            params: list[Any] = [pack_id]
            if category:
                sql += " AND category = ?"
                params.append(category)
            if entity_2:
                sql += " AND entity_2 = ?"
                params.append(entity_2)
            rows = con.execute(sql, params).fetchall()
        except Exception:
            return {}
    return {
        (str(w), str(c or ""), str(e or "")): float(u)
        for w, c, e, u in rows if u and float(u) > 0
    }


def detect_cusum_change_point(
    series: list[float],
    *,
    baseline_mean: float,
    baseline_std: float,
    k: float = 0.5,
    h: float = 4.0,
) -> dict[str, Any]:
    """Page's upper Cumulative Sum (CUSUM) for detecting sustained upward shifts.

    Distinguishes sustained process step-changes from 1-week transient spikes (audit 4.3).
    - k: reference value (slack parameter, in units of std; default 0.5)
    - h: decision boundary threshold (default 4.0 std devs)
    """
    if not series:
        return {"cusum_values": [], "triggered": False, "change_point_index": None}
    sigma = max(baseline_std, math.sqrt(baseline_mean) if baseline_mean > 0 else 1.0)
    k_val = k * sigma
    h_val = h * sigma
    s_pos = 0.0
    cusum_vals = []
    change_idx = None
    for idx, val in enumerate(series):
        s_pos = max(0.0, s_pos + (val - baseline_mean - k_val))
        cusum_vals.append(s_pos)
        if change_idx is None and s_pos >= h_val:
            change_idx = idx
    return {
        "cusum_values": cusum_vals,
        "triggered": change_idx is not None,
        "change_point_index": change_idx,
    }


def score_weekly_slices(
    counts: dict[tuple[str, str, str], int],
    *,
    pack_id: str,
    in_flight: dict[str, Any] | None = None,
    exposure: dict[tuple[str, str, str], float] | None = None,
) -> list[dict[str, Any]]:
    """Attach z_score / p_value / is_anomaly. Pure; no I/O.

    Zero-fills each series, scores leave-one-out quasi-Poisson residuals,
    and applies BH-FDR across all candidate slices.

    ``in_flight`` (item 36) folds ONE in-flight contact into the CURRENT
    week bucket before scoring — ``{"iso_week", "category", "entity_2"}`` —
    so a live voice/text contact can tip the threshold in the same call.
    The +1 is labeled (``in_flight_included``) and never persisted by the
    scorer; persistence paths must pass ``in_flight=None``.

    ``exposure`` (audit 8.1) maps (week, category, entity_2) → exposure
    units. A slice scores on RATE (per 1000 units) only when its own week
    and every baseline week have exposure; otherwise it falls back to raw
    counts with ``normalized=False`` so boards label it 'unnormalised'
    instead of presenting volume-driven flags as rate anomalies.
    """
    if in_flight:
        try:
            from src.data.timeutil import utc_now as _now

            week = in_flight.get("iso_week") or iso_week_label(_now())
            key = (str(week), str(in_flight.get("category") or ""),
                   str(in_flight.get("entity_2") or ""))
            counts = dict(counts)
            counts[key] = counts.get(key, 0) + 1
        except Exception:
            pass
    filled = zero_fill_weeks(counts)
    by_group: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for (week, cat, ent), n in filled.items():
        by_group[(cat, ent)].append((week, n))

    # First pass: per-slice statistics (leave-one-out baseline).
    prelim: list[dict[str, Any]] = []
    exp = exposure or {}
    cusum_map: dict[tuple[str, str], dict[str, Any]] = {}

    for (cat, ent), weeks in sorted(by_group.items()):
        sorted_weeks = sorted(weeks)
        # Precompute CUSUM on chronological series for this slice
        s_vals = [float(n) for _, n in sorted_weeks]
        s_mu = sum(s_vals) / len(s_vals) if s_vals else 0.0
        s_var = sum((v - s_mu) ** 2 for v in s_vals) / max(1, len(s_vals) - 1)
        cusum_map[(cat, ent)] = detect_cusum_change_point(
            s_vals, baseline_mean=s_mu, baseline_std=math.sqrt(s_var)
        )

        for w_idx, (week, n) in enumerate(sorted_weeks):
            others = [(w, c) for w, c in weeks if w != week]
            # Rate path (audit 8.1): per-1000-unit rates when exposure covers
            # this week AND every baseline week; else raw counts.
            exp_here = exp.get((week, cat, ent))
            exp_others = [exp.get((w, cat, ent)) for w, _ in others]
            normalized = bool(
                exp_here and exp_others and all(e and e > 0 for e in exp_others)
            )
            if normalized:
                assert exp_here is not None
                n_v = float(n) / float(exp_here) * 1000.0
                base_v = [
                    float(c) / float(e) * 1000.0
                    for (_, c), e in zip(others, exp_others)
                    if e
                ]
            else:
                n_v = float(n)
                base_v = [float(c) for _, c in others]
            mu = sum(base_v) / len(base_v) if base_v else 0.0
            if len(base_v) >= 2:
                var = sum((v - mu) ** 2 for v in base_v) / (len(base_v) - 1)
                std = math.sqrt(var)
            else:
                std = 0.0
            lift_abs = float(n_v - mu)
            lift_rel = (lift_abs / mu) if mu > 0 else (float("inf") if lift_abs > 0 else 0.0)
            hist_n = len(base_v)
            if mu <= 0:
                # Zero baseline: Poisson tail is degenerate. Absolute floor
                # only (documented heuristic).
                if n_v >= MIN_ZERO_BASELINE_COUNT and hist_n >= MIN_HISTORY_WEEKS_HEURISTIC:
                    z, method = ANOMALY_Z, "zero-baseline"
                else:
                    z, method = 0.0, "insufficient-history"
            else:
                denom = max(std, math.sqrt(mu))  # quasi-Poisson floor
                z = lift_abs / denom if denom > 0 else 0.0
                if hist_n >= MIN_BASELINE_WEEKS:
                    method = "quasi-poisson"
                elif hist_n >= MIN_HISTORY_WEEKS_HEURISTIC:
                    method = "low-history-heuristic"
                else:
                    method = "insufficient-history"
            prelim.append(
                {
                    "pack_id": pack_id,
                    "iso_week": week,
                    "category": cat,
                    "entity_2": ent,
                    "record_count": n,
                    "baseline_mean": mu,
                    "baseline_std": std,
                    "baseline_weeks": hist_n,
                    "z_score": z,
                    "p_value": _upper_tail_p(z) if mu > 0 else (0.0 if z >= ANOMALY_Z else 1.0),
                    "absolute_lift": lift_abs,
                    "relative_lift": lift_rel if lift_rel != float("inf") else None,
                    "method": method,
                    "normalized": normalized,
                    "exposure_units": exp.get((week, cat, ent)),
                    "w_idx": w_idx,
                }
            )

    # Second pass: BH-FDR across all candidate slices (multiple comparisons).
    candidates = [i for i, r in enumerate(prelim) if r["method"] != "insufficient-history"]
    adj = _bh_adjust([prelim[i]["p_value"] for i in candidates])
    p_bh_map = {idx: a for idx, a in zip(candidates, adj)}

    rows: list[dict[str, Any]] = []
    for i, r in enumerate(prelim):
        p_bh = p_bh_map.get(i, 1.0)
        r["p_bh"] = p_bh
        if r.get("normalized"):
            # Rate units: absolute-count gates don't apply; relative lift
            # (unitless) + z + FDR carry the decision.
            gates = (
                r["method"] != "insufficient-history"
                and r["z_score"] >= ANOMALY_Z
                and p_bh <= FDR_Q
                and (r["relative_lift"] or 0.0) >= MIN_RELATIVE_LIFT
            )
        else:
            gates = (
                r["method"] != "insufficient-history"
                and r["z_score"] >= ANOMALY_Z
                and p_bh <= FDR_Q
                and r["absolute_lift"] >= MIN_ABSOLUTE_LIFT
                and (r["baseline_mean"] <= 0 or (r["relative_lift"] or 0.0) >= MIN_RELATIVE_LIFT)
            )
        r["is_anomaly"] = bool(gates)

        # CUSUM sustained shift vs transient spike classification (audit 4.3)
        cat_ent = (r["category"], r["entity_2"])
        c_res = cusum_map.get(cat_ent, {})
        c_trig = bool(c_res.get("triggered"))
        c_idx = c_res.get("change_point_index")
        w_idx = r.pop("w_idx", 0)
        is_sustained = c_trig and (c_idx is not None and w_idx >= c_idx)
        if r["is_anomaly"]:
            r["change_point_type"] = "sustained_shift" if is_sustained else "transient_spike"
            r["cusum_triggered"] = is_sustained
        else:
            r["change_point_type"] = "none"
            r["cusum_triggered"] = False

        r["in_flight_included"] = bool(in_flight) and (
            r["iso_week"] == (in_flight.get("iso_week") or r["iso_week"])
            and r["category"] == str(in_flight.get("category") or "")
            and r["entity_2"] == str(in_flight.get("entity_2") or "")
        )
        rows.append(r)
    return rows


def recompute_weekly_anomalies(
    pack_id: str,
    *,
    category: str | None = None,
    entity_2: str | None = None,
    censor_recent_days: int = 0,
) -> list[dict[str, Any]]:
    """Read ``records``, replace ``weekly_anomalies`` for *pack_id*, return rows.

    Optional category / entity_2 restrict the recompute to one slice so a live
    contact does not rescan the whole warehouse. Exposure rows (see
    ``set_exposure``) switch scoring to rates where covered; uncovered slices
    stay raw-count with ``normalized=False``.

    ``censor_recent_days`` (board #6 — right-censoring): buckets ending
    within N days of now are systematically under-reported (NHTSA/CFPB lag).
    Censored buckets are still counted but never flagged (``censored=True``),
    so the most recent bar cannot page on incomplete data.
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
        try:
            exp_rows = con.execute(
                "SELECT iso_week, category, entity_2, exposure_units FROM exposure"
                " WHERE pack_id = ?",
                [pack_id],
            ).fetchall()
            exposure_map = {
                (str(w), str(c or ""), str(e or "")): float(u)
                for w, c, e, u in exp_rows if u and float(u) > 0
            } or None
        except Exception:
            exposure_map = None
        scored = score_weekly_slices(
            count_weekly_slices(records), pack_id=pack_id, exposure=exposure_map
        )
        if censor_recent_days and censor_recent_days > 0:
            from datetime import timedelta as _td

            from src.data.timeutil import utc_now as _now

            try:
                _cutoff = (_now().replace(tzinfo=None) - _td(days=int(censor_recent_days))).date()
            except Exception:
                _cutoff = None
            if _cutoff is not None:
                for _row in scored:
                    try:
                        _y, _w = str(_row.get("iso_week") or "").split("-W")
                        from datetime import datetime as _dt

                        _start = _dt.fromisocalendar(int(_y), int(_w), 1).date()
                        _end = _start + _td(days=6)
                        if _end > _cutoff:
                            _row["censored"] = True
                            _row["is_anomaly"] = False
                        else:
                            _row.setdefault("censored", False)
                    except Exception:
                        _row.setdefault("censored", False)
        else:
            for _row in scored:
                _row.setdefault("censored", False)
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
                    baseline_mean, baseline_std, z_score, is_anomaly,
                    p_value, p_bh, baseline_weeks, method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    row.get("p_value"),
                    row.get("p_bh"),
                    row.get("baseline_weeks"),
                    row.get("method"),
                ],
            )
    return scored


__all__ = [
    "ANOMALY_Z",
    "FDR_Q",
    "MIN_BASELINE_WEEKS",
    "iso_week_label",
    "count_weekly_slices",
    "zero_fill_weeks",
    "score_weekly_slices",
    "recompute_weekly_anomalies",
    "set_exposure",
    "load_exposure",
    "detect_cusum_change_point",
]
