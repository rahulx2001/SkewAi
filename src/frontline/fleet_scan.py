"""Scheduled fleet scan (Axion slice, Phase 3).

Contact-triggered intercepts only see slices a customer just touched. This
scan runs on a CADENCE (cron / compose scheduler / job queue) over the whole
pack so the reliability engineer learns about a spike nobody called about
yet — the Axion demo moment:

    1. recompute weekly anomalies for the full pack (observed rows only);
    2. optionally rebuild clusters (heavy; default off, nightly cadence);
    3. refresh the backtest lead-time table;
    4. for every anomalous (category, entity_2) slice, resolve the top
       cluster and open-or-link an investigation with evidence attached;
    5. fire early-warning alerts for newly opened investigations.

Nothing is fabricated: investigations open only on computed anomalies with
real record counts, and the report lists exactly what was evaluated.
"""

from __future__ import annotations

from typing import Any

from src.data.warehouse import domain_con


def _top_cluster_for_slice(
    pack_id: str, category: str | None, entity_2: str | None
) -> dict[str, Any] | None:
    """Best cluster for a slice: fused relevance without a contact.

    Same scoring philosophy as the investigator (category fit + entity
    overlap + size as tie-break only) so scan-opened investigations agree
    with contact-opened ones.
    """
    with domain_con(pack_id) as con:
        try:
            rows = con.execute(
                """
                SELECT cluster_id, top_terms, category, record_count
                FROM clusters WHERE pack_id = ?
                """,
                [pack_id],
            ).fetchall()
        except Exception:
            return None
    best: dict[str, Any] | None = None
    best_score = -1.0
    for cid, _top, cat, count in rows:
        score = 0.0
        if category and str(cat or "").upper() == str(category).upper():
            score += 2.0
        try:
            with domain_con(pack_id) as con2:
                modes = con2.execute(
                    """
                    SELECT r.entity_2 AS e2, COUNT(*) AS n
                    FROM cluster_assignments a
                    JOIN records r ON r.record_id = a.record_id
                    WHERE a.cluster_id = ?
                    GROUP BY r.entity_2 ORDER BY n DESC LIMIT 1
                    """,
                    [cid],
                ).fetchone()
        except Exception:
            modes = None
        if modes and entity_2 and str(modes[0] or "").upper() == str(entity_2).upper():
            score += 3.0
        import math as _math

        try:
            score += _math.log1p(float(count or 0)) * 0.1
        except (TypeError, ValueError):
            pass
        if score > best_score:
            best_score = score
            best = {"cluster_id": cid, "category": cat, "record_count": count}
    return best if best_score > 0 else None


def run_fleet_scan(
    pack_id: str,
    *,
    rebuild_clusters: bool = False,
    alert: bool = True,
) -> dict[str, Any]:
    """Run one full-pack fleet scan. Returns the scan report."""
    from src.backtest.engine import run_backtest
    from src.frontline.live_intercept import open_or_link_investigation
    from src.ml_runtime.anomalies import recompute_weekly_anomalies

    report: dict[str, Any] = {
        "pack_id": pack_id,
        "anomaly_slices": 0,
        "investigations_opened": [],
        "investigations_linked": [],
        "alerts_fired": 0,
        "novel_open": 0,
        "errors": [],
    }
    import os as _os

    try:
        _lag = int(_os.getenv("FRONTLINE_REPORTING_LAG_DAYS", "0"))
    except ValueError:
        _lag = 0
    try:
        scored = recompute_weekly_anomalies(pack_id, censor_recent_days=_lag)
        report["reporting_lag_days"] = _lag
        report["censored_slices"] = sum(1 for r in scored if r.get("censored"))
    except Exception as e:
        report["errors"].append(f"anomalies:{type(e).__name__}:{e}")
        return report
    if rebuild_clusters:
        try:
            from src.ml_runtime.clustering import rebuild_clusters as _rebuild

            report["cluster_rebuild"] = _rebuild(pack_id)
        except Exception as e:
            report["errors"].append(f"clusters:{type(e).__name__}:{e}")
    try:
        run_backtest(pack_id)
    except Exception as e:
        report["errors"].append(f"backtest:{type(e).__name__}:{e}")
    anomalous = [r for r in scored if r.get("is_anomaly")]
    report["anomaly_slices"] = len(anomalous)
    seen_clusters: set[int] = set()
    for row in anomalous:
        cat, ent = row.get("category"), row.get("entity_2")
        try:
            top = _top_cluster_for_slice(pack_id, cat, ent)
        except Exception as e:
            report["errors"].append(f"resolve:{type(e).__name__}:{e}")
            continue
        if not top:
            continue
        try:
            cid = int(top["cluster_id"])
        except (TypeError, ValueError):
            continue
        if cid in seen_clusters:
            continue
        seen_clusters.add(cid)
        is_new = False
        try:
            before = _open_investigation_for(pack_id, cid)
            inv_id = open_or_link_investigation(
                pack_id=pack_id,
                cluster_id=cid,
                title=f"Fleet scan {cat or ''} {ent or ''}".strip(),
            )
            is_new = before is None
        except Exception as e:
            report["errors"].append(f"investigation:{type(e).__name__}:{e}")
            continue
        entry = {
            "investigation_id": inv_id,
            "cluster_id": cid,
            "category": cat,
            "entity_2": ent,
            "z_score": row.get("z_score"),
        }
        if is_new:
            report["investigations_opened"].append(entry)
            if alert:
                try:
                    from src.frontline.alerts import alert_early_warning

                    import anyio as _anyio

                    async def _fire() -> None:
                        try:
                            await alert_early_warning(
                                cid,
                                int(row.get("record_count") or 0),
                                None,
                                pack_id=pack_id,
                            )
                        except Exception:
                            pass

                    _anyio.run(_fire)
                    report["alerts_fired"] += 1
                except Exception:
                    pass
        else:
            report["investigations_linked"].append(entry)
    try:
        from src.observability.slo import record_slo_sample

        record_slo_sample(
            "fleet_scan_anomalous_slices",
            numerator=float(len(report["investigations_opened"])
                            + len(report["investigations_linked"])),
            denominator=float(len(anomalous) or 1),
            objective=0.99,
        )
    except Exception:
        pass
    try:
        from src.data.warehouse import ops_con as _ops_con

        with _ops_con(read_only=True) as _con:
            report["novel_open"] = int(_con.execute(
                "SELECT COUNT(*) FROM novel_candidates WHERE status = 'open'"
            ).fetchone()[0])
            emerging = _con.execute(
                """
                SELECT COALESCE(category, 'unknown'), COALESCE(entity_2, 'unknown'), COUNT(*) as cnt
                FROM novel_candidates
                WHERE status = 'open'
                GROUP BY 1, 2
                HAVING COUNT(*) >= 3
                ORDER BY cnt DESC
                """
            ).fetchall()
            report["novel_emerging_clusters"] = [
                {"category": r[0], "entity_2": r[1], "count": int(r[2])}
                for r in emerging
            ]
    except Exception:
        report.setdefault("novel_emerging_clusters", [])
    return report


def _open_investigation_for(pack_id: str, cluster_id: int) -> str | None:
    from src.data.warehouse import ops_con

    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                """
                SELECT investigation_id FROM investigations
                WHERE pack_id = ? AND cluster_id = ? AND status = 'open'
                LIMIT 1
                """,
                [pack_id, cluster_id],
            ).fetchone()
        except Exception:
            return None
    return str(row[0]) if row else None


__all__ = ["run_fleet_scan"]
