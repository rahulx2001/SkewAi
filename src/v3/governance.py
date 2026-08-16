"""AI governance — deployment history, activate/rollback, interaction version stamps.

Soft-activate: one deployment has status=active; prior active becomes inactive
or rolled_back. History is append-only (rows never deleted).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con
from src.domains.active_pack import resolve_active_pack_id
from src.ids import new_ulid

try:
    from src.domains.loader import load_pack
except Exception:  # pragma: no cover
    load_pack = None  # type: ignore


def _now() -> datetime:
    from src.data.timeutil import utc_now

    return utc_now()


def _iso_row(d: dict[str, Any]) -> dict[str, Any]:
    from src.data.timeutil import to_iso_z

    out = dict(d)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = to_iso_z(v)
        if k == "artifact_versions_json" and isinstance(v, str):
            try:
                out["artifact_versions"] = json.loads(v)
            except Exception:
                out["artifact_versions"] = {}
    return out


def create_deployment(
    *,
    label: str,
    artifact_versions: dict[str, str] | None = None,
    pack_version: str | None = None,
    note: str = "",
    activated_by: str = "operator",
) -> dict[str, Any]:
    if not label.strip():
        raise ValueError("label required")
    did = "dep_" + new_ulid()
    now = _now()
    pack_id = resolve_active_pack_id()
    if pack_version is None and load_pack is not None:
        try:
            pack_version = load_pack(pack_id).pack_version
        except Exception:
            pack_version = None
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO config_deployments
            (deployment_id, label, created_at, status, pack_version,
             artifact_versions_json, activated_by, note)
            VALUES (?, ?, ?, 'inactive', ?, ?, ?, ?)
            """,
            [
                did,
                label.strip(),
                now,
                pack_version,
                json.dumps(artifact_versions or {}),
                activated_by or "operator",
                note or "",
            ],
        )
    return get_deployment(did)  # type: ignore[return-value]


def get_deployment(deployment_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM config_deployments WHERE deployment_id = ?",
            [deployment_id],
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return _iso_row(dict(zip(cols, row)))


def get_active_deployment() -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute(
            """
            SELECT * FROM config_deployments
            WHERE status = 'active'
            ORDER BY activated_at DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return _iso_row(dict(zip(cols, row)))


def list_deployments(*, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        cur = con.execute(
            """
            SELECT * FROM config_deployments
            ORDER BY created_at DESC LIMIT ?
            """,
            [limit],
        )
        cols = [d[0] for d in cur.description]
        return [_iso_row(dict(zip(cols, r))) for r in cur.fetchall()]


def activate_deployment(
    deployment_id: str,
    *,
    activated_by: str = "operator",
) -> dict[str, Any]:
    """Make deployment active; deactivate previous active (soft)."""
    dep = get_deployment(deployment_id)
    if not dep:
        raise LookupError(f"deployment not found: {deployment_id}")
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            UPDATE config_deployments
            SET status = 'inactive', deactivated_at = ?
            WHERE status = 'active'
            """,
            [now],
        )
        con.execute(
            """
            UPDATE config_deployments
            SET status = 'active', activated_at = ?, deactivated_at = NULL,
                activated_by = ?
            WHERE deployment_id = ?
            """,
            [now, activated_by or "operator", deployment_id],
        )
    out = get_deployment(deployment_id)
    assert out is not None
    return out


def rollback_deployment(
    *,
    to_deployment_id: str | None = None,
    activated_by: str = "operator",
) -> dict[str, Any]:
    """Rollback active to a previous deployment (or previous inactive by time).

    Resolves and validates the target **before** any status mutation so a failed
    lookup never leaves zero active deployments. Previous active becomes
    ``rolled_back``; target becomes ``active`` in one connection.
    """
    active = get_active_deployment()
    previous_id = active["deployment_id"] if active else None
    now = _now()

    target_id = to_deployment_id
    if previous_id and target_id == previous_id:
        raise ValueError("cannot roll back to the deployment that is currently active")

    # Resolve target without mutating.
    with ops_con(read_only=True) as con:
        if not target_id:
            if previous_id:
                row = con.execute(
                    """
                    SELECT deployment_id FROM config_deployments
                    WHERE status = 'inactive'
                      AND deployment_id != ?
                    ORDER BY COALESCE(activated_at, created_at) DESC
                    LIMIT 1
                    """,
                    [previous_id],
                ).fetchone()
            else:
                row = con.execute(
                    """
                    SELECT deployment_id FROM config_deployments
                    WHERE status = 'inactive'
                    ORDER BY COALESCE(activated_at, created_at) DESC
                    LIMIT 1
                    """
                ).fetchone()
            if not row:
                raise LookupError("no prior deployment to roll back to")
            target_id = row[0]
        else:
            row = con.execute(
                "SELECT deployment_id FROM config_deployments WHERE deployment_id = ?",
                [target_id],
            ).fetchone()
            if not row:
                raise LookupError(f"deployment not found: {target_id}")

    with ops_con() as con:
        if previous_id:
            con.execute(
                """
                UPDATE config_deployments
                SET status = 'rolled_back', deactivated_at = ?
                WHERE deployment_id = ?
                """,
                [now, previous_id],
            )
        con.execute(
            """
            UPDATE config_deployments
            SET status = 'inactive', deactivated_at = ?
            WHERE status = 'active' AND deployment_id != ?
            """,
            [now, target_id],
        )
        con.execute(
            """
            UPDATE config_deployments
            SET status = 'active', activated_at = ?, deactivated_at = NULL,
                activated_by = ?
            WHERE deployment_id = ?
            """,
            [now, activated_by or "operator", target_id],
        )
    out = get_deployment(target_id)
    assert out is not None
    return out


def stamp_interaction(
    interaction_id: str,
    *,
    experiment_id: str | None = None,
) -> dict[str, Any] | None:
    """Record versions used for this interaction. Idempotent upsert."""
    with ops_con(read_only=True) as con:
        h = con.execute(
            """
            SELECT interaction_id, pack_id, pack_version
            FROM interactions WHERE interaction_id = ?
            """,
            [interaction_id],
        ).fetchone()
        if not h:
            return None
        pack_id, pack_version = h[1], h[2]

    active = get_active_deployment()
    deployment_id = active["deployment_id"] if active else None
    artifact_versions = {}
    if active and active.get("artifact_versions"):
        artifact_versions = active["artifact_versions"]
    elif active and active.get("artifact_versions_json"):
        try:
            artifact_versions = json.loads(active["artifact_versions_json"])
        except Exception:
            artifact_versions = {}

    now = _now()
    with ops_con() as con:
        exists = con.execute(
            """
            SELECT model_policy FROM interaction_version_stamps
            WHERE interaction_id = ?
            """,
            [interaction_id],
        ).fetchone()
        if exists:
            # Preserve mid-call prompt hashes in model_policy (do not clobber
            # with bare 'deterministic' when prompts already stamped).
            prev_policy = (exists[0] or "").strip()
            if not prev_policy or prev_policy == "deterministic":
                new_policy = "deterministic"
            else:
                new_policy = prev_policy
            con.execute(
                """
                UPDATE interaction_version_stamps
                SET stamped_at = ?, pack_id = ?, pack_version = ?,
                    deployment_id = COALESCE(?, deployment_id),
                    experiment_id = COALESCE(?, experiment_id),
                    artifact_versions_json = ?,
                    model_policy = ?
                WHERE interaction_id = ?
                """,
                [
                    now,
                    pack_id,
                    pack_version,
                    deployment_id,
                    experiment_id,
                    json.dumps(artifact_versions),
                    new_policy,
                    interaction_id,
                ],
            )
        else:
            con.execute(
                """
                INSERT INTO interaction_version_stamps
                (interaction_id, stamped_at, pack_id, pack_version, deployment_id,
                 experiment_id, artifact_versions_json, model_policy)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'deterministic')
                """,
                [
                    interaction_id,
                    now,
                    pack_id,
                    pack_version,
                    deployment_id,
                    experiment_id,
                    json.dumps(artifact_versions),
                ],
            )
    return get_stamp(interaction_id)


def get_stamp(interaction_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM interaction_version_stamps WHERE interaction_id = ?",
            [interaction_id],
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = _iso_row(dict(zip(cols, row)))
        if isinstance(d.get("artifact_versions_json"), str):
            try:
                d["artifact_versions"] = json.loads(d["artifact_versions_json"])
            except Exception:
                d["artifact_versions"] = {}
        return d


def stamp_and_maybe_learn(interaction_id: str) -> None:
    """Finalize hook: stamp versions + optional learning proposal. Never raises."""
    try:
        stamp_interaction(interaction_id)
    except Exception:
        pass
    try:
        from src.v3.learning import maybe_propose_from_interaction

        maybe_propose_from_interaction(interaction_id)
    except Exception:
        pass
