"""Callback scheduling (feature #21).

When queues are long or a supervisor is unavailable, capture a callback slot
and fire a connector-shaped event into the outbox.
"""

from __future__ import annotations

import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS callbacks (
            callback_id VARCHAR PRIMARY KEY,
            interaction_id VARCHAR,
            case_id VARCHAR,
            pack_id VARCHAR,
            phone_or_channel VARCHAR,
            preferred_window VARCHAR,
            status VARCHAR,
            reason VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp,
            payload_json VARCHAR
        )
        """
    )


def schedule_callback(
    *,
    interaction_id: str | None,
    pack_id: str,
    phone_or_channel: str,
    preferred_window: str = "next_business_day",
    case_id: str | None = None,
    reason: str = "queue_or_supervisor",
) -> dict[str, Any]:
    cid = f"cb_{new_ulid()}"
    payload = {
        "event": "callback_requested",
        "callback_id": cid,
        "interaction_id": interaction_id,
        "case_id": case_id,
        "pack_id": pack_id,
        "phone_or_channel": phone_or_channel,
        "preferred_window": preferred_window,
        "reason": reason,
        "created_at": utc_now().isoformat(),
    }
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO callbacks
              (callback_id, interaction_id, case_id, pack_id, phone_or_channel,
               preferred_window, status, reason, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)
            """,
            [
                cid,
                interaction_id,
                case_id,
                pack_id,
                phone_or_channel,
                preferred_window,
                reason,
                json.dumps(payload),
            ],
        )
    # Best-effort connector outbox file (same family as alerts connectors)
    try:
        from pathlib import Path
        from src.config import REPO_ROOT

        out = REPO_ROOT / "data" / "connectors" / "outbox"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"callback_{cid}.json").write_text(json.dumps(payload, indent=2))
    except Exception:
        pass
    if interaction_id:
        try:
            from src.ledger import AgentAction, record_action

            record_action(
                AgentAction(
                    interaction_id=interaction_id,
                    agent="orchestrator",
                    action_type="callback_scheduled",
                    input_summary=phone_or_channel[:200],
                    output_summary=f"callback_id={cid}; window={preferred_window}",
                    case_id=case_id,
                    ok=True,
                )
            )
            payload["ledgered"] = True
        except Exception:
            payload["ledgered"] = False
    return {**payload, "status": "scheduled"}


def list_callbacks(*, status: str | None = "scheduled", limit: int = 50) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
        except Exception:
            return []
        sql = "SELECT callback_id, interaction_id, case_id, pack_id, phone_or_channel, preferred_window, status, reason, created_at FROM callbacks"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception:
            return []
    cols = [
        "callback_id",
        "interaction_id",
        "case_id",
        "pack_id",
        "phone_or_channel",
        "preferred_window",
        "status",
        "reason",
        "created_at",
    ]
    return [dict(zip(cols, r)) for r in rows]
