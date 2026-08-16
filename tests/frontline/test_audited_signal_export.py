"""Audited-signal export: outbox artifact + ledger linkage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.data.warehouse import ops_con
from src.frontline import connectors as conn_mod
from src.frontline.connectors import export_audited_signal, reset_connector_config_cache


def test_export_audited_signal_writes_outbox_and_ledger(tmp_path, reset_ops_db, monkeypatch):
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    monkeypatch.setattr(conn_mod, "OUTBOX_DIR", outbox)
    monkeypatch.setattr(conn_mod, "REPO_ROOT", tmp_path)
    reset_connector_config_cache()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at,
                category, description_summary, onset, severity,
                severity_source, priority, safety_flags,
                advisory_match_id, cluster_match_id, similar_record_count,
                investigation_id, status, followup_draft
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "case_audit_exp",
                "int_audit_exp",
                "automotive_nhtsa",
                datetime.now(timezone.utc),
                "SERVICE BRAKES",
                "grinding",
                datetime.now(timezone.utc),
                "Medium",
                "rules",
                2,
                "{}",
                None,
                None,
                0,
                None,
                "open",
                None,
            ],
        )

    result = export_audited_signal(
        "case_created",
        case_id="case_audit_exp",
        interaction_id="int_audit_exp",
        pack_id="automotive_nhtsa",
        category="SERVICE BRAKES",
        severity="Medium",
    )
    assert result["ok"] is True
    assert result["event"] == "case_created"
    assert result["ref_id"] == "case_audit_exp"
    assert result["delivery_id"]
    assert result["ledger_action_id"]
    assert result["ledger_row_hash"]
    assert result["outbox_path"]

    files = list(outbox.glob("*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["event"] == "case_created"
    assert body["case_id"] == "case_audit_exp"
    assert body["audit"]["delivery_id"] == result["delivery_id"]
    assert body["audit"]["ledger_action_id"] == result["ledger_action_id"]
    assert body["audit"]["ledger_row_hash"] == result["ledger_row_hash"]
    assert body["audit"]["ref_id"] == "case_audit_exp"

    with ops_con(read_only=True) as con:
        action = con.execute(
            """
            SELECT action_type, row_hash, evidence_ids
            FROM agent_actions WHERE action_id = ?
            """,
            [result["ledger_action_id"]],
        ).fetchone()
        delivery = con.execute(
            "SELECT status, event, ref_id FROM connector_deliveries WHERE delivery_id = ?",
            [result["delivery_id"]],
        ).fetchone()
    assert action is not None
    assert action[0] == "signal_exported"
    assert action[1] == result["ledger_row_hash"]
    assert delivery is not None
    assert delivery[0] == "success"
    assert delivery[1] == "case_created"
    assert delivery[2] == "case_audit_exp"
