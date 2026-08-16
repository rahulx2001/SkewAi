"""Money, regulatory, supplier, outreach/memory, RCA/analytics gating tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.enterprise.hypothesis_rca import (
    adversarial_score,
    list_thumbs,
    record_thumbs,
    run_hypothesis_rca,
    weekly_exec_briefing,
)
from src.frontline.analytics import (
    forecast_cluster_volume,
    geographic_hotspots,
    project_next_week_volume,
    seasonality_climate,
)
from src.frontline.copq import (
    cluster_copq,
    failure_rate_per_1000,
    rank_by_dollar,
    roi_attribution,
    save_cluster_cost,
    warranty_reserve,
)
from src.frontline.fmea import record_failure_mode, suggest_seen_before
from src.frontline.outreach import (
    customer_case_update,
    notify_affected_owners,
    product_line_health,
    register_owner,
)
from src.frontline.regulatory import (
    clock_status,
    draft_field_safety_notice,
    draft_filing,
    fire_clock_alert,
    recall_decision,
)
from src.frontline.supplier import (
    attach_supply,
    lot_trace,
    open_supplier_capa,
    respond_supplier_capa,
    supplier_scorecards,
)
from src.qubot.retrievers import live_risk_by_dollar


def _case(case_id: str, pack_id: str, *, status="open", severity="Medium", category="SERVICE BRAKES", iid="int_econ"):
    with ops_con() as con:
        exists = con.execute(
            "SELECT 1 FROM interactions WHERE interaction_id = ?", [iid]
        ).fetchone()
        if not exists:
            con.execute(
                """
                INSERT INTO interactions
                (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
                VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
                """,
                [iid, pack_id, utc_now()],
            )
        con.execute(
            """
            INSERT INTO cases
            (case_id, interaction_id, pack_id, created_at, category, description_summary,
             onset, severity, severity_source, priority, safety_flags, similar_record_count, status)
            VALUES (?, ?, ?, ?, ?, 'econ', ?, ?, 'rules', 3, '{}', 0, ?)
            """,
            [case_id, iid, pack_id, utc_now(), category, utc_now(), severity, status],
        )


def test_money_layer_copq_rank_roi_reserve_rate(reset_ops_db, pack):
    issues = [
        {"warranty_per_claim": 400.0, "labor_per_claim": 100.0, "recall_cost": 0.0, "claim_count": 10},
        {"warranty_per_claim": 200.0, "labor_per_claim": 50.0, "recall_cost": 1000.0, "claim_count": 2},
    ]
    scored = cluster_copq(issues, projected_extra_claims=5)
    assert scored["total"] == 10 * 500 + 2 * 250 + 1000
    assert scored["projected_total"] > scored["total"]
    assert scored["total"] != 10_000_000

    save_cluster_cost(
        pack_id=pack.id,
        cluster_id=7,
        warranty_per_claim=800,
        labor_per_claim=200,
        claim_count=3,
    )
    save_cluster_cost(
        pack_id=pack.id,
        cluster_id=8,
        warranty_per_claim=10,
        labor_per_claim=0,
        claim_count=80,
    )
    ranked = live_risk_by_dollar()
    dollars = {int(r["cluster_id"]): r["dollar_impact"] for r in ranked}
    assert dollars[7] > dollars[8]
    assert ranked[0]["cluster_id"] == 7

    slices = rank_by_dollar(
        [
            {"cluster_id": "high_vol", "live_case_count": 80, "dollar_impact": 800},
            {"cluster_id": "high_dollar", "live_case_count": 3, "dollar_impact": 3000},
        ]
    )
    assert slices[0]["cluster_id"] == "high_dollar"

    roi = roi_attribution(issues_caught=4, copq_per_issue=2500, lead_time_weeks=6)
    assert roi["issues_caught"] == 4
    assert roi["dollars_avoided"] == 10000
    assert "4" in roi["headline"] and "10000" in roi["headline"].replace(",", "")

    reserve = warranty_reserve([10, 12, 15, 18], cost_per_claim=400, weeks_ahead=8)
    assert reserve["projected_reserve"] > 0
    assert reserve["ci_low"] <= reserve["projected_reserve"] <= reserve["ci_high"]

    rate = failure_rate_per_1000(failures=5, units_in_service=2000)
    assert rate["rate_per_1000"] == 2.5
    with pytest.raises(ValueError):
        failure_rate_per_1000(5, 0)


def test_regulatory_recall_filings_clock_fsn(reset_ops_db, pack):
    quiet = recall_decision(
        cluster_id=1,
        live_count=2,
        historical_threshold=10,
        evidence_ids=["NHTSA-100001"],
        pack_id=pack.id,
    )
    assert quiet["grounded"] is False
    assert quiet["evidence_bundle"] is None
    hit = recall_decision(
        cluster_id=2,
        live_count=12,
        historical_threshold=10,
        evidence_ids=["NHTSA-100001"],
        pack_id=pack.id,
    )
    assert hit["grounded"] is True
    assert hit["evidence_bundle"]

    case = {"case_id": "case_econ_1", "category": "SERVICE BRAKES", "severity": "Critical"}
    for kind, form in (("ewr", "NHTSA EWR"), ("mdr", "FDA MDR"), ("15b", "CPSC 15(b)")):
        d = draft_filing(kind, case=case, evidence_ids=["NHTSA-100001"])
        assert form in d["form"]
        assert d["case_id"] == "case_econ_1"
        assert "NHTSA-100001" in d["evidence_ids"]

    opened = utc_now() - timedelta(days=6)
    assert clock_status(opened, days=5)["overdue"] is True
    alert = fire_clock_alert(ref_id="clk_1", opened_at=opened, days=5)
    assert alert["fired"] is True

    text = "grinding noise when braking"
    snaps = [{"evidence_id": "NHTSA-100001", "body_json": {"text": text, "record_id": "NHTSA-100001"}}]
    start = text.index("grinding noise")
    fsn = draft_field_safety_notice(
        [
            {"claim_text": "grinding noise", "evidence_id": "NHTSA-100001", "span_start": start, "span_end": start + 14},
            {"claim_text": "engine fire", "evidence_id": "NHTSA-100001", "span_start": start, "span_end": start + 11},
        ],
        snaps,
    )
    assert any(c["claim_text"] == "grinding noise" for c in fsn["claims"])
    assert "engine fire" in fsn["withheld"]
    assert "engine fire" not in fsn["notice"]


def test_supplier_scorecard_lot_capa(reset_ops_db, pack):
    attach_supply(record_id="R-bad-1", pack_id=pack.id, supplier="AcmeBrakes", lot_id="L-9", lot_start="2026-01-01", lot_end="2026-01-31")
    attach_supply(record_id="R-bad-2", pack_id=pack.id, supplier="AcmeBrakes", lot_id="L-9", lot_start="2026-01-01", lot_end="2026-01-31")
    attach_supply(record_id="R-ok", pack_id=pack.id, supplier="CleanCo", lot_id="L-1", lot_start="2026-02-01", lot_end="2026-02-28")
    cards = supplier_scorecards(pack.id)
    assert cards[0]["supplier"] == "AcmeBrakes"
    assert cards[0]["failures"] > cards[-1]["failures"]
    tr = lot_trace("R-bad-1")
    assert tr["lot_id"] == "L-9"
    assert tr["lot_start"] and tr["lot_end"]
    capa = open_supplier_capa(supplier="AcmeBrakes", pack_id=pack.id, request="contain lot L-9", lot_id="L-9")
    assert capa["status"] == "open"
    done = respond_supplier_capa(capa["capa_id"], "sorted and replaced lot")
    assert done["status"] == "responded"
    assert done["response"]


def test_outreach_memory_verified_fix(reset_ops_db, pack):
    owner_a = register_owner(
        pack_id=pack.id, entity_2="HONDA", entity_3="CR-V", cluster_id=3,
        channel="phone", address="+15550001",
    )
    owner_b = register_owner(
        pack_id=pack.id, entity_2="HONDA", entity_3="CR-V", cluster_id=9,
        channel="sms", address="+15550009",
    )
    note = notify_affected_owners(pack_id=pack.id, cluster_id=3, entity_2="HONDA")
    assert note["count"] == 1
    assert note["selected"][0]["owner_id"] == owner_a["owner_id"]
    assert note["before_inbound_call"] is True
    other = notify_affected_owners(pack_id=pack.id, cluster_id=9, entity_2="HONDA")
    assert other["count"] == 1
    assert other["selected"][0]["owner_id"] == owner_b["owner_id"]
    none = notify_affected_owners(pack_id=pack.id, cluster_id=7, entity_2="HONDA")
    assert none["count"] == 0

    _case("case_status_demo_x", pack.id, status="open", iid="int_stat_x")
    upd = customer_case_update("case_status_demo_x")
    assert upd["status"] == "open"
    assert "case_status_demo_x" in upd["customer_text"]

    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls,
             entity_3, category, peak_frustration)
            VALUES ('int_health', ?, 'v', ?, 'web_text', 'completed', FALSE, 0, 'CR-V', 'SERVICE BRAKES', 0.2)
            """,
            [pack.id, utc_now()],
        )
    health = product_line_health(pack_id=pack.id, entity_3="CR-V", category="SERVICE BRAKES")
    assert health["tied_to_quality"] is True
    assert 0 <= health["csat_proxy"] <= 1

    record_failure_mode(
        pack_id=pack.id,
        investigation_id="inv_ok",
        category="SERVICE BRAKES",
        title="caliper slide pin",
        entity_2="HONDA",
        verified_effective=True,
    )
    record_failure_mode(
        pack_id=pack.id,
        investigation_id="inv_no",
        category="SERVICE BRAKES",
        title="pad slap guess",
        entity_2="FORD",
        verified_effective=False,
    )
    seen = suggest_seen_before(pack_id=pack.id, category="SERVICE BRAKES", entity_2="HONDA")
    assert seen["suggested"]
    assert all(s["verified_effective"] for s in seen["suggested"])
    assert any(not s["verified_effective"] for s in seen["non_effective_siblings"])


def test_rca_analytics_map_season_ci_thumbs(reset_ops_db, pack):
    text = "caliper seized after rain"
    snaps = [{"evidence_id": "NHTSA-100001", "body_json": {"text": text}}]
    start = text.index("caliper seized")
    rca = run_hypothesis_rca(
        [
            {
                "id": "h1",
                "text": "slide pin corrosion",
                "claims": [
                    {
                        "claim_text": "caliper seized",
                        "evidence_id": "NHTSA-100001",
                        "span_start": start,
                        "span_end": start + 14,
                    }
                ],
            },
            {
                "id": "h2",
                "text": "software glitch",
                "claims": [
                    {
                        "claim_text": "ecu crash loop",
                        "evidence_id": "NHTSA-100001",
                        "span_start": 0,
                        "span_end": 8,
                    }
                ],
            },
        ],
        snaps,
    )
    assert any(h["id"] == "h1" for h in rca["shown"])
    assert any(h["id"] == "h2" for h in rca["withheld"])

    pair = adversarial_score(
        {"id": "left", "claims": rca["shown"][0] and [
            {"claim_text": "caliper seized", "evidence_id": "NHTSA-100001", "span_start": start, "span_end": start + 14}
        ]},
        {"id": "right", "claims": [
            {"claim_text": "ecu crash", "evidence_id": "NHTSA-100001", "span_start": 0, "span_end": 9}
        ]},
        snaps,
    )
    assert pair["winner"] == "left"

    brief = weekly_exec_briefing(pack_id=pack.id)
    assert brief["grounded"] is True
    assert brief["body"]

    with ops_con() as con:
        try:
            con.execute("ALTER TABLE interactions ADD COLUMN region VARCHAR")
        except Exception:
            pass
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES ('int_map', ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
            """,
            [pack.id, utc_now()],
        )
        try:
            con.execute("UPDATE interactions SET region = 'CA' WHERE interaction_id = 'int_map'")
        except Exception:
            pass
    geo = geographic_hotspots(pack_id=pack.id)
    assert "geojson" in geo
    assert geo["geojson"]["type"] == "FeatureCollection"

    season = seasonality_climate(
        [
            {"region": "MI", "temperature_c": -5},
            {"region": "TX", "temperature_c": 34},
            {"region": "CA", "temperature_c": 18},
        ]
    )
    assert season["temperature_bands"]["cold"] == 1
    assert season["temperature_bands"]["hot"] == 1

    # Two weeks of cases so forecast has a slope + interval
    now = utc_now()
    _case("case_fc1", pack.id, iid="int_fc")
    _case("case_fc2", pack.id, iid="int_fc")
    with ops_con() as con:
        con.execute(
            "UPDATE cases SET cluster_match_id = 4, created_at = ? WHERE case_id = 'case_fc1'",
            [now - timedelta(days=14)],
        )
        con.execute("UPDATE cases SET cluster_match_id = 4 WHERE case_id = 'case_fc2'")
    fc = forecast_cluster_volume(pack_id=pack.id, window_days=28)
    assert fc["forecasts"]
    row = fc["forecasts"][0]
    assert "ci_low" in row and "ci_high" in row
    assert row["ci_low"] <= row["ci_high"]

    # Declining series must clamp the point at 0 and keep ci_low <= ci_high.
    declining = project_next_week_volume([10, 1])
    assert declining["projected_next_week"] == 0.0
    assert declining["ci_low"] <= declining["ci_high"]
    assert declining["ci_low"] >= 0.0
    assert declining["ci_high"] >= 0.0
    now = utc_now()
    for i in range(10):
        _case(f"case_dec_old_{i}", pack.id, iid="int_dec")
    _case("case_dec_new", pack.id, iid="int_dec")
    with ops_con() as con:
        con.execute(
            "UPDATE cases SET cluster_match_id = 55, created_at = ? WHERE case_id LIKE 'case_dec_old_%'",
            [now - timedelta(days=21)],
        )
        con.execute(
            "UPDATE cases SET cluster_match_id = 55, created_at = ? WHERE case_id = 'case_dec_new'",
            [now],
        )
    dec = forecast_cluster_volume(pack_id=pack.id, window_days=28)
    dec_row = next(r for r in dec["forecasts"] if int(r["cluster_id"]) == 55)
    assert dec_row["weekly_counts"][0] > dec_row["weekly_counts"][-1]
    assert dec_row["projected_next_week"] == 0
    assert dec_row["ci_low"] <= dec_row["ci_high"]
    assert dec_row["ci_low"] >= 0

    fb = record_thumbs(suggestion_id="sug_1", up=False, note="wrong fix")
    assert fb["stored"] is True
    assert fb["thumbs_up"] is False
    stored = list_thumbs("sug_1")
    assert stored and stored[0]["thumbs_up"] is False

    assert Path("dashboard/routes/QualityEconomics.jsx").is_file()
    app = Path("dashboard/src/App.jsx").read_text(encoding="utf-8")
    assert "QualityEconomics" in app
    assert 'id: "economics"' in app
