"""Per-vertical toggleable compliance packs + evidence templates."""

from __future__ import annotations

from typing import Any

from src.data.warehouse import ops_con

PACKS = {
    "21cfr11": {
        "title": "21 CFR Part 11",
        "vertical": "medical_maude",
        "controls": ["audit_trail", "electronic_signature", "record_retention"],
        "template": (
            "Part 11 evidence: closed hash-chain on agent_actions "
            "(prev_hash/row_hash), unique user attribution, and exportable "
            "Evidence Locker bundle for {record_id}."
        ),
    },
    "nhtsa_tread": {
        "title": "NHTSA TREAD",
        "vertical": "automotive_nhtsa",
        "controls": ["early_warning", "death_injury_reporting", "field_reports"],
        "template": (
            "TREAD evidence: weekly_anomalies z-scores, investigation "
            "{investigation_id}, and cited NHTSA record {record_id} pinned "
            "at write time."
        ),
    },
    "gdpr": {
        "title": "GDPR",
        "vertical": "consumer_cpsc",
        "controls": ["lawful_basis", "dsar", "erasure", "retention"],
        "template": (
            "GDPR evidence: consent row for {interaction_id}, DSR export path "
            "via dsr.py, and erasure request logged in security audit."
        ),
    },
}


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_toggles (
            pack_key VARCHAR PRIMARY KEY,
            enabled BOOLEAN NOT NULL
        )
        """
    )


def toggle_pack(key: str, enabled: bool = True) -> dict[str, Any]:
    if key not in PACKS:
        raise KeyError(key)
    with ops_con() as con:
        _ensure(con)
        exists = con.execute(
            "SELECT 1 FROM compliance_toggles WHERE pack_key = ?", [key]
        ).fetchone()
        if exists:
            con.execute(
                "UPDATE compliance_toggles SET enabled = ? WHERE pack_key = ?",
                [enabled, key],
            )
        else:
            con.execute(
                "INSERT INTO compliance_toggles (pack_key, enabled) VALUES (?, ?)",
                [key, enabled],
            )
    return {"key": key, "enabled": enabled, **PACKS[key]}


def is_enabled(key: str) -> bool:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                "SELECT enabled FROM compliance_toggles WHERE pack_key = ?", [key]
            ).fetchone()
        except Exception:
            return False
    return bool(row[0]) if row else False


def evidence_template(key: str, **ctx: str) -> dict[str, Any]:
    spec = PACKS[key]
    text = spec["template"]
    for k, v in ctx.items():
        text = text.replace("{" + k + "}", str(v))
    return {
        "key": key,
        "title": spec["title"],
        "vertical": spec["vertical"],
        "enabled": is_enabled(key),
        "controls": spec["controls"],
        "evidence_template": text,
    }


def list_packs() -> list[dict[str, Any]]:
    return [{"key": k, "enabled": is_enabled(k), **v} for k, v in PACKS.items()]


__all__ = ["PACKS", "toggle_pack", "is_enabled", "evidence_template", "list_packs"]
