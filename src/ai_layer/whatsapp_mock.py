"""WhatsApp intake — MOCK.  [AI-LAYER]

NO WhatsApp / Meta Cloud API is called and nothing leaves the box. This module
accepts a webhook body shaped like the WhatsApp Cloud API ``messages`` event,
feeds each text message into the EXISTING intake orchestrator
(``create_interaction`` + ``handle_customer_turn``) and returns the agent's
replies in the response so the mock chat UI can render them. Kill-switch,
safety assessment, Qubot and audit run exactly as for any other contact.

Sessions are held in process memory keyed by the sender's hashed reference (ref);
the sender id is stored only as a sha256 ``customer_ref`` (never raw).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from typing import Any

MOCK_LABEL = "MOCK — simulated WhatsApp channel; no WhatsApp/Meta API is called and no message is sent"
CHANNEL = "whatsapp_mock"
_TERMINAL = ("DONE", "ABANDONED")
_MAX_TEXT = 2000

_sessions: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}
_seen: "OrderedDict[str, None]" = OrderedDict()


def reset_sessions() -> None:
    _sessions.clear()
    _locks.clear()
    _seen.clear()


def parse_webhook(body: Any) -> list[dict[str, Any]]:
    """Extract inbound messages from a Cloud-API-shaped body. Unknown shapes -> []."""
    out: list[dict[str, Any]] = []
    if not isinstance(body, dict):
        return out
    entries = body.get("entry")
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            contacts = value.get("contacts")
            names: dict[str, Any] = {}
            if isinstance(contacts, list):
                for c in contacts:
                    if isinstance(c, dict) and c.get("wa_id") and isinstance(c.get("profile"), dict):
                        names[c["wa_id"]] = c["profile"].get("name")
            messages = value.get("messages")
            if not isinstance(messages, list):
                continue
            for m in messages:
                if not isinstance(m, dict) or not m.get("from"):
                    continue
                text = None
                if m.get("type") == "text":
                    t_val = m.get("text")
                    if isinstance(t_val, dict):
                        text = t_val.get("body")
                out.append({
                    "from": str(m["from"])[:32],
                    "id": str(m.get("id") or ""),
                    "type": m.get("type"),
                    "text": str(text)[:_MAX_TEXT] if text is not None else None,
                    "name": names.get(m.get("from")),
                })
    return out


def _ref(wa_id: str) -> str:
    return hashlib.sha256(f"whatsapp:{wa_id}".encode()).hexdigest()


def _reply(wa_id: str, text: str) -> dict[str, Any]:
    return {"messaging_product": "whatsapp", "to": wa_id, "type": "text", "text": {"body": text}, "status": "mock_not_sent"}


async def handle_message(msg: dict[str, Any], *, pack_id: str | None = None) -> dict[str, Any]:
    from src.agents.orchestrator import OrchestratorHooks, create_interaction

    wa_id = msg["from"]
    msg_id = msg.get("id")
    if msg_id:
        if msg_id in _seen:
            return {"from": wa_id, "duplicate": True, "replies": []}
    if msg.get("text") is None:
        return {"from": wa_id, "replies": [_reply(wa_id, "This mock only accepts text messages. Please describe the problem in words.")]}

    ref = _ref(wa_id)
    if ref not in _locks:
        if len(_locks) > 2000:
            _locks.clear()
        _locks[ref] = asyncio.Lock()
    lock = _locks[ref]
    async with lock:
        s = _sessions.get(ref)
        if s is None or s["orch"].ctx.state in _TERMINAL:
            outbox: list[str] = []

            async def _said(text: str, meta: dict[str, Any], _o=outbox) -> None:
                if text:
                    _o.append(str(text))

            orch, greeting = await create_interaction(
                channel=CHANNEL, pack_id=pack_id, customer_ref=ref,
                hooks=OrchestratorHooks(emit_customer_turn=_said)
            )
            s = {"orch": orch, "outbox": outbox}
            _sessions[ref] = s
            if len(_sessions) > 1000:
                _sessions.popitem(last=False)
            if greeting and greeting not in outbox:
                outbox.append(str(greeting))
        start = 0 if not s.get("started") else len(s["outbox"])
        s["started"] = True
        await s["orch"].handle_customer_turn(msg["text"])
        ctx = s["orch"].ctx
        new = s["outbox"][start:]
        if ctx.state in _TERMINAL:
            _sessions.pop(ref, None)
            _locks.pop(ref, None)

        if msg_id:
            _seen[msg_id] = None
            while len(_seen) > 5000:
                _seen.popitem(last=False)

        return {"from": wa_id, "interaction_id": ctx.interaction_id, "state": ctx.state, "case_id": ctx.case_id,
                "severity": ctx.severity, "safety_flags": sorted(k for k, v in (ctx.safety_flags or {}).items() if v),
                "fault_codes": _fault_codes(ctx.interaction_id),  # [AI-LAYER] 'codes: C0035 P0300'
                "replies": [_reply(wa_id, t) for t in new]}


def erase_for_interaction(interaction_id: str) -> None:
    for ref in list(_sessions.keys()):
        s = _sessions.get(ref)
        if s and getattr(getattr(s.get("orch"), "ctx", None), "interaction_id", None) == interaction_id:
            _sessions.pop(ref, None)
            _locks.pop(ref, None)


def _fault_codes(interaction_id: str) -> list[dict[str, Any]]:
    # [AI-LAYER] fault codes the customer typed (e.g. 'codes: C0035 P0300'), with generic meanings
    try:
        from src.ai_layer.fault_codes import codes_for_interaction, lookup

        return [lookup(c) for c in codes_for_interaction(interaction_id)]
    except Exception:
        return []


async def handle_webhook(body: Any, *, pack_id: str | None = None) -> dict[str, Any]:
    msgs = parse_webhook(body)
    results = [await handle_message(m, pack_id=pack_id) for m in msgs]
    return {"mock": True, "label": MOCK_LABEL, "received": len(msgs), "results": results}


__all__ = ["CHANNEL", "MOCK_LABEL", "erase_for_interaction", "handle_message", "handle_webhook", "parse_webhook", "reset_sessions"]
