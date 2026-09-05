"""Tests for the self-diagnosing health check infrastructure.

Every health check must:
1. Return a HealthSignal with name, status, metric_value, threshold
2. Never crash (catch exceptions internally)
3. Detect degradation BEFORE customers notice
"""

import pytest
from src.observability.health_checks import (
    check_ledger_health,
    check_ops_db_writable,
    check_dead_letter_backlog,
    check_crypto_key_store_size,
    run_all_checks,
    health_summary,
    check_novel_candidate_backlog,
    check_anomaly_freshness
)
from src.data.warehouse import ops_con, domain_con
from src.data.timeutil import utc_now
from src.ids import new_ulid

def test_ledger_health_reports_healthy_baseline(reset_ops_db):
    from src.ledger.writer import reset_ledger_health
    reset_ledger_health()
    res = check_ledger_health()
    assert res.status == "healthy"

def test_ops_db_writable_succeeds(reset_ops_db):
    res = check_ops_db_writable()
    assert res.status == "healthy"

def test_dead_letter_healthy_when_empty(reset_ops_db):
    res = check_dead_letter_backlog()
    assert res.status == "healthy"

def test_crypto_store_healthy_when_small():
    res = check_crypto_key_store_size()
    assert res.status == "healthy"

def test_run_all_checks_never_crashes(reset_ops_db):
    res = run_all_checks()
    assert isinstance(res, list)
    assert len(res) > 0
    for r in res:
        assert r.name
        assert r.status in ("healthy", "degraded", "critical")

def test_health_summary_structure(reset_ops_db):
    summary = health_summary()
    assert "overall" in summary
    assert "checks" in summary
    assert isinstance(summary["checks"], list)

def test_novel_candidate_backlog_degrades_with_many(reset_ops_db):
    with ops_con() as con:
        for i in range(200):
            con.execute(
                "INSERT INTO novel_candidates (novel_id, interaction_id, pack_id, category, entity_2, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"nov_{i}", f"inter_{i}", "pack_1", "cat1", "ent2", "open", utc_now().isoformat())
            )
            
    res = check_novel_candidate_backlog(max_open=100)
    assert res.status == "degraded"

def test_anomaly_freshness_healthy_with_recent_scan(pack):
    now = utc_now()
    y, w, _ = now.isocalendar()
    iso_week = f"{y}-W{w:02d}"
    
    with domain_con(pack.id, read_only=False) as con:
        con.execute("CREATE TABLE IF NOT EXISTS records (record_id TEXT PRIMARY KEY, received_at TEXT, text TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS weekly_anomalies (pack_id TEXT, iso_week TEXT, category TEXT, entity_2 TEXT, record_count INTEGER)")
        
        con.execute("INSERT INTO records (record_id, received_at, text) VALUES (?, ?, ?)", ("r1", now.isoformat(), "test"))
        con.execute("INSERT INTO weekly_anomalies (pack_id, iso_week, category, entity_2, record_count) VALUES (?, ?, ?, ?, ?)",
                    (pack.id, iso_week, "test", "test", 10))
    
    res = check_anomaly_freshness(pack.id, max_age_hours=48)
    assert res.status == "healthy", f"Failed with detail: {res.detail}"
