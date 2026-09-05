"""Proactive owner notify, case-status customer payload, product-line health."""

from __future__ import annotations

from typing import Any

from src.agents.case_status import get_case_status
from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.frontline.callback import schedule_callback
from src.ids import new_ulid
from src.ledger import AgentAction, record_action


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_contacts (
            owner_id VARCHAR PRIMARY KEY,
            pack_id VARCHAR,
            entity_2 VARCHAR,
            entity_3 VARCHAR,
            cluster_id INTEGER,
            channel VARCHAR,
            address VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_notices (
            notice_id VARCHAR PRIMARY KEY,
            cluster_id INTEGER,
            owner_id VARCHAR,
            channel VARCHAR,
            status VARCHAR,
            created_at TIMESTAMP
        )
        """
    )


def register_owner(
    *,
    pack_id: str,
    entity_2: str,
    entity_3: str | None = None,
    cluster_id: int | None = None,
    channel: str = "phone",
    address: str = "",
) -> dict[str, Any]:
    oid = "own_" + new_ulid()
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO owner_contacts
            (owner_id, pack_id, entity_2, entity_3, cluster_id, channel, address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [oid, pack_id, entity_2, entity_3, cluster_id, channel, address],
        )
    return {"owner_id": oid, "entity_2": entity_2, "cluster_id": cluster_id}


def notify_affected_owners(
    *,
    pack_id: str,
    cluster_id: int,
    entity_2: str | None = None,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """Select owners for a cluster and record outreach before they call."""
    with ops_con() as con:
        _ensure(con)
        sql = (
            "SELECT owner_id, channel, address FROM owner_contacts "
            "WHERE pack_id = ? AND cluster_id = ?"
        )
        params: list[Any] = [pack_id, cluster_id]
        if entity_2:
            sql += " AND entity_2 = ?"
            params.append(entity_2)
        rows = con.execute(sql, params).fetchall()
    selected = []
    iid = interaction_id or f"int_notify_{cluster_id}"
    if rows and interaction_id is None:
        with ops_con() as con:
            exists = con.execute(
                "SELECT 1 FROM interactions WHERE interaction_id = ?", [iid]
            ).fetchone()
            if not exists:
                con.execute(
                    """
                    INSERT INTO interactions
                    (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
                    VALUES (?, ?, 'v', ?, 'web_text', 'active', FALSE, 0)
                    """,
                    [iid, pack_id, utc_now()],
                )
    for oid, channel, address in rows:
        nid = "nt_" + new_ulid()
        with ops_con() as con:
            con.execute(
                """
                INSERT INTO owner_notices
                (notice_id, cluster_id, owner_id, channel, status, created_at)
                VALUES (?, ?, ?, ?, 'sent', ?)
                """,
                [nid, cluster_id, oid, channel, utc_now()],
            )
        if channel in {"phone", "sms", "voice"}:
            schedule_callback(
                interaction_id=iid,
                pack_id=pack_id,
                phone_or_channel=str(address or oid),
                reason="proactive_cluster_notify",
            )
        selected.append({"owner_id": oid, "notice_id": nid, "channel": channel})
    ledger_recorded = False
    if selected:
        record_action(
            AgentAction(
                interaction_id=iid,
                agent="orchestrator",
                action_type="alert_sent",
                input_summary=f"cluster {cluster_id} proactive notify",
                output_summary=f"owners={len(selected)}",
            )
        )
        ledger_recorded = True
    return {
        "cluster_id": cluster_id,
        "selected": selected,
        "count": len(selected),
        "before_inbound_call": True,
        "ledger_recorded": ledger_recorded,
    }


def customer_case_update(case_id: str) -> dict[str, Any]:
    """Customer-facing status payload matching warehouse case status."""
    row = get_case_status(case_id)
    if not row:
        raise LookupError(case_id)
    payload = {
        "case_id": row["case_id"],
        "status": row["status"],
        "severity": row.get("severity"),
        "category": row.get("category"),
        "investigation_id": row.get("investigation_id"),
        "customer_text": (
            f"Case {row['case_id']} is {row['status']}. "
            f"Severity {row.get('severity') or 'n/a'}."
        ),
    }
    if row.get("interaction_id"):
        try:
            record_action(
                AgentAction(
                    interaction_id=row["interaction_id"],
                    agent="case",
                    action_type="case_status_updated",
                    input_summary=case_id,
                    output_summary=payload["customer_text"],
                    case_id=row["case_id"],
                )
            )
        except Exception:
            pass
    return payload


def product_line_health(
    *,
    pack_id: str | None = None,
    entity_3: str | None = None,
    category: str | None = None,
    window_days: int = 30,
) -> dict[str, Any]:
    """CSAT/sentiment trend tied to a product/quality category."""
    from datetime import timedelta
    from src.data.timeutil import utc_now as now

    cutoff = now() - timedelta(days=max(1, window_days))
    with ops_con(read_only=True) as con:
        sql = """
            SELECT i.entity_3, i.category, i.peak_frustration, i.started_at
            FROM interactions i
            WHERE i.started_at >= ?
        """
        params: list[Any] = [cutoff]
        if pack_id:
            sql += " AND i.pack_id = ?"
            params.append(pack_id)
        if entity_3:
            sql += " AND i.entity_3 = ?"
            params.append(entity_3)
        if category:
            sql += " AND i.category = ?"
            params.append(category)
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            rows = []
    fr = [float(r[2]) for r in rows if r[2] is not None]
    avg = sum(fr) / len(fr) if fr else 0.0
    csat = max(0.0, min(1.0, 1.0 - avg))
    return {
        "entity_3": entity_3,
        "category": category,
        "n": len(rows),
        "avg_frustration": avg,
        "csat_proxy": csat,
        "tied_to_quality": bool(category),
    }


__all__ = [
    "register_owner",
    "notify_affected_owners",
    "customer_case_update",
    "product_line_health",
]
