"""Report builder + scheduled digest runner."""

from __future__ import annotations

import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.frontline.provenance import list_kpis
from src.ids import new_ulid


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS built_reports (
            report_id VARCHAR PRIMARY KEY,
            title VARCHAR NOT NULL,
            body_json TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS digest_runs (
            run_id VARCHAR PRIMARY KEY,
            report_id VARCHAR,
            payload_json TEXT NOT NULL,
            ran_at TIMESTAMP NOT NULL
        )
        """
    )


def build_report(title: str, *, kpi_ids: list[str] | None = None, notes: str = "") -> dict[str, Any]:
    kpis = list_kpis()
    if kpi_ids:
        want = set(kpi_ids)
        kpis = [k for k in kpis if k["kpi_id"] in want]
    rid = "rpt_" + new_ulid()
    body = {"title": title, "kpis": kpis, "notes": notes, "built_at": utc_now().isoformat()}
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO built_reports (report_id, title, body_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [rid, title, json.dumps(body, default=str), utc_now()],
        )
    return {"report_id": rid, **body}


def run_scheduled_digest(report_id: str | None = None) -> dict[str, Any]:
    report = None
    if report_id:
        with ops_con(read_only=True) as con:
            row = con.execute(
                "SELECT report_id, title, body_json FROM built_reports WHERE report_id = ?",
                [report_id],
            ).fetchone()
        if row:
            report = {"report_id": row[0], "title": row[1], "body": json.loads(row[2])}
    if report is None:
        built = build_report("Daily digest")
        report = {"report_id": built["report_id"], "title": built["title"], "body": built}
    run_id = "dig_" + new_ulid()
    payload = {
        "run_id": run_id,
        "report_id": report["report_id"],
        "title": report["title"],
        "kpis": (report.get("body") or {}).get("kpis") or report.get("kpis") or [],
        "ran_at": utc_now().isoformat(),
    }
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO digest_runs (run_id, report_id, payload_json, ran_at)
            VALUES (?, ?, ?, ?)
            """,
            [run_id, report["report_id"], json.dumps(payload, default=str), utc_now()],
        )
    return payload


__all__ = ["build_report", "run_scheduled_digest"]
