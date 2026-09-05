"""Append-only security / access audit log (SOC 2 CC7.2 engineering baseline).

Writes JSON lines to ``data/security_audit.jsonl`` and mirrors to structured
logger. Not a full SIEM — export these files to your log pipeline in production.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import REPO_ROOT
from src.ids import new_ulid

_log = logging.getLogger("skewai.security_audit")
try:
    from src.security.secrets import SecretRedactionFilter

    if not any(isinstance(f, SecretRedactionFilter) for f in _log.filters):
        _log.addFilter(SecretRedactionFilter())
except Exception:
    pass
_lock = threading.Lock()

_DEFAULT_PATH = REPO_ROOT / "data" / "security_audit.jsonl"

# Allowed roots for SECURITY_AUDIT_LOG_PATH (M16 jail).
_ALLOWED_LOG_ROOTS = (
    (REPO_ROOT / "data").resolve(),
    Path("/var/log/skewai").resolve(),
)


def _path() -> Path:
    """Resolve audit log path; jail outside data/ or /var/log/skewai."""
    raw = (os.getenv("SECURITY_AUDIT_LOG_PATH") or "").strip()
    if not raw:
        return _DEFAULT_PATH
    try:
        p = Path(raw).expanduser().resolve()
    except OSError:
        return _DEFAULT_PATH
    for root in _ALLOWED_LOG_ROOTS:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    # Outside jail → fall back under data/ with basename only
    safe_name = p.name if p.name.endswith(".jsonl") else "security_audit.jsonl"
    return (REPO_ROOT / "data" / safe_name).resolve()


def security_event(
    action: str,
    *,
    outcome: str = "success",
    actor: str | None = None,
    role: str | None = None,
    resource: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Record one security-relevant event. Never raises to callers."""
    event = {
        "event_id": new_ulid(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "outcome": outcome,
        "actor": actor or "anonymous",
        "role": role,
        "resource": resource,
        "ip": ip,
        "request_id": request_id,
        "detail": detail or {},
    }
    line = json.dumps(event, default=str, separators=(",", ":"))
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        _log.info("security_audit %s", line)
    except Exception as e:
        _log.warning("security_audit_write_failed: %s", e)
    return event


def read_recent(limit: int = 100) -> list[dict[str, Any]]:
    """Read last N events (for admin/ops; not a full query engine)."""
    path = _path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


__all__ = ["security_event", "read_recent"]
