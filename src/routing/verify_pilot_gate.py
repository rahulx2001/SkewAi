"""Verification Script for Phase 1 Live Pilot Gate & Circuit Breaker.

Verifies:
  1. Admitted calls update the daily ingress counter.
  2. Circuit breaker trips and correctly redirects calls when simulated latency exceeds 1,000ms.
  3. Evacuated traffic redirects to standard human queue.
  4. Manual / supervisor reset restores normal ingress.

Usage:
  python3 -m src.routing.verify_pilot_gate
"""

from __future__ import annotations

import sys
from fastapi.testclient import TestClient

from src.api.main import app
from src.routing.circuit_breaker import LivePilotCircuitBreaker, set_circuit_breaker
from src.routing.traffic_gate import Phase1TrafficGate, set_traffic_gate


def run_verification() -> bool:
    print("=" * 80)
    print("   PHASE 1 CONTROLLED LIVE PILOT: GATE & CIRCUIT BREAKER VERIFICATION")
    print("=" * 80)

    # 1. Initialize Gate & Breaker
    gate = Phase1TrafficGate(
        target_ratio=0.05,
        daily_max_calls=50,
        start_hour_utc=0,
        end_hour_utc=24,
        allowed_domain="automotive_nhtsa",
    )
    breaker = LivePilotCircuitBreaker(latency_ceiling_ms=1000.0, max_consecutive_fp=3)
    set_traffic_gate(gate)
    set_circuit_breaker(breaker)

    client = TestClient(app)

    print("\n[Step 1] Inbound Call Ingress (Hash matching 5% split)...")
    headers_admitted = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "3"}
    resp1 = client.post("/api/interactions/start", headers=headers_admitted)
    assert resp1.status_code == 200, f"Expected 200, got {resp1.status_code}: {resp1.text}"
    data1 = resp1.json()

    print(f"  → Admitted: {data1.get('phase1_admitted')}")
    print(f"  → Routed To: {data1.get('routed_to')}")
    print(f"  → Daily Counter: {data1.get('daily_routed_count')} / {gate.daily_max_calls}")
    print(f"  → Interaction ID: {data1.get('interaction_id')}")

    assert data1["phase1_admitted"] is True, "Call should have been admitted to 5% live pilot"
    assert data1["routed_to"] == "live_voice_agent"
    assert data1["daily_routed_count"] == 1, "Daily ingress counter must be incremented to 1"

    print("\n[Step 2] Simulating Turn Latency Spike Exceeding 1,000ms Ceiling...")
    for i in range(10):
        breaker.record_turn_latency(1150.0)
    print(f"  → Breaker Tripped: {breaker.is_tripped}")
    print(f"  → Trip Reason: {breaker.trip_reason}")
    assert breaker.is_tripped is True, "Circuit breaker must trip after rolling latency > 1000ms"

    print("\n[Step 3] Inbound Call Ingress While Circuit Breaker Is Tripped...")
    resp2 = client.post("/api/interactions/start", headers=headers_admitted)
    assert resp2.status_code == 200
    data2 = resp2.json()

    print(f"  → Admitted: {data2.get('admitted')}")
    print(f"  → Routed To: {data2.get('routed_to')}")
    print(f"  → Rejection Reason: {data2.get('reason')}")

    assert data2["admitted"] is False, "Call must NOT be admitted when circuit breaker is tripped"
    assert data2["routed_to"] == "human_control", "Call must be evacuated to human control queue"
    assert "circuit_breaker_tripped" in data2["reason"]

    print("\n[Step 4] Supervisor Incident Resolution & Breaker Reset...")
    reset_resp = client.post("/api/interactions/routing/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["is_tripped"] is False
    print("  → Circuit breaker successfully reset to operational state.")

    print("\n[Step 5] Inbound Call Ingress After Breaker Reset...")
    headers_next = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "1"}
    resp3 = client.post("/api/interactions/start", headers=headers_next)
    assert resp3.status_code == 200
    data3 = resp3.json()

    print(f"  → Admitted: {data3.get('phase1_admitted')}")
    print(f"  → Routed To: {data3.get('routed_to')}")
    print(f"  → Daily Counter: {data3.get('daily_routed_count')} / {gate.daily_max_calls}")

    assert data3["phase1_admitted"] is True
    assert data3["daily_routed_count"] == 2

    print("\n" + "=" * 80)
    print("   ALL PHASE 1 GATING & CIRCUIT BREAKER INVARIANTS VERIFIED [PASS]")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
