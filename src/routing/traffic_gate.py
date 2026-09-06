"""Phase 1 Traffic Ingress Gate — 5% Controlled Split & Operating Window Enforcement."""

from __future__ import annotations

import datetime
import hashlib
from typing import Any, Tuple
from src.security.logging import get_logger

logger = get_logger("routing.traffic_gate")


def compute_call_hash(seed_source: Any) -> int:
    """Compute uniform call hash in range [0, 99] from seed source.

    Seed source must be non-empty and uniform per call.
    Uses SHA-256 64-bit integer modulo 100 for statistically uniform distribution.
    """
    if seed_source is None:
        raise ValueError("seed_source cannot be None")
    if isinstance(seed_source, int):
        return seed_source % 100
    if isinstance(seed_source, str):
        if not seed_source.strip():
            raise ValueError("seed_source cannot be empty")
        raw = seed_source.strip().encode("utf-8")
    elif isinstance(seed_source, bytes):
        if not seed_source:
            raise ValueError("seed_source cannot be empty bytes")
        raw = seed_source
    else:
        s = str(seed_source).strip()
        if not s:
            raise ValueError("seed_source string conversion is empty")
        raw = s.encode("utf-8")

    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") % 100


class Phase1TrafficGate:
    """
    Enforces traffic split boundaries, daily call limits, operating hour
    constraints, and circuit breaker checks for Phase 1 live pilot deployment.
    """

    def __init__(
        self,
        target_ratio: float = 0.05,
        daily_max_calls: int = 50,
        start_hour_utc: int = 13,  # 09:00 ET / Business hours
        end_hour_utc: int = 21,    # 17:00 ET
        allowed_domain: str = "automotive_nhtsa",
    ) -> None:
        self.target_ratio = target_ratio
        self.daily_max_calls = daily_max_calls
        self.start_hour = start_hour_utc
        self.end_hour = end_hour_utc
        self.allowed_domain = allowed_domain
        self._current_date = datetime.date.today()
        self._daily_routed_count = 0

        # Observability metrics
        self.gate_admitted_total: int = 0
        self.gate_rejected_total: dict[str, int] = {
            "circuit_breaker_tripped": 0,
            "outside_operating_hours": 0,
            "daily_volume_ceiling_reached": 0,
            "out_of_scope_pack": 0,
            "seed_computation_failed": 0,
            "routed_to_human_control": 0,
            "invalid_target_ratio": 0,
        }
        self.gate_seed_failure_total: int = 0

    def _compute_call_hash(self, seed_source: Any) -> int:
        return compute_call_hash(seed_source)

    def _is_in_scope(self, domain: str | None) -> bool:
        if domain and domain != self.allowed_domain:
            return False
        return True

    def _record_admission(self) -> None:
        self.gate_admitted_total += 1
        logger.info(
            "phase1_call_admitted",
            daily_count=self._daily_routed_count,
            total_admitted=self.gate_admitted_total,
        )

    def _record_rejection(self, reason_key: str, detail: str = "") -> None:
        self.gate_rejected_total[reason_key] = self.gate_rejected_total.get(reason_key, 0) + 1
        logger.info(
            "phase1_call_rejected",
            reason=reason_key,
            detail=detail,
            total_rejected=self.gate_rejected_total[reason_key],
        )

    def evaluate_ingress(
        self,
        seed_source: Any = None,
        *,
        call_hash: int | None = None,
        now: datetime.datetime | None = None,
        domain: str | None = None,
        circuit_breaker: Any = None,
    ) -> Tuple[bool, str]:
        # Defensive check: target_ratio boundaries
        if self.target_ratio < 0.0 or self.target_ratio > 1.0:
            logger.critical("traffic_gate_invalid_target_ratio", target_ratio=self.target_ratio)
            self._record_rejection("invalid_target_ratio")
            return False, "invalid_target_ratio"

        # 1. Circuit breaker check (Prompt §4)
        cb = circuit_breaker
        if cb is None:
            try:
                from src.routing.circuit_breaker import get_circuit_breaker

                cb = get_circuit_breaker()
            except Exception:
                cb = None
        if cb is not None and getattr(cb, "is_tripped", False):
            self._record_rejection("circuit_breaker_tripped")
            return False, "circuit_breaker_tripped"

        # Time normalization and midnight reset
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        # Reset counter at UTC midnight
        if now.date() != self._current_date:
            self._current_date = now.date()
            self._daily_routed_count = 0

        # 2. Operating hours check (Prompt §4)
        if not (self.start_hour <= now.hour < self.end_hour):
            self._record_rejection("outside_operating_hours")
            return False, "outside_operating_hours"

        # 3. Daily ceiling check (Prompt §4 & §5)
        if self.daily_max_calls <= 0 or self._daily_routed_count >= self.daily_max_calls:
            self._record_rejection("daily_volume_ceiling_reached")
            return False, "daily_volume_ceiling_reached"

        # 4. Scope check (Prompt §4)
        if not self._is_in_scope(domain):
            self._record_rejection("out_of_scope_pack", detail=str(domain))
            return False, f"out_of_scope_pack: out_of_scope_domain_{domain}"

        # Defensive check: target_ratio == 0.0
        if self.target_ratio == 0.0:
            self._record_rejection("routed_to_human_control")
            return False, "routed_to_human_control"

        # 5. Deterministic hash split (Prompt §4)
        computed_hash: int
        if call_hash is not None:
            computed_hash = int(call_hash) % 100
        elif seed_source is not None and isinstance(seed_source, int):
            computed_hash = seed_source % 100
        else:
            try:
                computed_hash = self._compute_call_hash(seed_source)
            except Exception as e:
                self.gate_seed_failure_total += 1
                self._record_rejection("seed_computation_failed", detail=str(e))
                logger.critical("traffic_gate_seed_failure", error=str(e))
                return False, "seed_computation_failed"

        # Target ratio == 1.0 (all calls admitted)
        if self.target_ratio >= 1.0:
            self._daily_routed_count += 1
            self._record_admission()
            return True, "admitted_to_pilot"

        threshold = int(self.target_ratio * 100)
        is_selected = computed_hash < threshold
        if is_selected:
            self._daily_routed_count += 1
            self._record_admission()
            return True, "admitted_to_pilot"

        self._record_rejection("routed_to_human_control")
        return False, "routed_to_human_control"

    @property
    def daily_routed_count(self) -> int:
        return self._daily_routed_count

    def reset_daily_count(self) -> None:
        self._daily_routed_count = 0


_default_gate: Phase1TrafficGate | None = None


def get_traffic_gate() -> Phase1TrafficGate:
    global _default_gate
    if _default_gate is None:
        _default_gate = Phase1TrafficGate()
    return _default_gate


def set_traffic_gate(gate: Phase1TrafficGate | None) -> None:
    global _default_gate
    _default_gate = gate
