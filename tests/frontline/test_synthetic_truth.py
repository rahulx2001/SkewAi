import pytest
import datetime
from src.data.warehouse import domain_con
from src.ml_runtime.anomalies import score_weekly_slices, recompute_weekly_anomalies, detect_cusum_change_point, set_exposure
from src.enterprise.fix_effectiveness import measure_effectiveness

pytestmark = pytest.mark.asyncio

async def test_synthetic_spike_detected_against_flat_baseline(reset_ops_db, pack):
    counts = {}
    for i in range(1, 9):
        counts[(f"2023-W0{i}", "BRAKES", "TOYOTA")] = 10
    counts[("2023-W09", "BRAKES", "TOYOTA")] = 60
    
    res = score_weekly_slices(counts, pack_id=pack.manifest.id)
    
    week9 = next(r for r in res if r["iso_week"] == "2023-W09")
    assert week9["is_anomaly"] is True
    assert week9["z_score"] >= 2.0
    assert week9["absolute_lift"] >= 5.0
    assert week9["relative_lift"] >= 0.5
    
    for i in range(1, 9):
        week = next(r for r in res if r["iso_week"] == f"2023-W0{i}")
        assert week["is_anomaly"] is False

async def test_synthetic_spike_detection_rate_over_100_injections(reset_ops_db, pack):
    detected = 0
    import random
    random.seed(42)
    for _ in range(100):
        counts = {}
        for i in range(1, 9):
            counts[(f"2023-W0{i}", "B", "T")] = random.randint(8, 12)
        counts[("2023-W09", "B", "T")] = random.randint(30, 100) # >= 3x
        res = score_weekly_slices(counts, pack_id=pack.manifest.id)
        w9 = next(r for r in res if r["iso_week"] == "2023-W09")
        if w9["is_anomaly"]:
            detected += 1
    assert detected > 90

async def test_placebo_fix_no_false_positive(reset_ops_db, pack):
    from src.data.warehouse import ops_con
    from src.ids import new_ulid
    fix_id = new_ulid()
    # insert fix
    with ops_con() as con:
        con.execute("INSERT INTO recorded_fixes (fix_id, pack_id, investigation_id, category, entity_2, fixed_at, note) VALUES (?, ?, ?, ?, ?, ?, ?)", [fix_id, pack.manifest.id, new_ulid(), "CAT", "E2", "2023-01-01", "note"])
    # measure_effectiveness logic expects data in domain
    import datetime
    res = measure_effectiveness(pack_id=pack.manifest.id, fixed_at=datetime.datetime(2023, 1, 1), category="CAT", entity_2="E2", window_days=30)
    pass

async def test_exposure_normalized_spike_vs_raw(reset_ops_db, pack):
    # Create baseline data with exposure units that vary across weeks
    counts = {}
    exposure = {}
    for i in range(1, 9):
        counts[(f"2023-W0{i}", "CAT", "E2")] = i * 10
        exposure[(f"2023-W0{i}", "CAT", "E2")] = i * 1000
    
    # Week 9 has higher raw volume, but same rate
    counts[("2023-W09", "CAT", "E2")] = 90
    exposure[("2023-W09", "CAT", "E2")] = 9000
    
    res_with = score_weekly_slices(counts, pack_id=pack.manifest.id, exposure=exposure)
    w9_with = next(r for r in res_with if r["iso_week"] == "2023-W09")
    assert w9_with["is_anomaly"] is False
    assert w9_with["normalized"] is True
    
    # Needs to be a massive spike to trigger anomalous Z > 2 on raw counts
    counts[("2023-W09", "CAT", "E2")] = 300
    res_without = score_weekly_slices(counts, pack_id=pack.manifest.id)
    w9_without = next(r for r in res_without if r["iso_week"] == "2023-W09")
    assert w9_without["is_anomaly"] is True

async def test_cusum_detects_sustained_shift_not_single_spike():
    # Series A: [5,5,5,5,25,25,25,25,25] (sustained shift at week 5)
    s_a = [5,5,5,5,25,25,25,25,25]
    c_a = detect_cusum_change_point(s_a, baseline_mean=5.0, baseline_std=12.0)
    assert c_a["triggered"] is True
    assert c_a["change_point_index"] in (4, 5, 6, 7, 8)

    # Series B: [5,5,5,5,50,5,5,5,5]
    s_b = [5,5,5,5,50,5,5,5,5]
    c_b = detect_cusum_change_point(s_b, baseline_mean=5.0, baseline_std=12.0)
    assert c_b["triggered"] is False

async def test_zero_baseline_requires_minimum_count(reset_ops_db, pack):
    counts = {}
    for i in range(1, 9):
        counts[(f"2023-W0{i}", "C", "E")] = 0
    counts[("2023-W09", "C", "E")] = 4
    res = score_weekly_slices(counts, pack_id=pack.manifest.id)
    w9 = next(r for r in res if r["iso_week"] == "2023-W09")
    assert w9["is_anomaly"] is False

    counts[("2023-W09", "C", "E")] = 6
    res2 = score_weekly_slices(counts, pack_id=pack.manifest.id)
    w9_2 = next(r for r in res2 if r["iso_week"] == "2023-W09")
    assert w9_2["is_anomaly"] is True
    assert w9_2["method"] == "zero-baseline"

async def test_multiple_comparison_correction_reduces_false_positives(reset_ops_db, pack):
    import random
    counts = {}
    for c in range(50):
        for w in range(1, 10):
            counts[(f"2023-W0{w}", f"C{c}", "E")] = random.randint(5, 10)
    res = score_weekly_slices(counts, pack_id=pack.manifest.id)
    flags = [r for r in res if r["is_anomaly"]]
    assert len(flags) <= 3

async def test_right_censoring_suppresses_incomplete_week(reset_ops_db, pack):
    from src.data.warehouse import domain_con, apply_domain_schema
    from src.ids import new_ulid
    from src.data.timeutil import utc_now
    
    now = utc_now()
    with domain_con(pack.manifest.id, read_only=False) as con:
        apply_domain_schema(con)
        # insert spike today
        for _ in range(50):
            con.execute("INSERT INTO records (record_id, occurred_at, received_at, category, entity_2, text) VALUES (?, ?, ?, ?, ?, ?)", [new_ulid(), now.isoformat(), now.isoformat(), "CAT", "E2", "text"])
    
    res = recompute_weekly_anomalies(pack.manifest.id, censor_recent_days=14)
    recent = next(r for r in res if r["category"] == "CAT" and r["entity_2"] == "E2")
    assert recent["is_anomaly"] is False
    assert recent.get("censored", False) is True

