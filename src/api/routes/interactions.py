"""REST + WS routes for interactions.

Endpoints:
  POST   /api/interactions/start              → create + open WS
  GET    /api/interactions                    → list (filter by status)
  GET    /api/interactions/{id}               → header + turns + actions
  POST   /api/interactions/{id}/end           → end the interaction
  POST   /api/interactions/{id}/takeover     → supervisor takes over
  POST   /api/interactions/{id}/release      → supervisor releases
  WS     /ws/interaction/{id}                 → bidirectional contact stream
  WS     /ws/console                          → live console feed
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from src.agents.orchestrator import (
    Orchestrator,
    OrchestratorHooks,
    create_interaction,
)
from src.api.auth import authenticate_websocket, check_api_key, require_api_key
from src.api.frontline_gate import frontline_enabled
from src.api.limiter import limiter
from src.channels.web_voice import WebVoiceChannel
from src.data.warehouse import ops_con

router = APIRouter(
    prefix="/api/interactions",
    tags=["interactions"],
    # PII surface: list/detail require key when FRONTLINE_API_KEY is set.
    dependencies=[Depends(require_api_key)],
)
# WebSocket routes live at the root path (/ws/interaction/{id} and /ws/console)
# and are registered directly on the app in src/api/main.py — there is no
# separate WS APIRouter (a previous ws_router here was never populated/mounted).


# ── In-memory registry of active orchestrators (one per interaction) ─────────
# Exclusive customer WS attach; per-entry lock for turn/takeover races;
# orphan TTL reaps start-without-WS entries.

_ORPHAN_TTL_S = 300.0  # 5 minutes without customer WS attach


@dataclass
class ActiveEntry:
    orch: Orchestrator
    created_at: float = field(default_factory=time.monotonic)
    ws_attached: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_active: dict[str, ActiveEntry] = {}
_active_lock = asyncio.Lock()


def _json_safe(value: Any) -> Any:
    """Make DuckDB / Python values JSON-serializable for WebSocket frames (UTC Z)."""
    from src.api.jsonutil import json_safe as _js

    return _js(value)


def activity_frame_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Build a console ``agent_activity`` payload safe for ``send_json``."""
    r = dict(row)
    ev = r.get("evidence_ids")
    if isinstance(ev, str):
        try:
            r["evidence_ids"] = json.loads(ev)
        except json.JSONDecodeError:
            r["evidence_ids"] = []
    return {"type": "agent_activity", **{k: _json_safe(v) for k, v in r.items()}}


def fetch_agent_actions_since(since: datetime, limit: int = 50) -> list[dict[str, Any]]:
    """Load agent_actions newer than ``since`` (real ops path used by console WS)."""
    from src.data.timeutil import to_naive_utc

    # Compare on naive-UTC basis so session TZ cannot drop recent rows.
    since_n = to_naive_utc(since)
    with ops_con(read_only=True) as con:
        cur = con.execute(
            """
            SELECT action_id, interaction_id, agent, action_type,
                   output_summary, evidence_ids, ts
            FROM agent_actions
            WHERE ts > ?
            ORDER BY ts
            LIMIT ?
            """,
            [since_n, limit],
        )
        cols = [d[0] for d in con.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _sweep_stale_active_db_rows(registry_ids: set[str] | None = None) -> list[str]:
    """Mark ops DB rows still ``status='active'`` but not in the live registry.

    Covers zombie contacts left after hangup-while-supervised failures or
    process restarts where the in-memory registry is empty.
    """
    live = registry_ids if registry_ids is not None else set(_active.keys())
    closed: list[str] = []
    try:
        with ops_con() as con:
            rows = con.execute(
                "SELECT interaction_id FROM interactions WHERE status = 'active'"
            ).fetchall()
            from src.data.timeutil import utc_now

            now = utc_now()
            for (iid,) in rows:
                if iid in live:
                    continue
                con.execute(
                    """
                    UPDATE interactions
                    SET status = 'failed',
                        ended_at = COALESCE(ended_at, ?),
                        outcome = COALESCE(outcome, 'orphan_db_sweep')
                    WHERE interaction_id = ? AND status = 'active'
                    """,
                    [now, iid],
                )
                closed.append(iid)
    except Exception:
        pass
    return closed


async def _reap_orphans_unlocked() -> list[str]:
    """Drop registry entries that never attached a WS within TTL. Caller holds _active_lock."""
    now = time.monotonic()
    dead = [
        iid
        for iid, e in _active.items()
        if (not e.ws_attached) and (now - e.created_at) > _ORPHAN_TTL_S
    ]
    for iid in dead:
        entry = _active.pop(iid, None)
        if entry is None:
            continue
        try:
            if entry.orch.ctx.state not in ("DONE", "ABANDONED"):
                await entry.orch.hangup()
        except Exception:
            pass
        try:
            from src.data.timeutil import utc_now

            with ops_con() as con:
                con.execute(
                    """
                    UPDATE interactions
                    SET status = 'failed',
                        ended_at = COALESCE(ended_at, ?),
                        outcome = COALESCE(outcome, 'orphan_timeout')
                    WHERE interaction_id = ? AND status = 'active'
                    """,
                    [utc_now(), iid],
                )
        except Exception:
            pass
    # Also close DB-only zombies that no longer have a registry entry.
    dead.extend(_sweep_stale_active_db_rows(set(_active.keys())))
    return dead


async def reap_orphans() -> list[str]:
    """Public reaper (startup / tests): registry TTL + DB active-row sweep."""
    async with _active_lock:
        return await _reap_orphans_unlocked()


async def _get_entry(interaction_id: str) -> ActiveEntry:
    async with _active_lock:
        await _reap_orphans_unlocked()
        entry = _active.get(interaction_id)
    if not entry:
        raise HTTPException(
            status_code=404, detail=f"active interaction not found: {interaction_id}"
        )
    return entry


async def _get_active(interaction_id: str) -> Orchestrator:
    return (await _get_entry(interaction_id)).orch


async def _register(interaction_id: str, orch: Orchestrator) -> None:
    async with _active_lock:
        # Register first so DB sweep does not treat this row as a zombie.
        _active[interaction_id] = ActiveEntry(orch=orch)
        await _reap_orphans_unlocked()


async def _unregister(interaction_id: str) -> None:
    async with _active_lock:
        _active.pop(interaction_id, None)


async def _attach_customer_ws(interaction_id: str) -> ActiveEntry:
    """Exclusive attach: second customer WS is rejected with 409 semantics."""
    async with _active_lock:
        await _reap_orphans_unlocked()
        entry = _active.get(interaction_id)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"active interaction not found: {interaction_id}"
            )
        if entry.ws_attached:
            raise HTTPException(
                status_code=409,
                detail=f"interaction already has an active customer WebSocket: {interaction_id}",
            )
        entry.ws_attached = True
        return entry


async def _mark_failed(interaction_id: str, reason: str) -> None:
    try:
        from src.data.timeutil import utc_now

        with ops_con() as con:
            con.execute(
                """
                UPDATE interactions
                SET status = 'failed',
                    ended_at = COALESCE(ended_at, ?),
                    outcome = ?
                WHERE interaction_id = ?
                  AND status IN ('active', 'abandoned')
                """,
                [utc_now(), reason[:200], interaction_id],
            )
    except Exception:
        pass


# ── REST ─────────────────────────────────────────────────────────────────────


@router.post("/start")
@limiter.limit("30 per minute")
async def start_interaction(
    request: Request,
    channel: str = "web_voice",
    _auth: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """Create an interaction + return the WS URL + greeting."""
    from src.domains.active_pack import resolve_active_pack_id
    from src.ops.drain import ServiceDrainingError

    pack_id = resolve_active_pack_id()
    try:
        orch, greeting = await create_interaction(channel=channel, pack_id=pack_id)
    except ServiceDrainingError as e:
        raise HTTPException(
            status_code=503,
            detail=str(e) or "service_draining: not accepting new contacts",
        ) from e
    await _register(orch.ctx.interaction_id, orch)
    pack = orch.ctx.pack
    return {
        "interaction_id": orch.ctx.interaction_id,
        "ws_url": f"/ws/interaction/{orch.ctx.interaction_id}",
        "greeting_text": greeting,
        "pack": {
            "id": pack.id,
            "display_name": pack.display_name,
            "entity_labels": pack.entity_labels,
            "pack_version": pack.pack_version,
        },
    }


@router.post("/ingest")
@limiter.limit("30 per minute")
async def ingest_interaction(
    request: Request,
    body: dict[str, Any] | None = None,
    _auth: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """Non-conversational complaint ingest (ticket/webhook path)."""
    from src.frontline.ingest import ingest_complaint

    payload = body if isinstance(body, dict) else {}
    if not payload:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    try:
        result = await ingest_complaint(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}") from e
    # Register only if still active (pipeline may already be DONE)
    if result.get("state") not in ("DONE", "ABANDONED"):
        try:
            from src.agents.orchestrator import Orchestrator  # noqa: F401

            # leave unregistered; ingest path is fire-and-finish
            pass
        except Exception:
            pass
    return result


@router.get("")
async def list_interactions(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List interactions (optionally filter by status). Paginated."""
    from src.api.jsonutil import json_safe_rows
    from src.api.pagination import clamp_limit, page_meta, resolve_offset

    lim = clamp_limit(limit)
    off = resolve_offset(offset=offset, cursor=cursor)
    sql = "SELECT * FROM interactions"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params.extend([lim + 1, off])
    with ops_con(read_only=True) as con:
        cur = con.execute(sql, params)
        cols = [d[0] for d in con.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    has_extra = len(rows) > lim
    page = rows[:lim]
    total = None if has_extra else off + len(page)
    return {
        "interactions": json_safe_rows(page),
        "count": len(page),
        "pagination": page_meta(limit=lim, offset=off, returned=len(page), total=total),
    }


@router.get("/{interaction_id}")
async def get_interaction(interaction_id: str) -> dict[str, Any]:
    """Return the interaction header + turns + actions for replay."""
    from src.qubot.retrievers import contact_audit

    try:
        data = contact_audit(interaction_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"interaction not found: {interaction_id}")
    return data


@router.post("/{interaction_id}/end")
async def end_interaction(
    interaction_id: str,
    _auth: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """End the interaction (customer hung up via REST instead of WS)."""
    entry = await _get_entry(interaction_id)
    async with entry.lock:
        await entry.orch.hangup()
    await _unregister(interaction_id)
    return {"interaction_id": interaction_id, "status": entry.orch.ctx.state}


@router.post("/{interaction_id}/takeover")
async def takeover(
    interaction_id: str,
    _auth: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """Supervisor takes over the conversation."""
    entry = await _get_entry(interaction_id)
    async with entry.lock:
        await entry.orch.takeover()
    return {
        "interaction_id": interaction_id,
        "state": entry.orch.ctx.state,
        "supervised": True,
    }


@router.post("/{interaction_id}/release")
async def release(
    interaction_id: str,
    _auth: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """Supervisor releases; AI resumes."""
    entry = await _get_entry(interaction_id)
    async with entry.lock:
        await entry.orch.release()
    return {
        "interaction_id": interaction_id,
        "state": entry.orch.ctx.state,
        "supervised": False,
    }


# ── WebSocket: per-interaction + console fan-out ─────────────────────────────

_console_subscribers: set[WebSocket] = set()
_console_sub_lock = asyncio.Lock()


async def _broadcast_console(msg: dict[str, Any]) -> None:
    """Push a frame to every live Live Console WebSocket (H6)."""
    dead: list[WebSocket] = []
    async with _console_sub_lock:
        subs = list(_console_subscribers)
    for ws in subs:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    if dead:
        async with _console_sub_lock:
            for ws in dead:
                _console_subscribers.discard(ws)


class _WSHooks(OrchestratorHooks):
    """Hooks that bridge the orchestrator to the customer WS + console fan-out."""

    def __init__(self, channel: WebVoiceChannel, interaction_id: str) -> None:
        # Do NOT call OrchestratorHooks.__init__: the dataclass would set every
        # hook field to None and shadow the methods defined below.
        self._channel = channel
        self._interaction_id = interaction_id

    async def emit_customer_turn(self, text: str, meta: dict[str, Any]) -> None:
        await self._channel.send_turn(text, speaker=meta.get("speaker", "agent"), meta=meta)
        await _broadcast_console({
            "type": "agent_turn",
            "interaction_id": self._interaction_id,
            "speaker": meta.get("speaker", "agent"),
            "text": text,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    async def emit_activity(self, payload: dict[str, Any]) -> None:
        await self._channel.send_activity(payload)
        await _broadcast_console({
            "type": "agent_activity",
            "interaction_id": self._interaction_id,
            **{k: _json_safe(v) for k, v in payload.items()},
        })

    async def emit_slots_update(self, slots: dict[str, str]) -> None:
        await self._channel.send_slots_update(slots)
        await _broadcast_console({
            "type": "slots_update",
            "interaction_id": self._interaction_id,
            "slots": dict(slots),
        })

    async def emit_handoff_offer(self) -> None:
        await self._channel.send_handoff_offer()
        await _broadcast_console({
            "type": "handoff_offer",
            "interaction_id": self._interaction_id,
        })

    async def emit_interaction_ended(self, payload: dict[str, Any]) -> None:
        await self._channel.send_interaction_ended(payload)
        await _broadcast_console({
            "type": "interaction_ended",
            "interaction_id": self._interaction_id,
            **{k: _json_safe(v) for k, v in (payload or {}).items()},
        })

    async def emit_frustration_update(self, value: float) -> None:
        await _broadcast_console({
            "type": "frustration_update",
            "interaction_id": self._interaction_id,
            "value": float(value),
        })


async def interaction_ws(websocket: WebSocket, interaction_id: str) -> None:
    """Bidirectional contact stream at ``/ws/interaction/{id}``.

    Client → server: optional auth frame, then
      {"type":"user_turn","text":"...","final":true} | barge_in | hangup
    Server → client: agent_turn | agent_activity | slots_update | handoff_offer | interaction_ended

    Auth: prefer first-message ``{"type":"auth","api_key":"..."}`` or headers.
    Query ``?api_key=`` is deprecated.
    """
    if not frontline_enabled():
        await websocket.close(code=1013)
        return

    try:
        await authenticate_websocket(websocket)
    except HTTPException:
        try:
            if websocket.client_state.name != "CONNECTED":
                await websocket.accept()
            await websocket.close(code=1008)
        except Exception:
            pass
        return

    if websocket.client_state.name != "CONNECTED":
        await websocket.accept()

    try:
        entry = await _attach_customer_ws(interaction_id)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else str(e.detail)
        await websocket.send_json({"type": "error", "detail": detail})
        await websocket.close(code=1008 if e.status_code == 409 else 1000)
        return

    orch = entry.orch
    channel = WebVoiceChannel(websocket)
    orch.hooks = _WSHooks(channel, interaction_id)

    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "user_turn":
                async with entry.lock:
                    await orch.handle_customer_turn(
                        msg.get("text", ""), final=msg.get("final", True)
                    )
                if orch.ctx.state in ("DONE", "ABANDONED"):
                    break
            elif mtype == "barge_in":
                pass
            elif mtype == "hangup":
                async with entry.lock:
                    await orch.hangup()
                break
            elif mtype == "human_turn":
                async with entry.lock:
                    await orch.human_turn(msg.get("text", ""))
    except WebSocketDisconnect:
        if orch.ctx.state not in ("DONE", "ABANDONED"):
            try:
                async with entry.lock:
                    await orch.hangup()
            except Exception:
                pass
    except Exception as e:
        # H1: any agent/turn crash must not leave status='active' forever.
        try:
            if orch.ctx.state not in ("DONE", "ABANDONED"):
                async with entry.lock:
                    await orch.hangup()
        except Exception:
            pass
        await _mark_failed(interaction_id, f"ws_error:{type(e).__name__}")
        try:
            await websocket.send_json(
                {"type": "error", "detail": f"server error: {type(e).__name__}"}
            )
        except Exception:
            pass
    finally:
        await _unregister(interaction_id)
        try:
            await websocket.close()
        except Exception:
            pass


async def console_ws(websocket: WebSocket) -> None:
    """Live console feed at ``/ws/console``.

    Server → console: agent_activity (+ lifecycle) for all active interactions.
    Console → server (after takeover): {"type":"human_turn","interaction_id":"...","text":"..."}

    Auth: first-message auth frame preferred; query api_key deprecated.
    """
    if not frontline_enabled():
        await websocket.close(code=1013)
        return

    try:
        await authenticate_websocket(websocket)
    except HTTPException:
        try:
            if websocket.client_state.name != "CONNECTED":
                await websocket.accept()
            await websocket.close(code=1008)
        except Exception:
            pass
        return

    if websocket.client_state.name != "CONNECTED":
        await websocket.accept()
    async with _console_sub_lock:
        _console_subscribers.add(websocket)
    # Look back so a console that connects mid-call still sees recent activity
    # (and so tests that ledger-then-connect are not deadlocked waiting forever).
    last_ts: datetime = datetime.now(timezone.utc) - timedelta(hours=1)
    try:
        while True:
            rows = await asyncio.to_thread(fetch_agent_actions_since, last_ts, 50)
            for r in rows:
                raw_ts = r.get("ts")
                if isinstance(raw_ts, datetime):
                    last_ts = raw_ts
                # C1: never pass raw datetime into send_json (kills the socket).
                await websocket.send_json(activity_frame_from_row(r))

            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.5)
                if msg.get("type") == "human_turn":
                    iid = msg.get("interaction_id")
                    text = msg.get("text", "")
                    try:
                        entry = await _get_entry(iid)
                        async with entry.lock:
                            await entry.orch.human_turn(text)
                    except HTTPException:
                        await websocket.send_json(
                            {"type": "error", "detail": f"interaction not active: {iid}"}
                        )
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
    finally:
        async with _console_sub_lock:
            _console_subscribers.discard(websocket)


__all__ = [
    "router",
    "interaction_ws",
    "console_ws",
    "_active",
    "reap_orphans",
    "_sweep_stale_active_db_rows",
    "ActiveEntry",
    "_ORPHAN_TTL_S",
    "_json_safe",
    "activity_frame_from_row",
    "fetch_agent_actions_since",
]
