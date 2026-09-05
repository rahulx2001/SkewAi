"""Content-addressed snapshots of *cited* domain rows (not a full dump).

On action write we pin sha256(canonical JSON) of each cited ``records`` row.
The auditor compares the pin to the live row and flags ``source-drifted``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import domain_con, ops_con
from src.ids import new_ulid


def _ensure_pin_table(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cited_evidence_snapshots (
            snapshot_id    VARCHAR PRIMARY KEY,
            action_id      VARCHAR NOT NULL,
            interaction_id VARCHAR,
            pack_id        VARCHAR NOT NULL,
            evidence_id    VARCHAR NOT NULL,
            body_json      TEXT NOT NULL,
            body_hash      VARCHAR NOT NULL,
            pinned_at      TIMESTAMP NOT NULL,
            erased         BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )
    try:
        con.execute(
            "ALTER TABLE cited_evidence_snapshots ADD COLUMN erased BOOLEAN"
        )
    except Exception:
        pass


def canonical_row_hash(row: dict[str, Any]) -> str:
    """Stable hash excluding volatile columns + normalized timestamps."""
    clean: dict[str, Any] = {}
    for k, v in (row or {}).items():
        if k in {"embedding"}:
            continue
        try:
            from datetime import datetime as _dt

            if isinstance(v, _dt):
                clean[k] = v.replace(tzinfo=None).isoformat()
                continue
        except Exception:
            pass
        clean[k] = str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
    body = json.dumps(clean, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _canonical_body(row: dict[str, Any]) -> tuple[str, str]:
    clean: dict[str, Any] = {}
    for k, v in (row or {}).items():
        if k in {"embedding"}:
            continue
        try:
            from datetime import datetime as _dt

            if isinstance(v, _dt):
                clean[k] = v.replace(tzinfo=None).isoformat()
                continue
        except Exception:
            pass
        clean[k] = str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
    body = json.dumps(clean, sort_keys=True, default=str, separators=(",", ":"))
    return body, hashlib.sha256(body.encode("utf-8")).hexdigest()


def fetch_record_row(pack_id: str, record_id: str) -> dict[str, Any] | None:
    try:
        with domain_con(pack_id) as con:
            cur = con.execute("SELECT * FROM records WHERE record_id = ?", [record_id])
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
    except FileNotFoundError:
        return None


def fetch_record_rows(pack_id: str, record_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One domain read for many record_ids."""
    ids = [str(r) for r in record_ids if r]
    if not pack_id or not ids:
        return {}
    try:
        with domain_con(pack_id) as con:
            ph = ",".join("?" * len(ids))
            cur = con.execute(
                f"SELECT * FROM records WHERE record_id IN ({ph})",
                ids,
            )
            cols = [d[0] for d in cur.description]
            out: dict[str, dict[str, Any]] = {}
            for raw in cur.fetchall():
                rec = {k: v for k, v in zip(cols, raw) if k != "embedding"}
                rid = str(rec.get("record_id") or "")
                if rid:
                    out[rid] = rec
            return out
    except FileNotFoundError:
        return {}


def fetch_advisory_rows(pack_id: str, advisory_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Batch fetch advisories (recall answers need drift protection too)."""
    ids = [str(a) for a in advisory_ids if a]
    if not pack_id or not ids:
        return {}
    try:
        with domain_con(pack_id) as con:
            ph = ",".join("?" * len(ids))
            cur = con.execute(
                f"SELECT * FROM advisories WHERE advisory_id IN ({ph})",
                ids,
            )
            cols = [d[0] for d in cur.description]
            return {str(dict(zip(cols, r)).get("advisory_id")): dict(zip(cols, r)) for r in cur.fetchall()}
    except FileNotFoundError:
        return {}


def fetch_cluster_rows(pack_id: str, cluster_ids: list[str | int]) -> dict[str, dict[str, Any]]:
    ids: list[int] = []
    for c in cluster_ids:
        try:
            ids.append(int(str(c)))
        except (ValueError, TypeError):
            continue
    if not pack_id or not ids:
        return {}
    try:
        with domain_con(pack_id) as con:
            ph = ",".join("?" * len(ids))
            cur = con.execute(
                f"SELECT * FROM clusters WHERE cluster_id IN ({ph}) AND pack_id = ?",
                [*ids, pack_id],
            )
            cols = [d[0] for d in cur.description]
            out = {}
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                out[str(d.get("cluster_id"))] = d
            return out
    except FileNotFoundError:
        return {}


def fetch_case_rows(case_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [str(c) for c in case_ids if c]
    if not ids:
        return {}
    with ops_con() as con:
        try:
            ph = ",".join("?" * len(ids))
            cur = con.execute(f"SELECT * FROM cases WHERE case_id IN ({ph})", ids)
        except Exception:
            return {}
        cols = [d[0] for d in cur.description]
        return {str(dict(zip(cols, r)).get("case_id")): dict(zip(cols, r)) for r in cur.fetchall()}


def fetch_rows_by_type(pack_id: str, evidence_ids: list[Any]) -> dict[str, dict[str, Any]]:
    """Route each evidence_id to its table. Keys are the raw evidence_ids."""
    rec_ids, adv_ids, clu_ids, case_ids = [], [], [], []
    for e in evidence_ids:
        s = str(e or "").strip()
        if not s:
            continue
        if s.startswith("case_"):
            case_ids.append(s)
        elif s.isdigit():
            clu_ids.append(s)
        elif "V-" in s or __import__("re").match(r"^\d{2}[A-Z]-\d+$", s):
            adv_ids.append(s)
        else:
            rec_ids.append(s)
    out: dict[str, dict[str, Any]] = {}
    out.update(fetch_record_rows(pack_id, rec_ids))
    out.update(fetch_advisory_rows(pack_id, adv_ids))
    out.update(fetch_cluster_rows(pack_id, clu_ids))
    out.update(fetch_case_rows(case_ids))
    # Investigations (ops)
    inv_ids = [str(e) for e in evidence_ids if str(e).startswith("inv_")]
    if inv_ids:
        with ops_con() as con:
            try:
                ph = ",".join("?" * len(inv_ids))
                cur = con.execute(
                    f"SELECT * FROM investigations WHERE investigation_id IN ({ph})", inv_ids
                )
                cols = [d[0] for d in cur.description]
                for r in cur.fetchall():
                    d = dict(zip(cols, r))
                    out[str(d.get("investigation_id"))] = d
            except Exception:
                pass
    return out


def insert_pins_on_con(
    con,
    *,
    action_id: str,
    interaction_id: str | None,
    pack_id: str,
    rows: dict[str, dict[str, Any]],
) -> int:
    _ensure_pin_table(con)
    # UNIQUE(action_id, evidence_id) — re-audit must not double-insert
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_pins_action_evidence ON cited_evidence_snapshots (action_id, evidence_id)"
        )
    except Exception:
        pass
    n = 0
    for rid, row in rows.items():
        body, h = _canonical_body(row)
        try:
            con.execute(
                """
                INSERT INTO cited_evidence_snapshots
                (snapshot_id, action_id, interaction_id, pack_id, evidence_id,
                 body_json, body_hash, pinned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    "pin_" + new_ulid(),
                    action_id,
                    interaction_id,
                    pack_id,
                    rid,
                    body,
                    h,
                    utc_now(),
                ],
            )
            n += 1
        except Exception:
            continue
    return n


def pin_cited_records(
    *,
    action_id: str,
    interaction_id: str | None,
    pack_id: str,
    evidence_ids: list[Any],
) -> int:
    """Snapshot each cited id that exists (records/advisories/clusters/cases)."""
    if not pack_id or not evidence_ids:
        return 0
    found = fetch_rows_by_type(pack_id, [str(e) for e in evidence_ids])
    if not found:
        return 0
    with ops_con() as con:
        return insert_pins_on_con(
            con,
            action_id=action_id,
            interaction_id=interaction_id,
            pack_id=pack_id,
            rows=found,
        )


def _live_row_for_drift(pack_id: str, eid: str) -> dict[str, Any] | None:
    s = str(eid)
    if s.startswith("case_"):
        return fetch_case_rows([s]).get(s)
    if s.isdigit():
        return fetch_cluster_rows(pack_id, [s]).get(s)
    if "V-" in s or __import__("re").match(r"^\d{2}[A-Z]-\d+$", s):
        rows = fetch_advisory_rows(pack_id, [s])
        if s in rows:
            return rows[s]
    if s.startswith("inv_"):
        with ops_con() as con:
            try:
                cur = con.execute(
                    "SELECT * FROM investigations WHERE investigation_id = ?", [s]
                )
                row = cur.fetchone()
                if not row:
                    return None
                return dict(zip([d[0] for d in cur.description], row))
            except Exception:
                return None
    return fetch_record_row(pack_id, s)


def detect_source_drift(action_id: str) -> list[dict[str, Any]]:
    """Return pins whose live source row no longer matches the snapshot hash."""
    with ops_con(read_only=True) as con:
        try:
            try:
                rows = con.execute(
                    """
                    SELECT evidence_id, pack_id, body_hash, body_json, erased
                    FROM cited_evidence_snapshots WHERE action_id = ?
                    """,
                    [action_id],
                ).fetchall()
            except Exception:
                rows = [
                    (*r, False)
                    for r in con.execute(
                        """
                        SELECT evidence_id, pack_id, body_hash, body_json
                        FROM cited_evidence_snapshots WHERE action_id = ?
                        """,
                        [action_id],
                    ).fetchall()
                ]
        except Exception:
            return []
    drifted: list[dict[str, Any]] = []
    for eid, pack_id, pinned_hash, _body, *rest in rows:
        if rest and rest[0]:
            # Erased by request (audit 7.3): not drift, not tampering.
            # Reported distinctly so audits stay truthful.
            drifted.append(
                {"evidence_id": eid, "reason": "erased", "pinned_hash": pinned_hash}
            )
            continue
        live = _live_row_for_drift(str(pack_id), str(eid))
        if live is None:
            drifted.append(
                {"evidence_id": eid, "reason": "source_row_missing", "pinned_hash": pinned_hash}
            )
            continue
        now_hash = canonical_row_hash(live)
        if now_hash != pinned_hash:
            drifted.append(
                {
                    "evidence_id": eid,
                    "reason": "source-drifted",
                    "pinned_hash": pinned_hash,
                    "live_hash": now_hash,
                }
            )
    return drifted


def snapshots_for_action(action_id: str) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            cur = con.execute(
                """
                SELECT snapshot_id, evidence_id, pack_id, body_json, body_hash
                FROM cited_evidence_snapshots WHERE action_id = ?
                """,
                [action_id],
            )
        except Exception:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


__all__ = [
    "canonical_row_hash",
    "fetch_record_row",
    "fetch_record_rows",
    "fetch_advisory_rows",
    "fetch_cluster_rows",
    "fetch_case_rows",
    "fetch_rows_by_type",
    "pin_cited_records",
    "insert_pins_on_con",
    "detect_source_drift",
    "snapshots_for_action",
]
