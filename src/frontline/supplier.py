"""Supplier scorecards, lot traceability, supplier CAPA."""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import domain_con, ops_con
from src.ids import new_ulid
from src.ledger import AgentAction, record_action


def _ensure_ops(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS record_supply (
            record_id VARCHAR PRIMARY KEY,
            pack_id VARCHAR NOT NULL,
            supplier VARCHAR,
            lot_id VARCHAR,
            lot_start VARCHAR,
            lot_end VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_capa (
            capa_id VARCHAR PRIMARY KEY,
            supplier VARCHAR NOT NULL,
            pack_id VARCHAR,
            lot_id VARCHAR,
            status VARCHAR NOT NULL,
            request TEXT,
            response TEXT,
            opened_at TIMESTAMP NOT NULL,
            responded_at TIMESTAMP
        )
        """
    )


def attach_supply(
    *,
    record_id: str,
    pack_id: str,
    supplier: str,
    lot_id: str,
    lot_start: str | None = None,
    lot_end: str | None = None,
) -> dict[str, Any]:
    with ops_con() as con:
        _ensure_ops(con)
        con.execute(
            """
            INSERT OR REPLACE INTO record_supply
            (record_id, pack_id, supplier, lot_id, lot_start, lot_end)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [record_id, pack_id, supplier, lot_id, lot_start, lot_end],
        )
    try:
        with domain_con(pack_id, read_only=False) as dcon:
            for col in ("supplier", "lot_id", "lot_start", "lot_end"):
                try:
                    dcon.execute(f"ALTER TABLE records ADD COLUMN {col} VARCHAR")
                except Exception:
                    pass
            dcon.execute(
                """
                UPDATE records SET supplier = ?, lot_id = ?, lot_start = ?, lot_end = ?
                WHERE record_id = ?
                """,
                [supplier, lot_id, lot_start, lot_end, record_id],
            )
    except Exception:
        pass
    return {
        "record_id": record_id,
        "supplier": supplier,
        "lot_id": lot_id,
        "lot_start": lot_start,
        "lot_end": lot_end,
    }


def supplier_scorecards(pack_id: str | None = None) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            _ensure_ops(con)
            sql = """
                SELECT supplier, lot_id, COUNT(*) AS n
                FROM record_supply
            """
            params: list[Any] = []
            if pack_id:
                sql += " WHERE pack_id = ?"
                params.append(pack_id)
            sql += " GROUP BY supplier, lot_id"
            rows = con.execute(sql, params).fetchall()
        except Exception:
            rows = []
    by_sup: dict[str, dict[str, Any]] = {}
    for sup, lot, n in rows:
        rec = by_sup.setdefault(
            str(sup),
            {"supplier": str(sup), "failures": 0, "lots": {}},
        )
        rec["failures"] += int(n)
        rec["lots"][str(lot)] = rec["lots"].get(str(lot), 0) + int(n)
    out = list(by_sup.values())
    out.sort(key=lambda x: -x["failures"])
    for i, row in enumerate(out, 1):
        row["rank"] = i
    return out


def lot_trace(record_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                """
                SELECT record_id, pack_id, supplier, lot_id, lot_start, lot_end
                FROM record_supply WHERE record_id = ?
                """,
                [record_id],
            ).fetchone()
        except Exception:
            return None
    if not row:
        return None
    return {
        "record_id": row[0],
        "pack_id": row[1],
        "supplier": row[2],
        "lot_id": row[3],
        "lot_start": row[4],
        "lot_end": row[5],
    }


def open_supplier_capa(
    *,
    supplier: str,
    pack_id: str,
    request: str,
    lot_id: str | None = None,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    cid = "capa_" + new_ulid()
    with ops_con() as con:
        _ensure_ops(con)
        con.execute(
            """
            INSERT INTO supplier_capa
            (capa_id, supplier, pack_id, lot_id, status, request, response, opened_at)
            VALUES (?, ?, ?, ?, 'open', ?, NULL, ?)
            """,
            [cid, supplier, pack_id, lot_id, request, utc_now()],
        )
    if interaction_id:
        try:
            record_action(
                AgentAction(
                    interaction_id=interaction_id,
                    agent="case",
                    action_type="connector_dispatched",
                    input_summary=f"supplier_capa {supplier}",
                    output_summary=f"capa_id={cid}; status=open",
                )
            )
        except Exception:
            pass
    return {
        "capa_id": cid,
        "supplier": supplier,
        "status": "open",
        "request": request,
        "lot_id": lot_id,
    }


def respond_supplier_capa(capa_id: str, response: str) -> dict[str, Any]:
    with ops_con() as con:
        _ensure_ops(con)
        con.execute(
            """
            UPDATE supplier_capa
            SET status = 'responded', response = ?, responded_at = ?
            WHERE capa_id = ?
            """,
            [response, utc_now(), capa_id],
        )
        row = con.execute(
            "SELECT capa_id, supplier, status, request, response FROM supplier_capa WHERE capa_id = ?",
            [capa_id],
        ).fetchone()
    if not row:
        raise LookupError(capa_id)
    return {
        "capa_id": row[0],
        "supplier": row[1],
        "status": row[2],
        "request": row[3],
        "response": row[4],
    }


__all__ = [
    "attach_supply",
    "supplier_scorecards",
    "lot_trace",
    "open_supplier_capa",
    "respond_supplier_capa",
]
