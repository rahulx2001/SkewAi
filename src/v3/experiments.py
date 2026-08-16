"""AI experiment platform — versioned artifacts + control/candidate compare.

Offline-first: trials can be recorded from warehouse interaction outcomes or
synthetic eval metrics. No multi-cluster deploy required (modes are labels).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con
from src.ids import new_ulid

ARTIFACT_KINDS = frozenset(
    {"prompt", "workflow", "routing", "safety_policy", "retrieval"}
)
EXPERIMENT_MODES = frozenset({"ab", "shadow", "canary"})
EXPERIMENT_STATUSES = frozenset({"draft", "running", "completed", "rolled_back"})


def _now() -> datetime:
    from src.data.timeutil import utc_now

    return utc_now()


def _iso_row(d: dict[str, Any]) -> dict[str, Any]:
    from src.data.timeutil import to_iso_z

    out = dict(d)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = to_iso_z(v)
        if k in ("body_json", "metrics_json") and isinstance(v, str):
            try:
                out[k.replace("_json", "")] = json.loads(v)
            except Exception:
                pass
    return out


def register_artifact(
    *,
    kind: str,
    name: str,
    version: str,
    body: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"kind must be one of {sorted(ARTIFACT_KINDS)}")
    if not name.strip() or not version.strip():
        raise ValueError("name and version required")
    aid = "art_" + new_ulid()
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO ai_artifacts
            (artifact_id, kind, name, version, body_json, created_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                aid,
                kind,
                name.strip(),
                version.strip(),
                json.dumps(body or {}),
                now,
                notes or "",
            ],
        )
    return get_artifact(aid)  # type: ignore[return-value]


def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM ai_artifacts WHERE artifact_id = ?", [artifact_id]
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = _iso_row(dict(zip(cols, row)))
        if isinstance(d.get("body_json"), str):
            try:
                d["body"] = json.loads(d["body_json"])
            except Exception:
                d["body"] = {}
        return d


def list_artifacts(*, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        if kind:
            cur = con.execute(
                """
                SELECT * FROM ai_artifacts WHERE kind = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                [kind, limit],
            )
        else:
            cur = con.execute(
                "SELECT * FROM ai_artifacts ORDER BY created_at DESC LIMIT ?",
                [limit],
            )
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = _iso_row(dict(zip(cols, r)))
            try:
                d["body"] = json.loads(d.get("body_json") or "{}")
            except Exception:
                d["body"] = {}
            out.append(d)
    return out


def create_experiment(
    *,
    name: str,
    control_artifact_id: str,
    candidate_artifact_id: str,
    mode: str = "ab",
    description: str = "",
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("name required")
    if mode not in EXPERIMENT_MODES:
        raise ValueError(f"mode must be one of {sorted(EXPERIMENT_MODES)}")
    if not get_artifact(control_artifact_id):
        raise LookupError(f"control artifact not found: {control_artifact_id}")
    if not get_artifact(candidate_artifact_id):
        raise LookupError(f"candidate artifact not found: {candidate_artifact_id}")
    eid = "exp_" + new_ulid()
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO experiments
            (experiment_id, name, description, mode, status,
             control_artifact_id, candidate_artifact_id, created_at)
            VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
            """,
            [
                eid,
                name.strip(),
                description or "",
                mode,
                control_artifact_id,
                candidate_artifact_id,
                now,
            ],
        )
    return get_experiment(eid)  # type: ignore[return-value]


def get_experiment(experiment_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?", [experiment_id]
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = _iso_row(dict(zip(cols, row)))
        if isinstance(d.get("metrics_json"), str) and d["metrics_json"]:
            try:
                d["metrics"] = json.loads(d["metrics_json"])
            except Exception:
                d["metrics"] = {}
        else:
            d["metrics"] = None
        return d


def list_experiments(*, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        if status:
            cur = con.execute(
                """
                SELECT * FROM experiments WHERE status = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                [status, limit],
            )
        else:
            cur = con.execute(
                "SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?",
                [limit],
            )
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = _iso_row(dict(zip(cols, r)))
            if d.get("metrics_json"):
                try:
                    d["metrics"] = json.loads(d["metrics_json"])
                except Exception:
                    d["metrics"] = None
            out.append(d)
    return out


def record_trial(
    experiment_id: str,
    *,
    arm: str,
    interaction_id: str | None = None,
    resolution_ok: bool | None = None,
    escalated: bool | None = None,
    latency_ms: int | None = None,
    groundedness_ok: bool | None = None,
    hallucination_flag: bool | None = None,
    cost_units: float | None = None,
) -> dict[str, Any]:
    if arm not in ("control", "candidate"):
        raise ValueError("arm must be control or candidate")
    exp = get_experiment(experiment_id)
    if not exp:
        raise LookupError(f"experiment not found: {experiment_id}")
    tid = "trl_" + new_ulid()
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO experiment_trials
            (trial_id, experiment_id, arm, interaction_id, resolution_ok, escalated,
             latency_ms, groundedness_ok, hallucination_flag, cost_units, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                tid,
                experiment_id,
                arm,
                interaction_id,
                resolution_ok,
                escalated,
                latency_ms,
                groundedness_ok,
                hallucination_flag,
                cost_units,
                now,
            ],
        )
    return {
        "trial_id": tid,
        "experiment_id": experiment_id,
        "arm": arm,
        "interaction_id": interaction_id,
        "resolution_ok": resolution_ok,
        "escalated": escalated,
        "latency_ms": latency_ms,
        "groundedness_ok": groundedness_ok,
        "hallucination_flag": hallucination_flag,
        "cost_units": cost_units,
        "created_at": now.isoformat(),
    }


def _arm_stats(con, experiment_id: str, arm: str) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT
          COUNT(*) AS n,
          AVG(CASE WHEN resolution_ok THEN 1.0 ELSE 0.0 END) AS resolution_rate,
          AVG(CASE WHEN escalated THEN 1.0 ELSE 0.0 END) AS escalation_rate,
          AVG(latency_ms) AS avg_latency_ms,
          AVG(CASE WHEN groundedness_ok THEN 1.0 ELSE 0.0 END) AS groundedness_rate,
          AVG(CASE WHEN hallucination_flag THEN 1.0 ELSE 0.0 END) AS hallucination_rate,
          AVG(cost_units) AS avg_cost_units
        FROM experiment_trials
        WHERE experiment_id = ? AND arm = ?
        """,
        [experiment_id, arm],
    ).fetchone()
    keys = [
        "n",
        "resolution_rate",
        "escalation_rate",
        "avg_latency_ms",
        "groundedness_rate",
        "hallucination_rate",
        "avg_cost_units",
    ]
    d = dict(zip(keys, row)) if row else {k: None for k in keys}
    for k, v in list(d.items()):
        if isinstance(v, float):
            d[k] = round(v, 4)
        elif v is None and k == "n":
            d[k] = 0
    return d


def complete_experiment_report(experiment_id: str) -> dict[str, Any]:
    """Aggregate trial metrics for control vs candidate and mark completed."""
    exp = get_experiment(experiment_id)
    if not exp:
        raise LookupError(f"experiment not found: {experiment_id}")
    with ops_con() as con:
        control = _arm_stats(con, experiment_id, "control")
        candidate = _arm_stats(con, experiment_id, "candidate")
        # Winner heuristic: higher resolution, lower escalation, lower latency/cost
        score = lambda s: (
            float(s.get("resolution_rate") or 0)
            - float(s.get("escalation_rate") or 0)
            - (float(s.get("avg_latency_ms") or 0) / 10000.0)
            - float(s.get("avg_cost_units") or 0) * 0.01
            - float(s.get("hallucination_rate") or 0)
            + float(s.get("groundedness_rate") or 0) * 0.5
        )
        sc, sd = score(control), score(candidate)
        if control["n"] == 0 and candidate["n"] == 0:
            winner = "insufficient_data"
        elif sd > sc + 0.02:
            winner = "candidate"
        elif sc > sd + 0.02:
            winner = "control"
        else:
            winner = "tie"
        report = {
            "control": control,
            "candidate": candidate,
            "winner": winner,
            "score_control": round(sc, 4),
            "score_candidate": round(sd, 4),
            "recommendation": (
                "Promote candidate artifact to active deployment"
                if winner == "candidate"
                else "Keep control; investigate candidate failures"
                if winner == "control"
                else "Collect more trials or refine metrics"
            ),
        }
        now = _now()
        con.execute(
            """
            UPDATE experiments
            SET status = 'completed', completed_at = ?, metrics_json = ?
            WHERE experiment_id = ?
            """,
            [now, json.dumps(report), experiment_id],
        )
    out = get_experiment(experiment_id)
    assert out is not None
    out["metrics"] = report
    return out
