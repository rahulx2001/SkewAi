"""Tests for Phase 1 Controlled Live Pilot (5% Traffic Split & Circuit Breakers)."""

from __future__ import annotations

import datetime
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.routing.circuit_breaker import LivePilotCircuitBreaker, get_circuit_breaker, set_circuit_breaker
from src.routing.traffic_gate import Phase1TrafficGate, get_traffic_gate, set_traffic_gate


@pytest.fixture(autouse=True)
def reset_phase1_routing():
    """Ensure clean traffic gate and circuit breaker state before each test."""
    gate = Phase1TrafficGate(
        target_ratio=0.05,
        daily_max_calls=50,
        start_hour_utc=0,  # default 24h open for test hermeticity
        end_hour_utc=24,
        allowed_domain="automotive_nhtsa",
    )
    breaker = LivePilotCircuitBreaker(latency_ceiling_ms=1000.0, max_consecutive_fp=3)
    set_traffic_gate(gate)
    set_circuit_breaker(breaker)
    yield gate, breaker
    set_traffic_gate(None)
    set_circuit_breaker(None)


def test_traffic_gate_ingress_and_daily_counter():
    gate = Phase1TrafficGate(target_ratio=0.05, daily_max_calls=50, start_hour_utc=0, end_hour_utc=24)
    now = datetime.datetime(2026, 9, 5, 14, 0, tzinfo=datetime.timezone.utc)

    # Hash 3 % 100 = 3 < 5 -> Selected
    admitted, reason = gate.evaluate_ingress(call_hash=3, now=now, domain="automotive_nhtsa")
    assert admitted is True
    assert reason == "admitted_to_pilot"
    assert gate.daily_routed_count == 1

    # Hash 4 % 100 = 4 < 5 -> Selected
    admitted, reason = gate.evaluate_ingress(call_hash=4, now=now, domain="automotive_nhtsa")
    assert admitted is True
    assert gate.daily_routed_count == 2

    # Hash 15 % 100 = 15 >= 5 -> Routed to human control
    admitted, reason = gate.evaluate_ingress(call_hash=15, now=now, domain="automotive_nhtsa")
    assert admitted is False
    assert reason == "routed_to_human_control"
    assert gate.daily_routed_count == 2  # Not incremented


def test_traffic_gate_daily_volume_ceiling():
    gate = Phase1TrafficGate(target_ratio=0.05, daily_max_calls=3, start_hour_utc=0, end_hour_utc=24)
    now = datetime.datetime(2026, 9, 5, 14, 0, tzinfo=datetime.timezone.utc)

    # Admit 3 calls
    for _ in range(3):
        admitted, reason = gate.evaluate_ingress(call_hash=1, now=now, domain="automotive_nhtsa")
        assert admitted is True

    assert gate.daily_routed_count == 3

    # 4th call should hit daily volume ceiling
    admitted, reason = gate.evaluate_ingress(call_hash=1, now=now, domain="automotive_nhtsa")
    assert admitted is False
    assert reason == "daily_volume_ceiling_reached"
    assert gate.daily_routed_count == 3


def test_traffic_gate_operating_window():
    gate = Phase1TrafficGate(
        target_ratio=0.05,
        daily_max_calls=50,
        start_hour_utc=13,  # 09:00 ET
        end_hour_utc=21,    # 17:00 ET
    )
    # Outside hours (10:00 UTC)
    outside_now = datetime.datetime(2026, 9, 5, 10, 0, tzinfo=datetime.timezone.utc)
    admitted, reason = gate.evaluate_ingress(call_hash=1, now=outside_now, domain="automotive_nhtsa")
    assert admitted is False
    assert reason == "outside_operating_hours"

    # Inside hours (14:00 UTC)
    inside_now = datetime.datetime(2026, 9, 5, 14, 0, tzinfo=datetime.timezone.utc)
    admitted, reason = gate.evaluate_ingress(call_hash=1, now=inside_now, domain="automotive_nhtsa")
    assert admitted is True
    assert reason == "admitted_to_pilot"


def test_traffic_gate_scope_lock():
    gate = Phase1TrafficGate(target_ratio=0.05, allowed_domain="automotive_nhtsa")
    now = datetime.datetime(2026, 9, 5, 14, 0, tzinfo=datetime.timezone.utc)

    # Out-of-scope domain (e.g. consumer_cpsc or billing)
    admitted, reason = gate.evaluate_ingress(call_hash=1, now=now, domain="finance_cfpb")
    assert admitted is False
    assert "out_of_scope_domain" in reason


def test_circuit_breaker_latency_spike():
    breaker = LivePilotCircuitBreaker(latency_ceiling_ms=1000.0)

    # 9 calls with high latency (1200ms)
    for _ in range(9):
        breaker.record_turn_latency(1200.0)
        assert breaker.is_tripped is False

    # 10th call completes rolling window -> average 1200ms > 1000ms -> TRIPS
    breaker.record_turn_latency(1200.0)
    assert breaker.is_tripped is True
    assert "breached ceiling" in breaker.trip_reason


def test_circuit_breaker_missed_safety_immediate_trip():
    breaker = LivePilotCircuitBreaker()
    breaker.record_safety_evaluation(missed_safety=True)
    assert breaker.is_tripped is True
    assert "Missed Safety Escaped" in breaker.trip_reason


def test_circuit_breaker_consecutive_p1_false_alarms():
    breaker = LivePilotCircuitBreaker(max_consecutive_fp=3)

    breaker.record_safety_evaluation(is_false_positive=True)
    assert breaker.is_tripped is False

    breaker.record_safety_evaluation(is_false_positive=True)
    assert breaker.is_tripped is False

    # 3rd consecutive false alarm trips failsafe
    breaker.record_safety_evaluation(is_false_positive=True)
    assert breaker.is_tripped is True
    assert "Exceeded max consecutive P1 false positives" in breaker.trip_reason


def test_circuit_breaker_supervisor_panic_and_reset():
    breaker = LivePilotCircuitBreaker()
    breaker.panic(supervisor_id="sup_alice", note="Severe acoustic echo reported by multiple callers")
    assert breaker.is_tripped is True
    assert "Supervisor panic switch triggered by sup_alice" in breaker.trip_reason

    # Reset
    breaker.reset(supervisor_id="sup_bob")
    assert breaker.is_tripped is False
    assert breaker.trip_reason == ""


def test_api_start_interaction_phase1_flow(reset_ops_db):
    client = TestClient(app)

    # Call 1: Call hash matching 5% slice (hash 2 % 100 == 2 < 5)
    headers = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "2"}
    resp1 = client.post("/api/interactions/start", headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["phase1_admitted"] is True
    assert data1["routed_to"] == "live_voice_agent"
    assert data1["daily_routed_count"] == 1
    assert data1["interaction_id"] is not None

    # Call 2: Call hash not in 5% slice (hash 50 % 100 == 50 >= 5)
    headers_non_pilot = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "50"}
    resp2 = client.post("/api/interactions/start", headers=headers_non_pilot)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["admitted"] is False
    assert data2["routed_to"] == "human_control"
    assert data2["reason"] == "routed_to_human_control"


def test_api_circuit_breaker_trip_redirects_traffic(reset_ops_db):
    client = TestClient(app)

    # Trip breaker via panic endpoint
    panic_resp = client.post("/api/interactions/routing/panic", params={"note": "Simulated acoustic breakdown"})
    assert panic_resp.status_code == 200
    assert panic_resp.json()["is_tripped"] is True

    # Incoming pilot call must now be instantly rejected and redirected to human
    headers = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "1"}
    resp = client.post("/api/interactions/start", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["admitted"] is False
    assert data["routed_to"] == "human_control"
    assert "circuit_breaker_tripped" in data["reason"]

    # Reset breaker
    reset_resp = client.post("/api/interactions/routing/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["is_tripped"] is False

    # New call is now admitted
    resp_after = client.post("/api/interactions/start", headers=headers)
    assert resp_after.status_code == 200
    assert resp_after.json()["phase1_admitted"] is True


def test_api_remedy_authorization_hitl(reset_ops_db):
    client = TestClient(app)

    # Start interaction
    resp = client.post("/api/interactions/start")
    iid = resp.json()["interaction_id"]

    # Authorize remedy
    auth_resp = client.post(f"/api/interactions/{iid}/authorize-remedy")
    assert auth_resp.status_code == 200
    assert auth_resp.json()["authorized"] is True


def test_day_one_supervisor_drill_e2e(reset_ops_db):
    from src.routing.day_one_drill import DayOneDrillRunner

    runner = DayOneDrillRunner(verbose=False)
    summary = runner.run_all_drills()
    assert summary["overall_status"] == "PASS"
    assert summary["drills"]["drill_1"]["status"] == "PASS"
    assert summary["drills"]["drill_2"]["status"] == "PASS"
    assert summary["drills"]["drill_3"]["status"] == "PASS"
    assert summary["drills"]["drill_4"]["status"] == "PASS"
    assert summary["drills"]["drill_4"]["evacuation_latency_sec"] < 60.0
    assert summary["drills"]["drill_5"]["status"] == "PASS"
