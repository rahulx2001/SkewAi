"""Returning-caller recognition (feature #14) — pilot voiceprint proxy.

Uses a stable hash of a speaker embedding vector (or of phone/ANI when no
audio). Matches against enterprise contact_memory + optional voiceprints table
in ops DB (created on demand).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.data.warehouse import ops_con
from src.enterprise.memory import entity_key, lookup_memory
from src.ids import new_ulid


def _ensure_table(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS voiceprints (
            voiceprint_id VARCHAR PRIMARY KEY,
            pack_id VARCHAR NOT NULL,
            fingerprint VARCHAR NOT NULL,
            entity_key VARCHAR,
            case_id VARCHAR,
            label VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp,
            UNIQUE (pack_id, fingerprint)
        )
        """
    )


def fingerprint_from_audio_features(features: list[float] | str) -> str:
    """Hash a speaker vector or ANI string into a short fingerprint."""
    if isinstance(features, str):
        raw = features.strip().lower().encode()
    else:
        raw = json.dumps([round(float(x), 4) for x in features], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def register_voiceprint(
    pack_id: str,
    fingerprint: str,
    *,
    entity_1: str | None = None,
    entity_2: str | None = None,
    entity_3: str | None = None,
    case_id: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    ek = entity_key(entity_1, entity_2, entity_3)
    vid = f"vp_{new_ulid()}"
    with ops_con() as con:
        _ensure_table(con)
        existing = con.execute(
            "SELECT voiceprint_id FROM voiceprints WHERE pack_id = ? AND fingerprint = ?",
            [pack_id, fingerprint],
        ).fetchone()
        if existing:
            con.execute(
                """
                UPDATE voiceprints
                SET case_id = COALESCE(?, case_id),
                    label = COALESCE(?, label),
                    entity_key = COALESCE(?, entity_key)
                WHERE pack_id = ? AND fingerprint = ?
                """,
                [case_id, label, ek or None, pack_id, fingerprint],
            )
            vid = existing[0]
        else:
            con.execute(
                """
                INSERT INTO voiceprints
                  (voiceprint_id, pack_id, fingerprint, entity_key, case_id, label)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [vid, pack_id, fingerprint, ek or None, case_id, label],
            )
    return {
        "voiceprint_id": vid,
        "pack_id": pack_id,
        "fingerprint": fingerprint,
        "entity_key": ek,
        "case_id": case_id,
    }


def match_caller(
    pack_id: str,
    fingerprint: str,
    *,
    entity_1: str | None = None,
    entity_2: str | None = None,
    entity_3: str | None = None,
) -> dict[str, Any]:
    """Return greeting hint if voiceprint or entity memory matches."""
    with ops_con(read_only=True) as con:
        try:
            _ensure_table(con)
        except Exception:
            pass
        try:
            row = con.execute(
                """
                SELECT voiceprint_id, entity_key, case_id, label
                FROM voiceprints
                WHERE pack_id = ? AND fingerprint = ?
                """,
                [pack_id, fingerprint],
            ).fetchone()
        except Exception:
            row = None
    mem = lookup_memory(pack_id, entity_1=entity_1, entity_2=entity_2, entity_3=entity_3)
    if row:
        case_id = row[2]
        label = row[3] or ""
        greeting = (
            f"Calling about the issue from case {case_id}?"
            if case_id
            else f"Welcome back{(' — ' + label) if label else ''}."
        )
        return {
            "matched": True,
            "source": "voiceprint",
            "case_id": case_id,
            "entity_key": row[1],
            "greeting": greeting,
            "memory": mem,
        }
    if mem:
        case_id = mem.get("last_case_id") or mem.get("case_id")
        greeting = (
            f"Calling about the issue from case {case_id}?"
            if case_id
            else "Welcome back — I see you've contacted us before."
        )
        return {
            "matched": True,
            "source": "entity_memory",
            "case_id": case_id,
            "entity_key": mem.get("entity_key"),
            "greeting": greeting,
            "memory": mem,
        }
    return {"matched": False, "source": None, "greeting": None, "memory": mem}
