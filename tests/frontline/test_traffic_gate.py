from __future__ import annotations

import datetime
from unittest.mock import MagicMock
import pytest

from src.routing.traffic_gate import Phase1TrafficGate, compute_call_hash
from src.routing.circuit_breaker import LivePilotCircuitBreaker


def test_five_percent_split_approximately_holds():
    """Simulate 10,000 calls with distinct seed sources and verify ~5% split (400-600 admitted)."""
    gate = Phase1TrafficGate(
        target_ratio=0.05,
        daily_max_calls=10000,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    admitted_count = 0

    for i in range(10000):
        seed = f"caller_ani_{i:06d}"
        admitted, _ = gate.evaluate_ingress(seed_source=seed, now=now)
        if admitted:
            admitted_count += 1

    assert 400 <= admitted_count <= 600, f"Expected 400-600 admitted out of 10k, got {admitted_count}"


def test_call_seed_nameerror_path_never_admits(caplog):
    """If seed computation fails or raises, call must be rejected to human control and logged."""
    gate = Phase1TrafficGate(
        target_ratio=0.05,
        daily_max_calls=100,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)

    class BrokenSeed:
        def __str__(self):
            raise NameError("name 'call_seed' is not defined")

    with caplog.at_level("CRITICAL"):
        admitted, reason = gate.evaluate_ingress(seed_source=BrokenSeed(), now=now)

    assert admitted is False
    assert reason == "seed_computation_failed"
    assert "traffic_gate_seed_failure" in caplog.text or "NameError" in caplog.text


def test_daily_cap_enforced():
    """Gate with daily_max_calls=5 admits at most 5 calls, rejecting further calls."""
    gate = Phase1TrafficGate(
        target_ratio=1.0,
        daily_max_calls=5,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    admitted_count = 0

    for i in range(20):
        admitted, reason = gate.evaluate_ingress(seed_source=f"call_{i}", now=now)
        if admitted:
            admitted_count += 1
        else:
            assert reason == "daily_volume_ceiling_reached"

    assert admitted_count == 5
    assert gate.daily_routed_count == 5


def test_outside_operating_hours_rejected():
    """Calls outside the operating hours window must be rejected."""
    gate = Phase1TrafficGate(
        target_ratio=1.0,
        daily_max_calls=100,
        start_hour_utc=13,
        end_hour_utc=21,
    )
    outside_now = datetime.datetime(2026, 9, 6, 10, 0, tzinfo=datetime.timezone.utc)
    admitted, reason = gate.evaluate_ingress(seed_source="call_outside", now=outside_now)
    assert admitted is False
    assert reason == "outside_operating_hours"


def test_inside_operating_hours_admitted():
    """Calls inside the operating hours window with eligible hash must be admitted."""
    gate = Phase1TrafficGate(
        target_ratio=1.0,
        daily_max_calls=100,
        start_hour_utc=13,
        end_hour_utc=21,
    )
    inside_now = datetime.datetime(2026, 9, 6, 14, 0, tzinfo=datetime.timezone.utc)
    admitted, reason = gate.evaluate_ingress(seed_source="call_inside", now=inside_now)
    assert admitted is True
    assert reason == "admitted_to_pilot"


def test_circuit_breaker_tripped_rejects_all():
    """When circuit breaker is tripped, calls that would otherwise be admitted are rejected."""
    cb = LivePilotCircuitBreaker()
    cb.panic(supervisor_id="sup_test", note="Acoustic breakdown")
    assert cb.is_tripped is True

    gate = Phase1TrafficGate(
        target_ratio=1.0,
        daily_max_calls=100,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    admitted, reason = gate.evaluate_ingress(seed_source="call_cb", now=now, circuit_breaker=cb)
    assert admitted is False
    assert reason == "circuit_breaker_tripped"


def test_target_ratio_zero_admits_nothing():
    """target_ratio=0.0 must never admit any call."""
    gate = Phase1TrafficGate(
        target_ratio=0.0,
        daily_max_calls=100,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)

    for i in range(100):
        admitted, reason = gate.evaluate_ingress(seed_source=f"call_{i}", now=now)
        assert admitted is False
        assert reason == "routed_to_human_control"

    assert gate.daily_routed_count == 0


def test_target_ratio_one_admits_everything():
    """target_ratio=1.0 admits 100% of calls within ceilings."""
    gate = Phase1TrafficGate(
        target_ratio=1.0,
        daily_max_calls=1000,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)

    for i in range(100):
        admitted, reason = gate.evaluate_ingress(seed_source=f"call_{i}", now=now)
        assert admitted is True
        assert reason == "admitted_to_pilot"

    assert gate.daily_routed_count == 100


def test_invalid_target_ratio_fails_closed(caplog):
    """Negative target_ratio or target_ratio > 1.0 must fail closed and log critical."""
    for invalid_ratio in (-0.5, 1.5):
        gate = Phase1TrafficGate(
            target_ratio=invalid_ratio,
            daily_max_calls=100,
            start_hour_utc=0,
            end_hour_utc=24,
        )
        now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)

        with caplog.at_level("CRITICAL"):
            admitted, reason = gate.evaluate_ingress(seed_source="call_invalid", now=now)

        assert admitted is False
        assert reason == "invalid_target_ratio"


def test_seed_hash_uniformity():
    """100,000 seeds distributed across 100 buckets must be approximately uniform."""
    from collections import Counter

    counts = Counter()
    for i in range(100000):
        h = compute_call_hash(f"caller_ani_seed_{i}")
        counts[h] += 1

    assert len(counts) == 100
    for b in range(100):
        c = counts[b]
        assert 800 <= c <= 1200, f"Bucket {b} count {c} deviated too far from expected 1000"


def test_daily_counter_resets_at_midnight():
    """Daily admitted count resets when crossing UTC midnight."""
    gate = Phase1TrafficGate(
        target_ratio=1.0,
        daily_max_calls=3,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    day1 = datetime.datetime(2026, 9, 5, 23, 59, tzinfo=datetime.timezone.utc)
    for i in range(3):
        admitted, _ = gate.evaluate_ingress(seed_source=f"c1_{i}", now=day1)
        assert admitted is True
    assert gate.daily_routed_count == 3

    admitted, reason = gate.evaluate_ingress(seed_source="c1_overflow", now=day1)
    assert admitted is False
    assert reason == "daily_volume_ceiling_reached"

    day2 = datetime.datetime(2026, 9, 6, 0, 1, tzinfo=datetime.timezone.utc)
    admitted, reason = gate.evaluate_ingress(seed_source="c2_first", now=day2)
    assert admitted is True
    assert reason == "admitted_to_pilot"
    assert gate.daily_routed_count == 1


def test_scope_boundary_enforced():
    """Calls targeting packs outside allowed_domain must be rejected with out_of_scope_pack."""
    gate = Phase1TrafficGate(
        target_ratio=1.0,
        allowed_domain="automotive_nhtsa",
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    admitted, reason = gate.evaluate_ingress(seed_source="c_scope", now=now, domain="finance_cfpb")
    assert admitted is False
    assert "out_of_scope_pack" in reason


def test_gate_failure_counter_increments_on_seed_failure():
    """Seed failure must increment gate_seed_failure_total metric."""
    gate = Phase1TrafficGate(
        target_ratio=0.05,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    initial_failures = gate.gate_seed_failure_total

    admitted, reason = gate.evaluate_ingress(seed_source="", now=now)
    assert admitted is False
    assert reason == "seed_computation_failed"
    assert gate.gate_seed_failure_total == initial_failures + 1


def test_no_admission_when_seed_missing():
    """Empty or None seed source must reject with seed_computation_failed."""
    gate = Phase1TrafficGate(
        target_ratio=0.05,
        start_hour_utc=0,
        end_hour_utc=24,
    )
    now = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)

    for empty_seed in (None, "", "   "):
        admitted, reason = gate.evaluate_ingress(seed_source=empty_seed, now=now)
        assert admitted is False
        assert reason == "seed_computation_failed"
