"""Scenario playbook builder — multi-step customer scripts for reusable sims.

Beyond count-based corpus simulate: save named step lists and run them through
the real orchestrator (when pack/domain available) or dry-run validation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.data.warehouse import ops_con
from src.ids import new_ulid


def _now() -> datetime:
    from src.data.timeutil import utc_now

    return utc_now()


def validate_scenario_steps(
    steps: list[dict[str, Any]] | None,
    *,
    name: str | None = None,
    pack_id: str | None = None,
) -> dict[str, Any]:
    """Pure validation for playbook steps (no DB). Used by API + create_scenario."""
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    if name is not None and not str(name).strip():
        errors.append({"field": "name", "message": "name required"})
    if pack_id is not None and not str(pack_id).strip():
        errors.append({"field": "pack_id", "message": "pack_id required"})
    if steps is None or not isinstance(steps, list):
        errors.append({"field": "steps", "message": "steps must be a non-empty list"})
        return {"ok": False, "errors": errors, "warnings": warnings, "step_count": 0}
    if len(steps) == 0:
        errors.append({"field": "steps", "message": "steps must be a non-empty list"})
    if len(steps) > 40:
        errors.append({"field": "steps", "message": "at most 40 steps allowed"})
    cleaned: list[dict[str, Any]] = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            errors.append({"field": f"steps[{i}]", "message": "step must be an object"})
            continue
        text = (s.get("text") or "").strip()
        if not text:
            errors.append({"field": f"steps[{i}].text", "message": "step needs non-empty text"})
            continue
        if len(text) > 2000:
            errors.append(
                {"field": f"steps[{i}].text", "message": "step text max 2000 characters"}
            )
            continue
        speaker = (s.get("speaker") or "customer").strip().lower()
        if speaker not in ("customer", "agent", "supervisor"):
            warnings.append(f"steps[{i}].speaker '{speaker}' coerced to customer")
            speaker = "customer"
        cleaned.append({"speaker": speaker, "text": text})
    if len(cleaned) == 1:
        warnings.append("single-step scenarios produce short contacts; consider 2+ turns")
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "step_count": len(cleaned),
        "steps": cleaned if not errors else steps,
    }


def create_scenario(
    *,
    pack_id: str,
    name: str,
    steps: list[dict[str, Any]],
    description: str = "",
) -> dict[str, Any]:
    check = validate_scenario_steps(steps, name=name, pack_id=pack_id)
    if not check["ok"]:
        msgs = "; ".join(e["message"] for e in check["errors"])
        raise ValueError(msgs or "invalid scenario")
    steps = check["steps"]
    sid = "scn_" + new_ulid()
    now = _now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO scenarios
            (scenario_id, pack_id, name, description, steps_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                sid,
                pack_id,
                name.strip(),
                description or "",
                json.dumps(steps),
                now,
                now,
            ],
        )
    return get_scenario(sid)  # type: ignore[return-value]


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    with ops_con(read_only=True) as con:
        cur = con.execute(
            "SELECT * FROM scenarios WHERE scenario_id = ?", [scenario_id]
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))
    if isinstance(d.get("steps_json"), str):
        try:
            d["steps"] = json.loads(d["steps_json"])
        except Exception:
            d["steps"] = []
    else:
        d["steps"] = []
    for k in ("created_at", "updated_at"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


def list_scenarios(pack_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 200)
    with ops_con(read_only=True) as con:
        if pack_id:
            cur = con.execute(
                """
                SELECT scenario_id, pack_id, name, description, created_at, updated_at, steps_json
                FROM scenarios WHERE pack_id = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                [pack_id, limit],
            )
        else:
            cur = con.execute(
                """
                SELECT scenario_id, pack_id, name, description, created_at, updated_at, steps_json
                FROM scenarios ORDER BY updated_at DESC LIMIT ?
                """,
                [limit],
            )
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            try:
                steps = json.loads(d.pop("steps_json") or "[]")
            except Exception:
                steps = []
            d["step_count"] = len(steps)
            d["steps"] = steps
            for k in ("created_at", "updated_at"):
                if isinstance(d.get(k), datetime):
                    d[k] = d[k].isoformat()
            out.append(d)
    return out


def delete_scenario(scenario_id: str) -> bool:
    with ops_con() as con:
        before = con.execute(
            "SELECT 1 FROM scenarios WHERE scenario_id = ?", [scenario_id]
        ).fetchone()
        if not before:
            return False
        con.execute("DELETE FROM scenarios WHERE scenario_id = ?", [scenario_id])
    return True


async def run_scenario(scenario_id: str) -> dict[str, Any]:
    """Run a saved scenario through the real orchestrator (deterministic agents)."""
    scn = get_scenario(scenario_id)
    if not scn:
        raise LookupError(f"scenario not found: {scenario_id}")
    steps = scn.get("steps") or []
    pack_id = scn["pack_id"]

    from src.agents.base import InteractionContext
    from src.agents.orchestrator import Orchestrator, OrchestratorHooks
    from src.domains.loader import load_pack
    from src.ids import new_ulid

    # OrchestratorHooks is a dataclass of callables — bind methods carefully.
    turns: list[dict[str, Any]] = []
    ended: dict[str, Any] | None = None

    async def _turn(text: str, meta: dict[str, Any]) -> None:
        turns.append({"text": text, "meta": meta})

    async def _ended(payload: dict[str, Any]) -> None:
        nonlocal ended
        ended = dict(payload)

    hooks = OrchestratorHooks(
        emit_customer_turn=_turn,
        emit_interaction_ended=_ended,
    )
    pack = load_pack(pack_id, reload=True)
    iid = "int_" + new_ulid()
    orch = Orchestrator(
        interaction_id=iid,
        pack=pack,
        channel="simulated",
        hooks=hooks,
    )
    # Persist interaction header the same way API start does (minimal).
    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con as _ops

    with _ops() as con:
        con.execute(
            """
            INSERT INTO interactions (
                interaction_id, pack_id, pack_version, started_at, channel, status
            ) VALUES (?, ?, ?, ?, 'simulated', 'active')
            """,
            [iid, pack.id, pack.pack_version, utc_now()],
        )

    await orch.start()
    for step in steps:
        text = (step.get("text") or "").strip()
        if not text:
            continue
        await orch.handle_customer_turn(text)
        if orch.ctx.state in ("DONE", "ABANDONED"):
            break
    if orch.ctx.state not in ("DONE", "ABANDONED"):
        await orch.hangup()

    return {
        "scenario_id": scenario_id,
        "interaction_id": iid,
        "pack_id": pack_id,
        "steps_run": len(steps),
        "agent_turns": len(turns),
        "state": orch.ctx.state,
        "case_id": getattr(orch.ctx, "case_id", None),
        "ended": ended,
    }
