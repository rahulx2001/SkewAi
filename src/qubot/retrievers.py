"""Qubot v2 retrievers — read-only SQL over the ops + domain warehouses.

Retrievers are the "DB computes" half of Qubot. Each returns a plain dict of
rows/stats that the auditor (or the ask-data layer) narrates. They never call
an LLM and never invent numbers — every figure is traceable to a SQL result.

All functions are synchronous (DuckDB is fast, in-process) and read-only.
"""

from __future__ import annotations

import json
from typing import Any

from src.data.warehouse import domain_con, ops_con


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rows(con, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in con.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k, v in d.items():
            if isinstance(v, str) and k in {"evidence_ids", "safety_flags", "top_terms"}:
                try:
                    d[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass
        out.append(d)
    return out


# ── 1. contact_audit ─────────────────────────────────────────────────────────

def contact_audit(interaction_id: str) -> dict[str, Any]:
    """Full ordered trace of one contact: header + turns + actions + case.

    This is the primary input to the post-contact audit playbook.
    """
    with ops_con(read_only=True) as con:
        header = _rows(con, "SELECT * FROM interactions WHERE interaction_id = ?", [interaction_id])
        turns = _rows(
            con,
            "SELECT * FROM interaction_turns WHERE interaction_id = ? ORDER BY seq",
            [interaction_id],
        )
        from src.data.turns import decrypt_turn_rows

        turns = decrypt_turn_rows(interaction_id, turns)
        actions = _rows(
            con,
            "SELECT * FROM agent_actions WHERE interaction_id = ? ORDER BY ts",
            [interaction_id],
        )
        case = _rows(con, "SELECT * FROM cases WHERE interaction_id = ?", [interaction_id])
        from src.security.pii import decrypt_case_rows

        case = decrypt_case_rows(case)
    if not header:
        raise FileNotFoundError(f"interaction not found: {interaction_id}")
    return {
        "interaction": header[0],
        "turns": turns,
        "actions": actions,
        "case": case[0] if case else None,
    }


# ── 2. agent_performance ─────────────────────────────────────────────────────

def agent_performance(window_days: int = 1) -> list[dict[str, Any]]:
    """Per-agent action counts, error rate, p50/p95 duration over the window."""
    sql = """
    SELECT
        agent,
        COUNT(*) AS action_count,
        SUM(CASE WHEN NOT ok THEN 1 ELSE 0 END) AS error_count,
        ROUND(100.0 * SUM(CASE WHEN NOT ok THEN 1 ELSE 0 END) / COUNT(*), 2) AS error_rate_pct,
        ROUND(AVG(duration_ms), 1) AS avg_duration_ms,
        ROUND(QUANTILE_CONT(duration_ms, 0.5), 1) AS p50_duration_ms,
        ROUND(QUANTILE_CONT(duration_ms, 0.95), 1) AS p95_duration_ms
    FROM agent_actions
    WHERE ts >= now() - INTERVAL (? || ' days')
    GROUP BY agent
    ORDER BY action_count DESC
    """
    with ops_con(read_only=True) as con:
        return _rows(con, sql, [str(window_days)])


# ── 3. live_risk ─────────────────────────────────────────────────────────────

def live_risk(
    window_days: int = 7,
    *,
    as_of: str | None = None,
    include_simulated: bool = False,
) -> list[dict[str, Any]]:
    """Cases grouped by matched cluster, joined to weekly anomalies + backtest.

    Surfaces clusters that are heating up right now, with the historical
    lead-time (the "did spikes precede advisories" moat) attached.

    Trend scope (item 27): each cluster's trend is its OWN
    (category, entity_2) slice — entity_2 resolved as the modal member-record
    value — over matched-lead history. A global or category-only trend is
    never returned for an unrelated cluster. ``as_of`` (ISO week or full
    timestamp) caps the series for reproducible historical reads.
    """
    kind_sql = (
        "1=1"
        if include_simulated
        else "COALESCE(c.case_kind, 'customer') = 'customer'"
    )
    sql = f"""
    SELECT
        c.cluster_match_id AS cluster_id,
        c.pack_id,
        COUNT(*) AS live_case_count,
        MAX(c.created_at) AS last_case_at,
        SUM(CASE WHEN c.severity = 'Critical' THEN 1 ELSE 0 END) AS critical_count
    FROM cases c
    WHERE c.cluster_match_id IS NOT NULL
      AND c.created_at >= now() - INTERVAL (? || ' days')
      AND ({kind_sql})
    GROUP BY c.cluster_match_id, c.pack_id
    ORDER BY live_case_count DESC
    """
    with ops_con(read_only=True) as con:
        clusters = _rows(con, sql, [str(window_days)])

    # Enrich each cluster with corpus trend + lead-time from the domain warehouse.
    # Batched per pack (item 27): one domain connection per pack, one trend
    # query per pack — never N+1 opens. Trends are scoped to the cluster's own
    # (category, entity_2) slice with matched-only lead.
    try:
        _pack_ids = sorted({c["pack_id"] for c in clusters})
        _lead_by_cid: dict[tuple[str, int], dict[str, Any]] = {}
        _slice_by_cid: dict[tuple[str, int], tuple[str | None, str | None]] = {}
        _trend_by_slice: dict[tuple[str, str | None, str | None], list[dict[str, Any]]] = {}
        for _pid in _pack_ids:
            try:
                with domain_con(_pid) as _dcon:
                    for _lr in _rows(
                        _dcon,
                        "SELECT cluster_id, advisory_id, lead_time_weeks, matched FROM backtest_results WHERE matched = TRUE",
                    ):
                        try:
                            _lead_by_cid[(_pid, int(_lr["cluster_id"]))] = _lr
                        except (TypeError, ValueError):
                            continue
                    # Cluster slices: category from clusters, entity_2 as the
                    # modal member-record value (record-level, not inferred).
                    try:
                        for _crow in _rows(
                            _dcon,
                            "SELECT cluster_id, category FROM clusters WHERE pack_id = ?",
                            [_pid],
                        ):
                            try:
                                _cid_int = int(_crow["cluster_id"])
                            except (TypeError, ValueError):
                                continue
                            _slice_by_cid[(_pid, _cid_int)] = (
                                _crow.get("category"),
                                None,
                            )
                        try:
                            _modes = _rows(
                                _dcon,
                                """
                                SELECT a.cluster_id AS cluster_id, r.entity_2 AS entity_2,
                                       COUNT(*) AS n
                                FROM cluster_assignments a
                                JOIN records r ON r.record_id = a.record_id
                                WHERE r.entity_2 IS NOT NULL
                                GROUP BY a.cluster_id, r.entity_2
                                """,
                            )
                            _best: dict[int, tuple[int, str]] = {}
                            for _m in _modes:
                                try:
                                    _mc = int(_m["cluster_id"])
                                except (TypeError, ValueError):
                                    continue
                                _n = int(_m["n"] or 0)
                                if _mc not in _best or _n > _best[_mc][0]:
                                    _best[_mc] = (_n, str(_m["entity_2"]))
                            for _mc, (_, _ent) in _best.items():
                                _cat, _ = _slice_by_cid.get((_pid, _mc), (None, None))
                                _slice_by_cid[(_pid, _mc)] = (_cat, _ent)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    # One trend query per pack across all needed slices.
                    try:
                        _asof_clause = ""
                        _asof_params: list[Any] = [_pid]
                        if as_of:
                            _asof_clause = "AND iso_week <= ?"
                            _asof_params.append(str(as_of)[:8])
                        for _tr in _rows(
                            _dcon,
                            f"""
                            SELECT category, entity_2, iso_week,
                                   SUM(record_count) AS record_count,
                                   MAX(z_score) AS z_score,
                                   MAX(CASE WHEN is_anomaly THEN 1 ELSE 0 END) = 1 AS is_anomaly
                            FROM weekly_anomalies
                            WHERE pack_id = ? {_asof_clause}
                            GROUP BY category, entity_2, iso_week
                            ORDER BY iso_week DESC
                            """,
                            _asof_params,
                        ):
                            _key = (_pid, _tr.get("category"), _tr.get("entity_2"))
                            _trend_by_slice.setdefault(_key, []).append(_tr)
                    except Exception:
                        pass
            except FileNotFoundError:
                continue
    except Exception:
        _lead_by_cid = {}
        _slice_by_cid = {}
        _trend_by_slice = {}
    for cl in clusters:
        pack_id = cl["pack_id"]
        cid = cl["cluster_id"]
        try:
            _cid = int(cid) if str(cid).lstrip("-").isdigit() else None
        except (TypeError, ValueError):
            _cid = None
        lead = _lead_by_cid.get((pack_id, _cid)) if _cid is not None else None
        cl["lead_time_weeks"] = (lead or {}).get("lead_time_weeks")
        cl["matched_advisory"] = (lead or {}).get("advisory_id")
        ccat, cent = _slice_by_cid.get((pack_id, _cid), (None, None)) if _cid is not None else (None, None)
        trend = list(_trend_by_slice.get((pack_id, ccat, cent), []))
        scope = "category+entity_2"
        if not trend and ccat:
            # Category-only fallback when the entity slice has no history:
            # aggregate the category across entities IN PYTHON from the
            # already-fetched per-pack rows (no extra queries), and label it
            # so callers never mistake it for entity-scoped truth.
            by_week: dict[str, dict[str, Any]] = {}
            for (p, c, _e), rows in _trend_by_slice.items():
                if p != pack_id or c != ccat:
                    continue
                for t in rows:
                    w = str(t.get("iso_week"))
                    cell = by_week.setdefault(w, {
                        "category": ccat, "entity_2": None,
                        "iso_week": w, "record_count": 0,
                        "z_score": None, "is_anomaly": False,
                    })
                    try:
                        cell["record_count"] += int(t.get("record_count") or 0)
                    except (TypeError, ValueError):
                        pass
                    try:
                        z = t.get("z_score")
                        if z is not None and (cell["z_score"] is None or float(z) > float(cell["z_score"])):
                            cell["z_score"] = z
                    except (TypeError, ValueError):
                        pass
                    if t.get("is_anomaly"):
                        cell["is_anomaly"] = True
            trend = [dict(v, trend_scope="category-only-fallback")
                     for _, v in sorted(by_week.items(), reverse=True)]
            scope = "category-only-fallback" if trend else "no-history"
        if not ccat:
            scope = "pack-unscoped"
        cl["trend_scope"] = scope
        cl["trend_entity_2"] = cent
        cl["weekly_trend"] = (trend or [])[:8]
        n = float(cl.get("live_case_count") or 0)
        crit = float(cl.get("critical_count") or 0)
        cl["live_risk_score"] = round(
            min(1.0, (n / 20.0) * 0.6 + (crit / max(n, 1.0)) * 0.4),
            4,
        )
    return clusters


def live_risk_by_dollar(window_days: int = 7) -> list[dict[str, Any]]:
    """Early-warning feed ranked by COPQ dollars, not volume."""
    from src.frontline.copq import load_cluster_costs, rank_by_dollar

    clusters = live_risk(window_days)
    costs = {
        (c.get("pack_id"), int(c.get("cluster_id") or 0)): c
        for c in load_cluster_costs()
    }
    slices = []
    for cl in clusters:
        key = (cl.get("pack_id"), int(cl.get("cluster_id") or 0))
        cost = costs.get(key) or {}
        dollars = float(cost.get("total") or 0)
        slices.append({**cl, "dollar_impact": dollars, "copq": cost or None})
    # Clusters with no live_risk row but a cost model still compete
    seen = {(s.get("pack_id"), int(s.get("cluster_id") or 0)) for s in slices}
    for key, cost in costs.items():
        if key in seen:
            continue
        slices.append(
            {
                "cluster_id": key[1],
                "pack_id": key[0],
                "live_case_count": 0,
                "dollar_impact": float(cost.get("total") or 0),
                "copq": cost,
            }
        )
    return rank_by_dollar(slices)


# ── 4. case_funnel ───────────────────────────────────────────────────────────

def case_funnel(window_days: int = 7) -> dict[str, Any]:
    """started → completed → cases → advisories notified → escalations → takeovers."""
    sql = """
    SELECT
        COUNT(*) AS started,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END) AS abandoned,
        SUM(CASE WHEN status = 'escalated' THEN 1 ELSE 0 END) AS escalated,
        SUM(CASE WHEN supervised THEN 1 ELSE 0 END) AS takeovers,
        SUM(CASE WHEN outcome = 'advisory_notified' THEN 1 ELSE 0 END) AS advisories_notified
    FROM interactions
    WHERE started_at >= now() - INTERVAL (? || ' days')
    """
    cases_sql = """
    SELECT COUNT(*) AS case_count
    FROM cases
    WHERE created_at >= now() - INTERVAL (? || ' days')
      AND COALESCE(case_kind, 'customer') = 'customer'
    """
    with ops_con(read_only=True) as con:
        funnel = _rows(con, sql, [str(window_days)])[0]
        cases = _rows(con, cases_sql, [str(window_days)])[0]
    funnel["cases_created"] = cases["case_count"]
    # Normalize None sums to 0 for clean narration.
    for k, v in funnel.items():
        if v is None:
            funnel[k] = 0
    return funnel


# ── 5. investigation_status ──────────────────────────────────────────────────

def investigation_status(investigation_id: str | None = None, window_days: int = 30) -> list[dict[str, Any]]:
    """Investigation header(s) + linked cases + cluster trend.

    Uses a single cases IN-list fetch instead of N+1 per-investigation queries.
    """
    with ops_con(read_only=True) as con:
        if investigation_id:
            invs = _rows(
                con,
                """
                SELECT *,
                       DATE_DIFF('day', opened_at, COALESCE(last_case_at, now())) AS days_open
                FROM investigations
                WHERE investigation_id = ?
                """,
                [investigation_id],
            )
        else:
            invs = _rows(
                con,
                """
                SELECT *,
                       DATE_DIFF('day', opened_at, COALESCE(last_case_at, now())) AS days_open
                FROM investigations
                WHERE opened_at >= now() - INTERVAL (? || ' days')
                ORDER BY opened_at DESC
                """,
                [str(window_days)],
            )
        if not invs:
            return []

        inv_ids = [i["investigation_id"] for i in invs]
        placeholders = ", ".join("?" for _ in inv_ids)
        case_rows = _rows(
            con,
            f"""
            SELECT case_id, category, severity, priority, status, created_at, investigation_id
            FROM cases
            WHERE investigation_id IN ({placeholders})
            ORDER BY created_at DESC
            """,
            inv_ids,
        )
        by_inv: dict[str, list[dict[str, Any]]] = {iid: [] for iid in inv_ids}
        for row in case_rows:
            iid = row.get("investigation_id")
            if iid in by_inv:
                # Keep payload shape: investigation_id not required on nested case cards
                slim = {k: v for k, v in row.items() if k != "investigation_id"}
                by_inv[iid].append(slim)
        for inv in invs:
            inv["cases"] = by_inv.get(inv["investigation_id"], [])
    return invs


# ── 6. daily_counts ─────────────────────────────────────────────────────────────


def daily_counts(days: int = 7) -> list[dict[str, Any]]:
    """Per-day interaction/case counts (UTC) for trend questions."""
    sql = """
    SELECT
        CAST(started_at AS DATE) AS day,
        COUNT(*) AS started,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END) AS abandoned
    FROM interactions
    WHERE started_at >= now() - INTERVAL (? || ' days')
    GROUP BY day
    ORDER BY day
    """
    with ops_con(read_only=True) as con:
        return _rows(con, sql, [str(days)])


# ── 7. top_offenders ────────────────────────────────────────────────────────────


def top_offenders(pack_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Top offenders in a pack domain corpus, by record count.

    The domain `records` table is pack-agnostic (`entity_1/2/3` are pack-
    labeled: automotive Make/Model; finance sub_product/company, etc.). We
    rank by the concrete maker/company column (`entity_3`) and surface the
    complaint `category` breakdown alongside, so the result reads
    "<entity> — <n> records, top categories …" regardless of vertical.
    """
    with domain_con(pack_id) as con:
        cols = {
            r[1] for r in con.execute("PRAGMA table_info(records)").fetchall()
        }
        if "entity_3" not in cols or "category" not in cols:
            return []
        sql = """
        SELECT
            COALESCE(entity_3, '(unknown)') AS entity,
            COUNT(*) AS records,
            MODE(category) AS top_category
        FROM records
        GROUP BY entity
        ORDER BY records DESC, entity
        LIMIT ?
        """
        return _rows(con, sql, [limit])


# ── Registry (used by the ask-data router) ───────────────────────────────────

RETRIEVERS = {
    "contact_audit": contact_audit,
    "agent_performance": agent_performance,
    "live_risk": live_risk,
    "case_funnel": case_funnel,
    "investigation_status": investigation_status,
    "daily_counts": daily_counts,
    "top_offenders": top_offenders,
}

__all__ = [
    "contact_audit",
    "agent_performance",
    "live_risk",
    "case_funnel",
    "investigation_status",
    "daily_counts",
    "top_offenders",
    "RETRIEVERS",
]
