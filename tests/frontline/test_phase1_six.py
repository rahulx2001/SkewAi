"""Phase 1 six: hash-chain, LLM fallback, semantic, backtest, builder, scale ingest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.warehouse import ops_con
from src.ledger import AgentAction, list_actions, record_action
from src.ledger.chain import verify_chain


def test_hash_chain_verifies_and_detects_tamper(reset_ops_db):
    iid = "int_chain_1"
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="state_transition",
            input_summary="a",
            output_summary="b",
        )
    )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="greeting_emitted",
            input_summary="g",
            output_summary="hello",
        )
    )
    rows = list_actions(iid)
    assert len(rows) >= 2
    assert all(r.get("row_hash") for r in rows)
    assert verify_chain(rows)["ok"] is True

    # Tamper output_summary in memory → recompute fails
    bad = [dict(r) for r in rows]
    bad[1]["output_summary"] = "TAMPERED"
    # Keep stored row_hash so verify sees mismatch
    assert verify_chain(bad)["ok"] is False


def test_llm_narration_falls_back_without_enable(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_LLM_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from src.ai.narration import phrase_investigation_brief

    res = phrase_investigation_brief(
        similar_count=3,
        cluster_id=14,
        lead_time_weeks=11,
        keyword="grind",
        evidence_ids=["NHTSA-1"],
    )
    assert res.used_llm is False
    assert res.ok is False
    assert "3" in res.text or "similar" in res.text.lower()
    assert res.model_id == "deterministic"


def test_semantic_rank_prefers_related_text():
    from src.ml_runtime.embeddings import rank_by_similarity

    cands = [
        {"record_id": "a", "text": "grinding noise when braking at low speed"},
        {"record_id": "b", "text": "airbag warning light on dashboard"},
        {"record_id": "c", "text": "power window regulator failure"},
    ]
    ranked = rank_by_similarity("my brakes grind when I stop", cands, top_k=3)
    assert ranked[0]["record_id"] == "a"
    assert ranked[0]["sim_score"] >= ranked[-1]["sim_score"]


def test_backtest_engine_writes_computed_lead_times(seed_automotive_pack):
    from src.backtest.engine import best_lead_time, run_backtest

    rows = run_backtest("automotive_nhtsa")
    assert rows, "expected computed backtest rows"
    assert all("lead_time_weeks" in r for r in rows)
    # At least one matched path with positive lead for fixture clusters
    matched = [r for r in rows if r.get("matched")]
    assert matched, f"expected matched advisory/cluster pairs, got {rows!r}"
    best = best_lead_time("automotive_nhtsa")
    assert best is not None
    assert best["lead_time_weeks"] is not None
    # Persisted in domain DB
    from src.data.warehouse import domain_con

    with domain_con("automotive_nhtsa") as con:
        n = con.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
    assert n >= 1


def test_pack_builder_mvp(tmp_path):
    from src.domains.builder.pack_builder import build_draft_pack, profile_csv

    csv_path = tmp_path / "tickets.csv"
    csv_path.write_text(
        "id,make,model,issue,description\n"
        "1,Honda,CR-V,brakes,grinding when braking\n"
        "2,Toyota,Camry,airbags,warning light on\n",
        encoding="utf-8",
    )
    prof = profile_csv(csv_path)
    assert "text" in prof["proposed_mapping"] or "description" in prof["columns"]
    out = build_draft_pack(
        pack_id="demo_builder_pack",
        display_name="Demo Builder",
        csv_path=csv_path,
        mapping={
            "text": "description",
            "entity_2": "make",
            "entity_3": "model",
            "category": "issue",
            "record_id": "id",
        },
        out_root=tmp_path / "domains",
    )
    pack_dir = Path(out["pack_dir"])
    assert (pack_dir / "pack.yaml").exists()
    assert "builder_mvp: true" in (pack_dir / "pack.yaml").read_text(encoding="utf-8")
    assert out["sample_records"] >= 2


def test_scale_ingest_small(tmp_path, monkeypatch):
    """Scaled ingest writes embeddings + re-runs backtest (n=25 for speed)."""
    import src.config as cfg
    from scripts.ingest_scale import build_scaled

    class _S:
        def domain_db_path(self, pack_id):
            return tmp_path / f"{pack_id}.duckdb"

    monkeypatch.setattr(cfg, "settings", _S())
    # warehouse also imports settings
    import src.data.warehouse as wh

    monkeypatch.setattr(wh, "settings", _S())
    path = build_scaled("automotive_nhtsa", 25)
    assert path.exists()
    from src.data.warehouse import domain_con

    with domain_con("automotive_nhtsa") as con:
        n = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        emb = con.execute(
            "SELECT embedding FROM records WHERE embedding IS NOT NULL LIMIT 1"
        ).fetchone()
        bt = con.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
    assert n == 25
    assert emb is not None
    assert bt >= 1


def test_pii_redaction():
    from src.security.pii import find_pii, redact_pii

    t = "Call me at 555-123-4567 or a@b.com"
    assert "email" in find_pii(t) or "phone" in find_pii(t)
    red = redact_pii(t)
    assert "555-123-4567" not in red
    assert "@" not in red or "[EMAIL]" in red


def test_consent_preamble_on_greeting(monkeypatch):
    from src.frontline.consent import with_consent

    monkeypatch.setenv("FRONTLINE_CONSENT_DISCLOSURE", "1")
    # Re-import logic reads env at call time
    g = with_consent("Hello.")
    assert "consent" in g.lower() or "recorded" in g.lower() or "monitored" in g.lower()
    monkeypatch.setenv("FRONTLINE_CONSENT_DISCLOSURE", "0")
    assert with_consent("Hello.") == "Hello."


def test_severity_json_registry():
    from src.ml_runtime.registry import predict_severity

    sev, reason = predict_severity(
        "domains/automotive_nhtsa/models/severity_rules.json",
        {"description": "grinding brakes", "category": "SERVICE BRAKES", "safety_flags": {}},
    )
    assert sev == "Medium"
    assert "json_rule" in reason
    # No keyword → raises so triage can use pack YAML rules
    import pytest

    with pytest.raises(LookupError):
        predict_severity(
            "domains/automotive_nhtsa/models/severity_rules.json",
            {"description": "paint chipping", "category": "STRUCTURE", "safety_flags": {}},
        )
