"""Active domain-pack resolution (Settings UI + API + contact start + health).

Source of truth when present:
  ``{FRONTLINE_DB_PATH parent}/active_pack.json``  →  ``{"pack_id": "..."}``

Fallback: ``DOMAIN_PACK`` env / ``settings.domain_pack``.

Settings UI and ``PUT /api/packs/active`` write the override file; contact
start and ``/health`` must read the same store (not env alone).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.config import settings

_ACTIVE_PACK_FILE: Path = settings.frontline_db_path.parent / "active_pack.json"


def active_pack_path() -> Path:
    return _ACTIVE_PACK_FILE


def resolve_active_pack_id() -> str:
    """Return the pack id live contacts and health should use."""
    path = _ACTIVE_PACK_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = (data.get("pack_id") or "").strip()
            if pid:
                return pid
        except Exception:
            pass
    return settings.domain_pack


def set_active_pack_id(pack_id: str) -> str:
    """Persist override (same file Settings / packs API write). Returns pack_id."""
    path = _ACTIVE_PACK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pack_id": pack_id}, indent=2) + "\n", encoding="utf-8")
    return pack_id


def clear_active_pack_override() -> None:
    """Remove override so env/default applies (tests)."""
    path = _ACTIVE_PACK_FILE
    if path.exists():
        path.unlink()


__all__ = [
    "resolve_active_pack_id",
    "set_active_pack_id",
    "clear_active_pack_override",
    "active_pack_path",
]
