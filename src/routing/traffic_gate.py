"""Phase 1 Traffic Ingress Gate — 5% Controlled Split & Operating Window Enforcement."""

from __future__ import annotations

import datetime
from typing import Tuple
from src.security.logging import get_logger

logger = get_logger("routing.traffic_gate")


class Phase1TrafficGate:
    """
    Enforces traffic split boundaries, daily call limits, and operating hour
    constraints for Phase 1 live pilot deployment.
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

    def evaluate_ingress(
        self,
        call_hash: int,
        now: datetime.datetime | None = None,
        domain: str | None = None,
    ) -> Tuple[bool, str]:
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        # Reset counter at UTC midnight
        if now.date() != self._current_date:
            self._current_date = now.date()
            self._daily_routed_count = 0

        # Constraint 0: Domain / Scope Boundary
        if domain and domain != self.allowed_domain:
            return False, f"out_of_scope_domain_{domain}"

        # Constraint 1: Operating Window
        if not (self.start_hour <= now.hour < self.end_hour):
            return False, "outside_operating_hours"

        # Constraint 2: Volume Ceiling
        if self._daily_routed_count >= self.daily_max_calls:
            return False, "daily_volume_ceiling_reached"

        # Constraint 3: Hash-based Deterministic Traffic Split (exact 5%)
        is_selected = (call_hash % 100) < int(self.target_ratio * 100)
        if is_selected:
            self._daily_routed_count += 1
            logger.info("phase1_call_admitted", daily_count=self._daily_routed_count)
            return True, "admitted_to_pilot"

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
