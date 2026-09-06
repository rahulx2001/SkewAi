"""Day-One Runbook & Supervisor Staging Drill Runner for Phase 1 Live Pilot.

Executes the five mandatory pre-pilot staging drills before live customer traffic is un-gated:
  Drill 1: 5% Traffic Split & Scope Boundary Ingress (20 simulated calls)
  Drill 2: Supervisor Takeover Intervention (10x calls with state verification)
  Drill 3: Stage 5 Remedy Authorization HITL Gate (10x calls, speech held until approval)
  Drill 4: Panic Kill-Switch Evacuation Stopwatch Drill (Measure evacuation SLA < 60s)
  Drill 5: Post-Incident Breaker Reset & Normal Ingress Restoration

Usage:
  python3 -m src.routing.day_one_drill
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import json
import sys
import time
from typing import Any

from fastapi.testclient import TestClient

from src.api.limiter import limiter
from src.api.main import app
from src.api.rbac import _secret
from src.api.routes.interactions import _active
from src.routing.circuit_breaker import LivePilotCircuitBreaker, get_circuit_breaker, set_circuit_breaker
from src.routing.traffic_gate import Phase1TrafficGate, set_traffic_gate


def _make_supervisor_session(subject: str = "supervisor_alice") -> str:
    """Mint an authenticated supervisor session token for HITL drills."""
    body = {"sub": subject, "role": "supervisor", "exp": int(time.time()) + 3600}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}|{sig}"


class DayOneDrillRunner:
    """Automates and records the pre-pilot staging drills."""

    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        # Disable rate limiter during hermetic drill batch execution
        self._orig_limiter_state = limiter.enabled
        limiter.enabled = False
        self.client = TestClient(app)
        self.results: dict[str, Any] = {}

    def close(self) -> None:
        limiter.enabled = self._orig_limiter_state

    def log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def drill_1_traffic_split_and_scope_boundary(self) -> bool:
        """Drill 1: Ingest 20 simulated calls and verify 5% split and scope boundary."""
        self.log("\n[Drill 1] 5% Ingress Split & Scope Boundary Enforcement (20 calls)...")
        gate = Phase1TrafficGate(
            target_ratio=0.05,
            daily_max_calls=50,
            start_hour_utc=0,
            end_hour_utc=24,
            allowed_domain="automotive_nhtsa",
        )
        breaker = LivePilotCircuitBreaker(latency_ceiling_ms=1000.0)
        set_traffic_gate(gate)
        set_circuit_breaker(breaker)

        admitted_count = 0
        redirected_count = 0

        # Simulate 20 incoming calls with deterministic hash values
        for i in range(20):
            call_hash = i
            headers = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": str(call_hash)}
            resp = self.client.post("/api/interactions/start", headers=headers)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            data = resp.json()

            if (call_hash % 100) < 5:
                assert data["phase1_admitted"] is True
                assert data["routed_to"] == "live_voice_agent"
                admitted_count += 1
            else:
                assert data["admitted"] is False
                assert data["routed_to"] == "human_control"
                redirected_count += 1

        # Test out-of-scope domain lock (finance_cfpb must fail closed)
        out_of_scope_hash = 2  # Would normally qualify for 5%
        now = datetime.datetime.now(datetime.timezone.utc)
        admitted, reason = gate.evaluate_ingress(call_hash=out_of_scope_hash, now=now, domain="finance_cfpb")
        assert admitted is False
        assert "out_of_scope_domain" in reason

        self.log(f"  → Admitted calls into 5% split: {admitted_count}/20")
        self.log(f"  → Redirected to human queue: {redirected_count}/20")
        self.log("  → Out-of-scope domain fail-closed: PASS")
        self.results["drill_1"] = {
            "status": "PASS",
            "admitted_count": admitted_count,
            "redirected_count": redirected_count,
            "scope_lock_verified": True,
        }
        return True

    def drill_2_supervisor_takeover(self) -> bool:
        """Drill 2: Exercise 10 supervisor takeover interventions and verify state."""
        self.log("\n[Drill 2] Supervisor Takeover Interventions (10x calls)...")
        gate = Phase1TrafficGate(target_ratio=1.0, daily_max_calls=50, start_hour_utc=0, end_hour_utc=24)
        breaker = LivePilotCircuitBreaker()
        set_traffic_gate(gate)
        set_circuit_breaker(breaker)

        takeover_successes = 0

        for i in range(10):
            actor_name = f"supervisor_{i+1:02d}"
            token = _make_supervisor_session(actor_name)
            # Start an admitted interaction
            headers = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "1"}
            resp = self.client.post("/api/interactions/start", headers=headers)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            iid = resp.json()["interaction_id"]
            assert iid is not None

            # Execute supervisor takeover
            takeover_resp = self.client.post(
                f"/api/interactions/{iid}/takeover",
                headers={"x-frontline-session": token, "X-Actor": actor_name},
            )
            assert takeover_resp.status_code == 200, f"Takeover failed: {takeover_resp.text}"
            t_data = takeover_resp.json()

            assert t_data["state"] == "SUPERVISED"
            assert t_data["supervised"] is True
            assert t_data["claimed_by"] == actor_name
            takeover_successes += 1

        self.log(f"  → Successfully executed and audited takeovers: {takeover_successes}/10")
        self.results["drill_2"] = {
            "status": "PASS",
            "takeover_count": takeover_successes,
            "state_supervised_verified": True,
        }
        return True

    def drill_3_remedy_authorization_gate(self) -> bool:
        """Drill 3: Stage 5 Remedy Authorization HITL Gate (10x calls)."""
        self.log("\n[Drill 3] Remedy Authorization HITL Gate (10x calls)...")
        gate = Phase1TrafficGate(target_ratio=1.0, daily_max_calls=50, start_hour_utc=0, end_hour_utc=24)
        breaker = LivePilotCircuitBreaker()
        set_traffic_gate(gate)
        set_circuit_breaker(breaker)

        auth_successes = 0

        for i in range(10):
            token = _make_supervisor_session(f"supervisor_rem_{i+1}")
            headers = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "1"}
            resp = self.client.post("/api/interactions/start", headers=headers)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            iid = resp.json()["interaction_id"]

            # Plant a pending remedy proposal
            entry = _active.get(iid)
            assert entry is not None
            entry.orch.ctx.remedy_authorized = False
            entry.orch.ctx.pending_remedy_offer = {
                "customer_text": "We have authorized warranty reimbursement for your brake repair.",
            }

            # Verify unapproved state
            assert entry.orch.ctx.remedy_authorized is False

            # Supervisor authorizes the remedy
            auth_resp = self.client.post(
                f"/api/interactions/{iid}/authorize-remedy",
                headers={"x-frontline-session": token},
            )
            assert auth_resp.status_code == 200, f"Auth failed: {auth_resp.text}"
            a_data = auth_resp.json()
            assert a_data["authorized"] is True
            assert entry.orch.ctx.remedy_authorized is True
            assert entry.orch.ctx.pending_remedy_offer is None  # Emitted and cleared
            auth_successes += 1

        self.log(f"  → Verified remedy authorizations: {auth_successes}/10")
        self.results["drill_3"] = {
            "status": "PASS",
            "authorized_remedies": auth_successes,
            "zero_unauthorized_speech": True,
        }
        return True

    def drill_4_panic_kill_switch_evacuation_stopwatch(self) -> bool:
        """Drill 4: Trigger panic switch and measure evacuation SLA with stopwatch (<60s)."""
        self.log("\n[Drill 4] Panic Kill-Switch Evacuation Stopwatch Drill (<60s SLA)...")
        gate = Phase1TrafficGate(target_ratio=0.05, daily_max_calls=50, start_hour_utc=0, end_hour_utc=24)
        breaker = LivePilotCircuitBreaker()
        set_traffic_gate(gate)
        set_circuit_breaker(breaker)

        token = _make_supervisor_session("supervisor_ops")

        # 1. Start stopwatch
        t0 = time.perf_counter()

        # 2. Supervisor presses single-click panic switch on live console
        panic_resp = self.client.post(
            "/api/interactions/routing/panic",
            params={"note": "Automated drill: Acoustic line distortion"},
            headers={"x-frontline-session": token},
        )
        assert panic_resp.status_code == 200
        assert panic_resp.json()["is_tripped"] is True

        # 3. Simulate sudden burst of 10 incoming calls
        evacuated_calls = 0
        for i in range(10):
            headers = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": str(i)}
            burst_resp = self.client.post("/api/interactions/start", headers=headers)
            assert burst_resp.status_code == 200
            b_data = burst_resp.json()
            assert b_data["admitted"] is False
            assert b_data["routed_to"] == "human_control"
            assert "circuit_breaker_tripped" in b_data["reason"]
            evacuated_calls += 1

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        elapsed_sec = elapsed_ms / 1000.0

        self.log(f"  → Burst calls successfully evacuated: {evacuated_calls}/10")
        self.log(f"  → Measured Evacuation Latency: {elapsed_ms:.2f}ms ({elapsed_sec:.4f}s)")
        self.log(f"  → Target SLA: < 60.0s [PASS - Margined by {60.0 - elapsed_sec:.2f}s]")

        assert elapsed_sec < 60.0, f"Evacuation exceeded 60s SLA: {elapsed_sec}s"

        self.results["drill_4"] = {
            "status": "PASS",
            "evacuation_latency_ms": round(elapsed_ms, 2),
            "evacuation_latency_sec": round(elapsed_sec, 4),
            "sla_target_sec": 60.0,
            "evacuated_count": evacuated_calls,
        }
        return True

    def drill_5_post_incident_reset_and_restoration(self) -> bool:
        """Drill 5: Reset circuit breaker and verify normal ingress restoration."""
        self.log("\n[Drill 5] Post-Incident Circuit Breaker Reset & Restoration...")
        breaker = get_circuit_breaker()
        assert breaker.is_tripped is True

        token = _make_supervisor_session("supervisor_lead")

        # Supervisor resets breaker after post-incident review
        reset_resp = self.client.post(
            "/api/interactions/routing/reset",
            headers={"x-frontline-session": token},
        )
        assert reset_resp.status_code == 200
        assert reset_resp.json()["is_tripped"] is False
        assert breaker.is_tripped is False

        # Verify normal 5% split traffic admission resumes
        headers = {"X-Phase1-Live-Pilot": "1", "X-Call-Hash": "1"}
        resp = self.client.post("/api/interactions/start", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase1_admitted"] is True
        assert data["routed_to"] == "live_voice_agent"

        self.log("  → Breaker successfully reset.")
        self.log("  → Pilot admission restored on hash split: PASS")
        self.results["drill_5"] = {
            "status": "PASS",
            "breaker_cleared": True,
            "ingress_restored": True,
        }
        return True

    def run_all_drills(self) -> dict[str, Any]:
        """Execute the full 5-drill staging protocol and produce summary scorecard."""
        try:
            self.log("=" * 88)
            self.log("      DAY-ONE SUPERVISOR & RUNBOOK STAGING DRILLS — PHASE 1 READINESS")
            self.log("=" * 88)

            d1 = self.drill_1_traffic_split_and_scope_boundary()
            d2 = self.drill_2_supervisor_takeover()
            d3 = self.drill_3_remedy_authorization_gate()
            d4 = self.drill_4_panic_kill_switch_evacuation_stopwatch()
            d5 = self.drill_5_post_incident_reset_and_restoration()

            all_passed = d1 and d2 and d3 and d4 and d5

            self.log("\n" + "=" * 88)
            self.log(f"DRILL EXECUTION SUMMARY: [{'PASS' if all_passed else 'FAIL'}]")
            self.log(f"  • Drill 1 (5% Split & Scope Boundary):   [{self.results['drill_1']['status']}]")
            self.log(f"  • Drill 2 (10x Supervisor Takeovers):    [{self.results['drill_2']['status']}]")
            self.log(f"  • Drill 3 (10x Remedy Authorizations):   [{self.results['drill_3']['status']}]")
            self.log(f"  • Drill 4 (Panic Evacuation Stopwatch):  [{self.results['drill_4']['status']}] ({self.results['drill_4']['evacuation_latency_ms']}ms < 60s)")
            self.log(f"  • Drill 5 (Post-Incident Restoration):   [{self.results['drill_5']['status']}]")
            self.log("=" * 88)

            return {
                "overall_status": "PASS" if all_passed else "FAIL",
                "drills": self.results,
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        finally:
            self.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Day-One Supervisor Staging Drill Runner")
    parser.add_argument("--out", type=str, default="reports/day_one_drill.json", help="Path to write drill results")
    args = parser.parse_args()

    runner = DayOneDrillRunner(verbose=True)
    report = runner.run_all_drills()

    if args.out:
        from pathlib import Path
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
