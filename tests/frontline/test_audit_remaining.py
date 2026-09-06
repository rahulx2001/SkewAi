"""Regression tests for remaining audit findings F-008..F-022 and selected mediums."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pytest

from src.ids import new_ulid
from src.security.pii import SubjectKeyStore, decrypt_subject_pii, encrypt_subject_pii


def test_f009_no_human_category_leak():
    src = open("src/frontline/shadow_pilot.py", encoding="utf-8").read()
    assert 'elif human_slots.get("category")' not in src
    assert "do not copy human" in src


def test_f011_live_mode_refuses_monte_carlo():
    from src.frontline.shadow_pilot import run_shadow_pilot

    with pytest.raises(ValueError, match="requires --input"):
        run_shadow_pilot(mode="live", sample_size=3, out_path="")


def test_f021_csv_formula_neutralized():
    from src.frontline.ops import _csv_neutralize

    assert _csv_neutralize("=cmd|calc") == "'=cmd|calc"
    assert _csv_neutralize("@SUM(1)") == "'@SUM(1)"
    assert _csv_neutralize("normal") == "normal"


def test_f008_encrypt_roundtrip_and_shred(reset_ops_db):
    SubjectKeyStore.clear()
    iid = "int_" + new_ulid()
    token = encrypt_subject_pii(iid, "caller phone 555-0199 and a long narrative " * 3)
    assert token.startswith("enc:v1:")
    assert decrypt_subject_pii(iid, token).startswith("caller phone")
    assert SubjectKeyStore.shred_dek(iid) is True
    with pytest.raises(KeyError):
        decrypt_subject_pii(iid, token)


def test_encrypted_turns_decrypt_on_read_paths(reset_ops_db):
    from src.data.turns import ERASED_TURN, persist_turn, reveal_turn_text
    from src.data.warehouse import ops_con
    from src.frontline.dsr import export_interaction
    from src.qubot.retrievers import contact_audit

    SubjectKeyStore.clear()
    iid = "int_read_" + new_ulid()[:12]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', 't', ?, 'web_text', 'active')
            """,
            [iid, datetime.now(timezone.utc)],
        )
    persist_turn(iid, {
        "turn_id": iid + "_t1",
        "seq": 1,
        "speaker": "customer",
        "text": "My 2019 Honda CR-V grinds. Call 555-0199.",
        "ts": datetime.now(timezone.utc),
    })
    persist_turn(iid, {
        "turn_id": iid + "_t2",
        "seq": 2,
        "speaker": "agent",
        "text": "I heard grinding on the Honda.",
        "ts": datetime.now(timezone.utc),
    })
    with ops_con(read_only=True) as con:
        stored = con.execute(
            "SELECT speaker, text FROM interaction_turns WHERE interaction_id = ? ORDER BY seq",
            [iid],
        ).fetchall()
    assert stored[0][0] == "customer"
    assert str(stored[0][1]).startswith("enc:v1:")
    assert "555-0199" not in str(stored[0][1])
    assert stored[1][1] == "I heard grinding on the Honda."

    audit = contact_audit(iid)
    cust = next(t for t in audit["turns"] if t["speaker"] == "customer")
    assert cust["text"].startswith("My 2019 Honda")
    assert "enc:v1:" not in cust["text"]
    exported = export_interaction(iid)
    exp_cust = next(t for t in exported["turns"] if t["speaker"] == "customer")
    assert "555-0199" in exp_cust["text"]

    SubjectKeyStore.shred_dek(iid)
    assert reveal_turn_text(iid, stored[0][1]) == ERASED_TURN
    shredded = contact_audit(iid)
    shredded_cust = next(t for t in shredded["turns"] if t["speaker"] == "customer")
    assert shredded_cust["text"] == ERASED_TURN


@pytest.mark.asyncio
async def test_f017_simulated_case_kind(reset_ops_db, seed_automotive_pack, pack):
    from src.agents.orchestrator import Orchestrator
    from tests.frontline.conftest import _RecordingHooks

    orch = Orchestrator("int_sim_kind", pack, channel="simulated", hooks=_RecordingHooks())
    assert orch.ctx.case_kind == "simulated"


def test_f016_live_risk_score_present(reset_ops_db):
    from src.qubot.retrievers import live_risk

    rows = live_risk(window_days=7)
    assert isinstance(rows, list)
    for r in rows:
        assert "live_risk_score" in r
        assert 0.0 <= float(r["live_risk_score"]) <= 1.0


def test_f036_twiml_escapes_xml():
    from src.channels.twilio_media import TwilioMediaChannel

    xml = TwilioMediaChannel.generate_transfer_twiml(
        TwilioMediaChannel(),
        '<sip:evil>"',
        caller_id='x" y',
    )
    assert "&lt;" in xml
    assert "<sip:evil>" not in xml


def test_f008_case_description_encrypt_decrypt(reset_ops_db):
    from src.frontline.ops import get_case_row
    from src.data.warehouse import ops_con
    from src.security.pii import encrypt_subject_text

    SubjectKeyStore.clear()
    iid = "int_case_" + new_ulid()[:10]
    cid = "case_" + new_ulid()[:10]
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', 't', ?, 'web_text', 'completed')
            """,
            [iid, now],
        )
        stored = encrypt_subject_text(iid, "Caller 555-0199: brakes grind on the CR-V")
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at, category,
                description_summary, onset, severity, severity_source, priority,
                safety_flags, status
            ) VALUES (?, ?, 'automotive_nhtsa', ?, 'SERVICE BRAKES', ?, ?,
                      'Medium', 'rules', 2, '{}', 'open')
            """,
            [cid, iid, now, stored, now],
        )
    with ops_con(read_only=True) as con:
        raw = con.execute(
            "SELECT description_summary FROM cases WHERE case_id = ?", [cid]
        ).fetchone()[0]
    assert str(raw).startswith("enc:v1:")
    assert "555-0199" not in str(raw)
    row = get_case_row(cid)
    assert "555-0199" in (row or {}).get("description_summary", "")
    from src.frontline.dsr import export_interaction

    exported = export_interaction(iid)
    assert "555-0199" in (exported["cases"][0].get("description_summary") or "")


def test_f026_rebuild_does_not_alter_records():
    src = open("src/ml_runtime/clustering.py", encoding="utf-8").read()
    assert "ALTER TABLE records ADD COLUMN embedding" not in src
    wh = open("src/data/warehouse.py", encoding="utf-8").read()
    assert "ALTER TABLE records ADD COLUMN embedding FLOAT[]" in wh


def test_f048_degradation_ladder_is_wired():
    from src.observability.degradation import init_default_ladders, reset_all_ladders, step_down, all_ladders_status

    reset_all_ladders()
    init_default_ladders()
    step_down("merkle_anchor", reason="wal_fallback")
    by_name = {s["subsystem"]: s for s in all_ladders_status()}
    assert by_name["merkle_anchor"]["current_level"] >= 1


def test_f012_worker_tick_runs(reset_ops_db):
    from src.jobs.worker import worker_tick

    out = worker_tick(run_fairness=True)
    assert "job" in out
    assert "fairness" in out


def test_f015_health_summary_runs_fairness(reset_ops_db):
    from src.observability.health_checks import health_summary

    summary = health_summary()
    names = [c["name"] for c in summary["checks"]]
    assert "fairness_circuit_breaker" in names
    assert "degradation_ladders" in summary


def test_f029_dashboard_renders_trend_scope_and_simulated_opt_out():
    src = open("dashboard/routes/EarlyWarningBoard.jsx", encoding="utf-8").read()
    assert "include_simulated" in src
    assert "trend_scope" in src
    assert "Include simulated" in src


def test_empirical_unlabeled_severity_and_cluster_are_blocked():
    from src.frontline.shadow_pilot import load_empirical_cohort
    from src.eval.shadow_pilot import ShadowPilotEvaluator

    contacts = load_empirical_cohort(
        "data/safety_eval_corpus.jsonl", sample_size=20
    )
    assert all(not (c.human_severity or "").strip() for c in contacts)
    assert all(c.engineer_verified_cluster_id is None for c in contacts)
    report = ShadowPilotEvaluator(contacts).run_full_evaluation()
    assert report["metrics"]["severity_agreement"]["rating"] == "blocked"
    assert report["metrics"]["cluster_agreement"]["top_1"]["rating"] == "blocked"
    assert report["overall_verdict"] == "red"
    assert "elif human_slots.get(\"category\")" not in open(
        "src/frontline/shadow_pilot.py", encoding="utf-8"
    ).read()


def test_persist_turn_encrypt_fail_closed(reset_ops_db, monkeypatch):
    from src.data.turns import persist_turn
    from src.data.warehouse import ops_con

    iid = "int_encfail_" + new_ulid()[:8]
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', 't', ?, 'web_text', 'active')
            """,
            [iid, now],
        )

    def _boom(_sid, _text):
        raise RuntimeError("dek unavailable")

    monkeypatch.setattr("src.security.pii.encrypt_subject_pii", _boom)
    with pytest.raises(RuntimeError, match="dek unavailable"):
        persist_turn(iid, {
            "turn_id": iid + "_t1",
            "seq": 1,
            "speaker": "customer",
            "text": "My Honda CR-V grinds. Call 555-0199.",
            "ts": now,
        })
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT text FROM interaction_turns WHERE interaction_id = ?", [iid]
        ).fetchone()
    assert row is None


def test_f040_session_sig_is_full_sha256():
    from src.api.rbac import issue_session, verify_session

    tok = issue_session("u1", "agent", issuer_role="admin")
    raw, sig = tok["token"].rsplit("|", 1)
    assert len(sig) == 64
    assert verify_session(tok["token"])["sub"] == "u1"
