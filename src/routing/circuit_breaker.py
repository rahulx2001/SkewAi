"""Live Pilot Automated Circuit Breaker & Panic Kill Switch."""

from __future__ import annotations

import time
from collections import deque
from typing import Any
from src.security.logging import get_logger

logger = get_logger("routing.circuit_breaker")


class LivePilotCircuitBreaker:
    """
    Monitors operational health metrics during live calls.
    Trips hard failsafe to instantly revert 100% of traffic to human queues within 60 seconds.
    """

    def __init__(
        self,
        latency_ceiling_ms: float = 1000.0,
        max_consecutive_fp: int = 3,
        error_rate_threshold: float = 0.01,
        window_seconds: float = 900.0,  # 15 minutes
    ) -> None:
        self.latency_ceiling_ms = latency_ceiling_ms
        self.max_consecutive_fp = max_consecutive_fp
        self.error_rate_threshold = error_rate_threshold
        self.window_seconds = window_seconds

        self.is_tripped = False
        self.trip_reason: str = ""
        self.tripped_at: float | None = None

        self._recent_latencies: deque[float] = deque(maxlen=10)
        self._consecutive_p1_fps = 0
        self._request_history: deque[tuple[float, bool]] = deque()

    def record_turn_latency(self, latency_ms: float) -> None:
        if self.is_tripped:
            return
        self._recent_latencies.append(latency_ms)
        if len(self._recent_latencies) == 10:
            avg_latency = sum(self._recent_latencies) / 10.0
            if avg_latency > self.latency_ceiling_ms:
                self.trip(f"Rolling latency p95 breached ceiling: {avg_latency:.1f}ms")

    def record_safety_evaluation(self, is_false_positive: bool = False, missed_safety: bool = False) -> None:
        if self.is_tripped:
            return
        if missed_safety:
            self.trip("Missed Safety Escaped: verified hazard failed to trip within 1 turn")
            return

        if is_false_positive:
            self._consecutive_p1_fps += 1
            if self._consecutive_p1_fps >= self.max_consecutive_fp:
                self.trip(f"Exceeded max consecutive P1 false positives: {self._consecutive_p1_fps}")
        else:
            self._consecutive_p1_fps = 0

    def record_request_outcome(self, is_error: bool, timestamp: float | None = None) -> None:
        if self.is_tripped:
            return
        now = timestamp if timestamp is not None else time.time()
        self._request_history.append((now, is_error))
        cutoff = now - self.window_seconds
        while self._request_history and self._request_history[0][0] < cutoff:
            self._request_history.popleft()

        total = len(self._request_history)
        if total >= 20:
            errors = sum(1 for _, err in self._request_history if err)
            rate = errors / total
            if rate > self.error_rate_threshold:
                self.trip(f"Unhandled 5xx error rate exceeded {self.error_rate_threshold*100:.1f}%: {rate*100:.1f}%")

    def trip(self, reason: str) -> None:
        self.is_tripped = True
        self.trip_reason = reason
        self.tripped_at = time.time()
        logger.critical("CIRCUIT_BREAKER_TRIPPED_EVACUATING_TRAFFIC", reason=reason)

    def reset(self, supervisor_id: str) -> None:
        logger.warn("circuit_breaker_manually_reset", supervisor_id=supervisor_id)
        self.is_tripped = False
        self.trip_reason = ""
        self.tripped_at = None
        self._recent_latencies.clear()
        self._consecutive_p1_fps = 0
        self._request_history.clear()

    def panic(self, supervisor_id: str, note: str = "") -> None:
        """Manual single-click kill-switch pressed on CommandCenter."""
        reason = f"Supervisor panic switch triggered by {supervisor_id}"
        if note:
            reason += f": {note}"
        self.trip(reason)

    def status(self) -> dict[str, Any]:
        return {
            "is_tripped": self.is_tripped,
            "trip_reason": self.trip_reason,
            "tripped_at": self.tripped_at,
            "recent_latency_samples": len(self._recent_latencies),
            "consecutive_p1_fps": self._consecutive_p1_fps,
        }


_default_breaker: LivePilotCircuitBreaker | None = None


def get_circuit_breaker() -> LivePilotCircuitBreaker:
    global _default_breaker
    if _default_breaker is None:
        _default_breaker = LivePilotCircuitBreaker()
    return _default_breaker


def set_circuit_breaker(breaker: LivePilotCircuitBreaker | None) -> None:
    global _default_breaker
    _default_breaker = breaker
