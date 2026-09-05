"""Data-subject request tooling: export/delete by interaction (feature #34)."""

from __future__ import annotations

import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con


def export_interaction(interaction_id: str, *, redact_pii: bool = False) -> dict[str, Any]:
    """Export all ops rows linked to one interaction.

    redact_pii=False by default because DSR/legal export must be complete for
    the data subject. Pass redact_pii=True for support-screen views.
    """
    iid = interaction_id
    out: dict[str, Any] = {"interaction_id": iid, "exported_at": utc_now().isoformat() + "Z"}
    with ops_con(read_only=True) as con:
        for name, sql, params in (
            ("interaction", "SELECT * FROM interactions WHERE interaction_id = ?", [iid]),
            ("turns", "SELECT * FROM interaction_turns WHERE interaction_id = ? ORDER BY seq", [iid]),
            ("actions", "SELECT * FROM agent_actions WHERE interaction_id = ? ORDER BY ts", [iid]),
            ("cases", "SELECT * FROM cases WHERE interaction_id = ?", [iid]),
            (
                "version_stamps",
                "SELECT * FROM interaction_version_stamps WHERE interaction_id = ?",
                [iid],
            ),
        ):
            try:
                cur = con.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                for r in rows:
                    for k, v in list(r.items()):
                        if hasattr(v, "isoformat"):
                            r[k] = v.isoformat()
                out[name] = rows if name != "interaction" else (rows[0] if rows else None)
            except Exception as e:
                out[name] = {"error": f"{type(e).__name__}:{e}"}

        # notes for cases
        case_ids = [c["case_id"] for c in (out.get("cases") or []) if c.get("case_id")]
        notes = []
        for cid in case_ids:
            try:
                cur = con.execute(
                    "SELECT * FROM case_notes WHERE case_id = ?", [cid]
                )
                cols = [d[0] for d in cur.description]
                for r in cur.fetchall():
                    d = dict(zip(cols, r))
                    for k, v in list(d.items()):
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    notes.append(d)
            except Exception:
                pass
        out["case_notes"] = notes
    if redact_pii:
        try:
            from src.security.pii import redact_pii as _redact

            def _scrub(obj: Any) -> Any:
                if isinstance(obj, dict):
                    return {k: (_redact(v) if isinstance(v, str) else _scrub(v)) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_scrub(x) for x in obj]
                if isinstance(obj, str):
                    return _redact(obj)
                return obj

            for key in ("interaction", "turns", "actions", "cases", "case_notes"):
                if key in out:
                    out[key] = _scrub(out[key])
        except Exception:
            pass
    return out


def delete_interaction(interaction_id: str, *, mode: str = "erase") -> dict[str, Any]:
    """Delete linked ops rows for one interaction.

    Modes (audit 7.3 & 5.1 — hash chain vs erasure):
    - ``"erase"`` (default, backward compatible): hard delete. The contact
      is gone entirely; its chain segment cannot be re-verified afterward.
    - ``"tombstone"`` (recommended for regulated data): PII-bearing content
      (turn text, action summaries, evidence-pin bodies) is replaced with a
      dated tombstone and flagged ``erased``, while ``row_hash``/``prev_hash``
      linkage is preserved — ``verify_chain`` still passes and neighbors are
      unaffected. Merkle leaves (hashes of hashes) keep verifying.
    - ``"crypto_shred"``: destroys the per-subject Data Encryption Key (DEK)
      permanently rendering ciphertexts mathematically irrecoverable, and
      applies tombstoning without mutating historical chain hashes.
    """
    if mode not in ("erase", "tombstone", "crypto_shred"):
        raise ValueError("mode must be 'erase', 'tombstone', or 'crypto_shred'")
    if mode == "crypto_shred":
        from src.security.pii import SubjectKeyStore
        shredded = SubjectKeyStore.shred_dek(interaction_id)
        res = tombstone_interaction(interaction_id)
        res["crypto_shredded"] = shredded
        res["mode"] = "crypto_shred"
        return res
    if mode == "tombstone":
        return tombstone_interaction(interaction_id)
    iid = interaction_id
    deleted: dict[str, int] = {}
    with ops_con() as con:
        # case notes first
        case_ids = [
            r[0]
            for r in con.execute(
                "SELECT case_id FROM cases WHERE interaction_id = ?", [iid]
            ).fetchall()
        ]
        n = 0
        for cid in case_ids:
            con.execute("DELETE FROM case_notes WHERE case_id = ?", [cid])
            n += 1
        deleted["case_notes_batches"] = n
        from src.security.sql_ident import safe_column, safe_table

        for table, col in (
            ("cases", "interaction_id"),
            ("agent_actions", "interaction_id"),
            ("interaction_turns", "interaction_id"),
            ("interaction_version_stamps", "interaction_id"),
            ("risk_snapshots", "interaction_id"),
            ("interactions", "interaction_id"),
        ):
            try:
                t = safe_table(table)
                c = safe_column(col)
                before = con.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE {c} = ?", [iid]
                ).fetchone()[0]
                con.execute(f"DELETE FROM {t} WHERE {c} = ?", [iid])
                deleted[table] = int(before)
            except Exception:
                deleted[table] = -1
    return {"interaction_id": iid, "deleted": deleted, "ok": True}


def tombstone_interaction(interaction_id: str) -> dict[str, Any]:
    """Chain-preserving erasure for one interaction (audit 7.3).

    Replaces PII content with tombstones, keeps every hash link intact:
    - interaction_turns.text → tombstone, erased=TRUE
    - agent_actions input/output_summary → tombstone, erased=TRUE
      (row_hash/prev_hash untouched → verify_chain passes, linkage checked)
    - cited_evidence_snapshots body_json → tombstone, erased=TRUE
      (body_hash of the ORIGINAL kept alongside, so drift-audit can tell
      "erased by request" apart from "tampered")
    - interactions description/category/entity slots → cleared (operational
      copies; the case row keeps non-PII analytics fields)
    Structural rows (cases, interactions headers) are kept so corpus counts
    and foreign-key-shaped joins don't silently shift.
    """
    from src.data.timeutil import utc_now
    from src.qubot.evidence_pin import _ensure_pin_table

    iid = interaction_id
    stamp = f"[ERASED {utc_now().date().isoformat()} per erasure request]"
    out: dict[str, int] = {}
    with ops_con() as con:
        _ensure_pin_table(con)
        for table, col, idcol in (
            ("interaction_turns", "text", "interaction_id"),
            ("agent_actions", "input_summary", "interaction_id"),
        ):
            try:
                from src.security.sql_ident import safe_column, safe_table

                t = safe_table(table)
                c = safe_column(col)
                n = con.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE {idcol} = ?", [iid]
                ).fetchone()[0]
                con.execute(
                    f"UPDATE {t} SET {c} = ?, erased = TRUE WHERE {idcol} = ?",
                    [stamp, iid],
                )
                out[f"{table}.tombstoned"] = int(n)
            except Exception:
                out[f"{table}.tombstoned"] = -1
        try:
            n = con.execute(
                "UPDATE agent_actions SET output_summary = ?, erased = TRUE"
                " WHERE interaction_id = ?",
                [stamp, iid],
            )
            out["agent_actions.output_tombstoned"] = "ok"
        except Exception:
            out["agent_actions.output_tombstoned"] = "failed"
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM cited_evidence_snapshots WHERE interaction_id = ?",
                [iid],
            ).fetchone()[0]
            con.execute(
                "UPDATE cited_evidence_snapshots SET body_json = ?, erased = TRUE"
                " WHERE interaction_id = ?",
                ['{"erased": true}', iid],
            )
            out["pins.tombstoned"] = int(n)
        except Exception:
            out["pins.tombstoned"] = -1
        try:
            con.execute(
                "UPDATE interactions SET description = NULL, category = NULL,"
                " entity_1 = NULL, entity_2 = NULL, entity_3 = NULL"
                " WHERE interaction_id = ?",
                [iid],
            )
            out["interaction.slots_cleared"] = 1
        except Exception:
            out["interaction.slots_cleared"] = -1
    try:
        from src.security.audit_log import security_event

        security_event(
            "dsr.tombstone", outcome="success", resource=iid,
            detail={"tombstoned": out},
        )
    except Exception:
        pass
    return {"interaction_id": iid, "mode": "tombstone", "tombstoned": out, "ok": True}


__all__ = ["export_interaction", "delete_interaction", "tombstone_interaction"]
