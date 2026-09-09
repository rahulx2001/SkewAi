"""KPI provenance: every dashboard figure has a chain of custody."""

from __future__ import annotations

from typing import Any, Callable

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.data.trust import lineage_for_record


def _count(sql: str, params: list[Any] | None = None) -> int:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(sql, params or []).fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0


def _open_cases() -> dict[str, Any]:
    n = _count(
        """
        SELECT COUNT(*) FROM cases
        WHERE status IN ('open', 'pending_followup')
          AND (interaction_id IS NULL OR interaction_id NOT IN
               (SELECT interaction_id FROM interactions WHERE channel = 'simulated'))
        """
    )
    return {
        "value": n,
        "unit": "cases",
        "source_table": "cases",
        "filter": "status open|pending_followup, exclude simulated",
    }


def _open_investigations() -> dict[str, Any]:
    n = _count("SELECT COUNT(*) FROM investigations WHERE status = 'open'")
    return {"value": n, "unit": "investigations", "source_table": "investigations", "filter": "status=open"}


def _contacts_started() -> dict[str, Any]:
    n = _count(
        "SELECT COUNT(*) FROM interactions WHERE COALESCE(channel, '') <> 'simulated'"
    )
    return {
        "value": n,
        "unit": "contacts",
        "source_table": "interactions",
        "filter": "exclude simulated",
    }


def _trusted_records() -> dict[str, Any]:
    n = _count("SELECT COUNT(*) FROM record_trust WHERE trusted = TRUE")
    return {"value": n, "unit": "records", "source_table": "record_trust", "filter": "trusted=true"}


KPI_COMPUTE: dict[str, Callable[[], dict[str, Any]]] = {
    "open_cases": _open_cases,
    "open_investigations": _open_investigations,
    "contacts_started": _contacts_started,
    "trusted_records": _trusted_records,
}


def list_kpis() -> list[dict[str, Any]]:
    out = []
    for kid in KPI_COMPUTE:
        out.append(kpi_lineage(kid))
    return out


def kpi_lineage(kpi_id: str) -> dict[str, Any]:
    fn = KPI_COMPUTE.get(kpi_id)
    if fn is None:
        raise KeyError(kpi_id)
    computed = fn()
    freshness = "live"
    grounded = "computed"
    source = computed.get("source_table") or "ops"
    badge = {
        "source": source,
        "freshness": freshness,
        "grounded_verdict": grounded,
        "why_trusted": f"{source} → {freshness} → {grounded}",
    }
    chain = [
        {"step": "kpi", "value": kpi_id},
        {"step": "source", "value": source},
        {"step": "filter", "value": computed.get("filter")},
        {"step": "freshness", "value": freshness},
        {"step": "grounded_verdict", "value": grounded},
        {"step": "value", "value": computed.get("value")},
        {"step": "as_of", "value": utc_now().isoformat()},
    ]
    return {
        "kpi_id": kpi_id,
        "value": computed.get("value"),
        "unit": computed.get("unit"),
        "badge": badge,
        "chain_of_custody": chain,
        "source_table": source,
        "filter": computed.get("filter"),
    }


def figure_lineage(kpi_id: str, *, record_id: str | None = None, pack_id: str | None = None) -> dict[str, Any]:
    """KPI chain plus optional cited-record trust badge."""
    body = kpi_lineage(kpi_id)
    if record_id and pack_id:
        rec = lineage_for_record(pack_id, record_id)
        if rec:
            body["cited_record"] = rec
            body["chain_of_custody"] = list(body["chain_of_custody"]) + rec.get(
                "chain_of_custody", []
            )
    return body


__all__ = ["list_kpis", "kpi_lineage", "figure_lineage", "KPI_COMPUTE"]
