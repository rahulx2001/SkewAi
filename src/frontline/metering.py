"""In-app usage metering (feature #56)."""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ops.tenant import get_tenant


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            event_id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            metric VARCHAR NOT NULL,
            quantity DOUBLE,
            meta_json VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def record_usage(
    metric: str,
    quantity: float = 1.0,
    *,
    tenant_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import json
    from src.ids import new_ulid

    tid = tenant_id or get_tenant()
    eid = f"use_{new_ulid()}"
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO usage_events (event_id, tenant_id, metric, quantity, meta_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [eid, tid, metric, float(quantity), json.dumps(meta or {})],
        )
    return {"event_id": eid, "tenant_id": tid, "metric": metric, "quantity": quantity}


def usage_summary(*, tenant_id: str | None = None, month: str | None = None) -> dict[str, Any]:
    """Aggregate contacts / llm spend / alerts for tenant (month optional YYYY-MM)."""
    tid = tenant_id or get_tenant()
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
            rows = con.execute(
                """
                SELECT metric, SUM(quantity) FROM usage_events
                WHERE tenant_id = ?
                GROUP BY metric
                """,
                [tid],
            ).fetchall()
        except Exception:
            rows = []
        # Also derive from interactions/cases if metering empty
        try:
            n_contacts = con.execute(
                "SELECT COUNT(*) FROM interactions WHERE 1=1"
            ).fetchone()[0]
        except Exception:
            n_contacts = 0
    metrics = {r[0]: float(r[1]) for r in rows}
    if "contacts" not in metrics:
        metrics["contacts"] = float(n_contacts)
    metrics.setdefault("llm_spend_usd", 0.0)
    metrics.setdefault("alerts", 0.0)
    return {
        "tenant_id": tid,
        "month": month or utc_now().strftime("%Y-%m"),
        "metrics": metrics,
        "as_of": utc_now().isoformat(),
    }
