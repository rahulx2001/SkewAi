"""Phase-1 analytical core: anomalies, association, investigation workspace,
fix-effectiveness, multi-key entity resolution.

Each test calls the shipped function — no reimplementation, no seed 6.0/2.0/0.0.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.data.timeutil import utc_now
from src.data.warehouse import apply_domain_schema, domain_con, ops_con
from src.enterprise.fix_effectiveness import measure_effectiveness, record_fix
from src.enterprise.investigation_workspace import (
    add_hypothesis,
    get_investigation,
    update_investigation,
)
from src.ml_runtime.anomalies import recompute_weekly_anomalies
from src.ml_runtime.association import rank_by_association
from src.ml_runtime.entity_resolution import resolve_matches, same_entity


def _monday(year: int, week: int) -> datetime:
    return datetime.fromisocalendar(year, week, 1)


def test_recompute_weekly_anomalies_marks_spike_not_quiet(tmp_path, monkeypatch):
    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack = "automotive_nhtsa"
    quiet_weeks = [10, 11, 12, 13]
    spike_week = 14
    with domain_con(pack, read_only=False) as con:
        apply_domain_schema(con)
        n = 0
        for w in quiet_weeks:
            for i in range(2):
                n += 1
                con.execute(
                    """
                    INSERT INTO records (
                        record_id, received_at, entity_1, entity_2, entity_3,
                        category, text, source
                    ) VALUES (?, ?, '2019', 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')
                    """,
                    [f"Q-{w}-{i}", _monday(2024, w), f"quiet {w} {i}"],
                )
        for i in range(20):
            n += 1
            con.execute(
                """
                INSERT INTO records (
                    record_id, received_at, entity_1, entity_2, entity_3,
                    category, text, source
                ) VALUES (?, ?, '2019', 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')
                """,
                [f"S-{i}", _monday(2024, spike_week), f"spike {i}"],
            )
        # Quiet other slice: FORD electrical, 2 per week including spike week
        for w in quiet_weeks + [spike_week]:
            for i in range(2):
                n += 1
                con.execute(
                    """
                    INSERT INTO records (
                        record_id, received_at, entity_1, entity_2, entity_3,
                        category, text, source
                    ) VALUES (?, ?, '2019', 'FORD', 'F-150', 'ELECTRICAL SYSTEM', ?, 'NHTSA')
                    """,
                    [f"E-{w}-{i}", _monday(2024, w), f"elec {w} {i}"],
                )

    scored = recompute_weekly_anomalies(pack)
    by_key = {(r["iso_week"], r["category"], r["entity_2"]): r for r in scored}
    spike = by_key[("2024-W14", "SERVICE BRAKES", "HONDA")]
    quiet = by_key[("2024-W10", "SERVICE BRAKES", "HONDA")]
    other = by_key[("2024-W14", "ELECTRICAL SYSTEM", "FORD")]

    assert spike["record_count"] == 20
    assert spike["z_score"] != 6.0
    assert spike["z_score"] >= 2.0
    assert spike["is_anomaly"] is True
    assert quiet["is_anomaly"] is False
    assert other["is_anomaly"] is False

    with domain_con(pack) as con:
        stored = con.execute(
            """
            SELECT z_score, is_anomaly, record_count FROM weekly_anomalies
            WHERE pack_id = ? AND iso_week = ? AND category = ? AND entity_2 = ?
            """,
            [pack, "2024-W14", "SERVICE BRAKES", "HONDA"],
        ).fetchone()
    assert stored is not None
    assert stored[0] == spike["z_score"]
    assert bool(stored[1]) is True
    assert stored[2] == 20


def test_association_ranks_cooccurrence_above_recent_distractor():
    query = {
        "record_id": "Q",
        "category": "SERVICE BRAKES",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "received_at": datetime(2024, 6, 1),
    }
    sibling = {
        "record_id": "SIB",
        "category": "SERVICE BRAKES",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "received_at": datetime(2024, 1, 1),
    }
    distractor = {
        "record_id": "NEW",
        "category": "ELECTRICAL SYSTEM",
        "entity_2": "FORD",
        "entity_3": "F-150",
        "received_at": datetime(2024, 6, 15),
    }
    extra = {
        "record_id": "E2",
        "category": "SERVICE BRAKES",
        "entity_2": "HONDA",
        "entity_3": "ACCORD",
        "received_at": datetime(2024, 2, 1),
    }
    pop = [query, sibling, distractor, extra]
    ranked = rank_by_association(query, [sibling, distractor], pop, top_k=5)
    assert ranked[0]["record_id"] == "SIB"
    assert ranked[0]["assoc_score"] > ranked[-1]["assoc_score"]
    ids = [r["record_id"] for r in ranked]
    assert ids.index("SIB") < ids.index("NEW")


def test_investigation_assignee_sla_hypothesis_roundtrip(reset_ops_db):
    now = utc_now()
    due = now + timedelta(days=7)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO investigations
            (investigation_id, pack_id, cluster_id, title, status, opened_at, case_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ["inv_ws_1", "automotive_nhtsa", 14, "brake grind", "open", now, 3],
        )
    update_investigation("inv_ws_1", assignee="jordan@ops", sla_due_at=due)
    add_hypothesis("inv_ws_1", "Pad wear on 2019 CR-V after wet roads", status="open")
    got = get_investigation("inv_ws_1")
    assert got["investigation_id"] == "inv_ws_1"
    assert got["assignee"] == "jordan@ops"
    assert got["sla_due_at"] is not None
    assert "T" in str(got["sla_due_at"])
    assert len(got["hypotheses"]) == 1
    assert got["hypotheses"][0]["body"] == "Pad wear on 2019 CR-V after wet roads"
    assert got["hypotheses"][0]["status"] == "open"
    again = get_investigation("inv_ws_1")
    assert again["assignee"] == "jordan@ops"
    assert again["hypotheses"][0]["status"] == "open"


def test_fix_effectiveness_after_quieter_than_before(tmp_path, monkeypatch):
    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack = "automotive_nhtsa"
    pivot = datetime(2024, 6, 15)
    with domain_con(pack, read_only=False) as con:
        apply_domain_schema(con)
        for i in range(10):
            con.execute(
                """
                INSERT INTO records (
                    record_id, received_at, entity_2, entity_3, category, text, source
                ) VALUES (?, ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')
                """,
                [f"B-{i}", pivot - timedelta(days=20 - i), f"before {i}"],
            )
        for i in range(2):
            con.execute(
                """
                INSERT INTO records (
                    record_id, received_at, entity_2, entity_3, category, text, source
                ) VALUES (?, ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')
                """,
                [f"A-{i}", pivot + timedelta(days=5 + i), f"after {i}"],
            )
    recorded = record_fix(
        pack_id=pack,
        fixed_at=pivot,
        category="SERVICE BRAKES",
        entity_2="HONDA",
        entity_3="CR-V",
        note="pad campaign",
    )
    assert recorded["fix_id"].startswith("fix_")
    measured = measure_effectiveness(
        pack_id=pack,
        fixed_at=pivot,
        category="SERVICE BRAKES",
        entity_2="HONDA",
        entity_3="CR-V",
        window_days=60,
    )
    assert measured["before_count"] == 10
    assert measured["after_count"] == 2
    assert measured["before_rate"] == 10 / 60
    assert measured["after_rate"] == 2 / 60
    assert measured["after_rate"] < measured["before_rate"]
    assert measured["conclusive"] is True
    assert measured["improved"] is True


def test_entity_resolution_vin_make_model_not_make_only():
    a = {"vin": "1HGCM82633A004352", "entity_2": "HONDA", "entity_3": "ACCORD"}
    b = {"vin": "1hgcm82633a004352", "entity_2": "honda", "entity_3": "accord"}
    c = {"vin": "1HGCM82633A004352", "entity_2": "TOYOTA", "entity_3": "CAMRY"}
    d = {"vin": "", "entity_2": "HONDA", "entity_3": "ACCORD"}
    e = {"serial": "SN-99", "entity_2": "HONDA", "entity_3": "CR-V"}
    f = {"serial": "SN-99", "entity_2": "HONDA", "entity_3": "CR-V"}
    assert same_entity(a, b) is True
    assert same_entity(a, c) is False
    assert same_entity(a, d) is False
    assert same_entity(d, a) is False
    assert same_entity(e, f) is True
    recs = [a, b, c, d]
    pairs = resolve_matches(recs)
    assert (0, 1) in pairs
    assert (0, 2) not in pairs
    assert (0, 3) not in pairs
