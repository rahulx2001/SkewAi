"""Blue-green deploy with call draining (feature #51).

On SIGTERM: stop accepting new contacts, let active ones reach CLOSING, persist,
then exit. ``DrainController`` is process-global.
"""

from __future__ import annotations

import asyncio
import signal
import threading
from typing import Any, Callable


class ServiceDrainingError(RuntimeError):
    """Raised when create_interaction is refused because the process is draining."""

    def __init__(self, message: str = "service_draining: not accepting new contacts") -> None:
        super().__init__(message)


class DrainController:
    def __init__(self) -> None:
        self._draining = False
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._on_drain_hooks: list[Callable[[], None]] = []
        self._sigterm_installed = False

    @property
    def draining(self) -> bool:
        with self._lock:
            return self._draining

    def register_active(self, interaction_id: str) -> bool:
        """Return False if draining (reject new contacts)."""
        with self._lock:
            if self._draining:
                return False
            self._active.add(interaction_id)
            return True

    def unregister(self, interaction_id: str) -> None:
        with self._lock:
            self._active.discard(interaction_id)

    def begin_drain(self) -> dict[str, Any]:
        with self._lock:
            self._draining = True
            active = list(self._active)
        for h in self._on_drain_hooks:
            try:
                h()
            except Exception:
                pass
        return {"draining": True, "active_interactions": active, "count": len(active)}

    def reset(self) -> None:
        """Clear drain flags (tests / post-deploy warm start)."""
        with self._lock:
            self._draining = False
            self._active.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "draining": self._draining,
                "active_count": len(self._active),
                "active_interactions": list(self._active),
                "ready_to_exit": self._draining and len(self._active) == 0,
                "sigterm_handler_installed": self._sigterm_installed,
            }

    def on_drain(self, fn: Callable[[], None]) -> None:
        self._on_drain_hooks.append(fn)

    async def wait_until_drained(self, timeout_s: float = 120.0) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            if self.status()["ready_to_exit"]:
                return True
            await asyncio.sleep(0.05)
        return self.status()["ready_to_exit"]


DRAIN = DrainController()


def install_sigterm_handler() -> None:
    """Install SIGTERM → begin_drain (no hard exit; process manager waits)."""

    def _handler(signum, frame):  # noqa: ARG001
        DRAIN.begin_drain()

    try:
        signal.signal(signal.SIGTERM, _handler)
        DRAIN._sigterm_installed = True
    except Exception:
        # Windows / restricted environments may refuse signal handlers.
        pass
