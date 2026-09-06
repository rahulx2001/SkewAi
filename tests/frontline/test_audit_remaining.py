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


def test_f040_session_sig_is_full_sha256():
    from src.api.rbac import issue_session, verify_session

    tok = issue_session("u1", "agent", issuer_role="admin")
    raw, sig = tok["token"].rsplit("|", 1)
    assert len(sig) == 64
    assert verify_session(tok["token"])["sub"] == "u1"
