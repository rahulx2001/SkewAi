"""Ops alerts — fire-and-forget webhook dispatcher.

Sends Slack-compatible `{"text": ...}` payloads to `ALERT_WEBHOOK_URL`. Non-blocking:
alert failures are logged, never break a call. Deduplication: at most one alert per
(event, cluster/interaction) per day, tracked in the `alert_dedup` ops table.

Delivery reliability (pilot):
  - Up to ``ALERT_RETRY_ATTEMPTS`` (default 3) POSTs with exponential backoff
  - Exhausted failures are written to ``alert_dead_letter`` for ops replay

Every alert is itself ledgered (agent='orchestrator', action_type='alert_sent') so
Qubot can report on alert volume.

Events:
  - safety_escalation       (P1)
  - investigation_opened
  - early_warning_threshold (cluster live-risk crosses threshold)
  - groundedness_mismatch   (from Qubot auditor)
  - takeover_started
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import settings
from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.ledger import AgentAction, record_action

logger = logging.getLogger(__name__)

# Bounded retries — short base delay so unit tests stay fast.
ALERT_RETRY_ATTEMPTS = 3
ALERT_RETRY_BASE_S = 0.02


# ── Deduplication ────────────────────────────────────────────────────────────


def _dedup_key(event: str, ref_id: str, pack_id: str | None = None) -> str:
    """Same-day dedup; pack_id scopes keys so two packs cannot suppress each other."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pack = (pack_id or "_").strip() or "_"
    return f"{event}:{pack}:{ref_id}:{today}"


def _already_fired(event: str, ref_id: str, pack_id: str | None = None) -> bool:
    """True if a *successful* same-day send was already recorded for (event, pack, ref)."""
    key = _dedup_key(event, ref_id, pack_id)
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT dedup_key FROM alert_dedup WHERE dedup_key = ?", [key]
        ).fetchone()
    return bool(row)


def _stamp_dedup(event: str, ref_id: str, pack_id: str | None = None) -> None:
    """Record successful delivery so same-day re-fire is suppressed."""
    key = _dedup_key(event, ref_id, pack_id)
    with ops_con() as con:
        exists = con.execute(
            "SELECT 1 FROM alert_dedup WHERE dedup_key = ?", [key]
        ).fetchone()
        if exists:
            return
        from src.data.timeutil import utc_now

        con.execute(
            "INSERT INTO alert_dedup (dedup_key, event, ref_id, fired_at) VALUES (?, ?, ?, ?)",
            [key, event, str(ref_id), utc_now()],
        )


# ── Dead letter ───────────────────────────────────────────────────────────────


def _record_dead_letter(
    *,
    event: str,
    ref_id: str,
    interaction_id: str | None,
    payload: dict[str, Any],
    attempts: int,
    error: str | None,
) -> str:
    """Persist a failed alert after retries are exhausted. Returns dead_letter_id."""
    from src.data.timeutil import utc_now

    dl_id = "adl_" + new_ulid()
    now = utc_now()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO alert_dead_letter
            (dead_letter_id, event, ref_id, interaction_id, payload_json,
             error, attempts, created_at, last_attempt_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            [
                dl_id,
                event,
                str(ref_id),
                interaction_id,
                json.dumps(payload),
                (error or "")[:1000],
                attempts,
                now,
                now,
            ],
        )
    return dl_id


def list_dead_letters(limit: int = 50, status: str = "pending") -> list[dict[str, Any]]:
    """List dead-letter rows (for ops / tests)."""
    with ops_con(read_only=True) as con:
        cur = con.execute(
            """
            SELECT dead_letter_id, event, ref_id, interaction_id, payload_json,
                   error, attempts, created_at, last_attempt_at, status
            FROM alert_dead_letter
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [status, limit],
        )
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = d["created_at"].isoformat()
            if isinstance(d.get("last_attempt_at"), datetime):
                d["last_attempt_at"] = d["last_attempt_at"].isoformat()
            rows.append(d)
    return rows


# ── Send ──────────────────────────────────────────────────────────────────────


async def _post_webhook_once(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Single POST attempt. Returns (ok, error_detail). Never raises."""
    url = settings.alert_webhook_url
    if not url:
        return False, "no_webhook_configured"
    try:
        from src.security.url_guard import validate_outbound_url

        url = validate_outbound_url(url)
    except ValueError as e:
        detail = f"ssrf_blocked:{e}"
        logger.warning("alert webhook blocked by URL guard: %s", detail)
        return False, detail
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            detail = f"http_{resp.status_code}: {resp.text[:200]}"
            logger.warning("alert webhook returned %s", detail)
            return False, detail
        return True, None
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        logger.warning("alert webhook failed: %s", detail)
        return False, detail


async def _post_webhook(payload: dict[str, Any]) -> bool:
    """POST with bounded retries + exponential backoff. Returns True on success.

    Failures are logged but never raised — alerting must not break a call.
    Callers that need attempt counts should use ``_post_webhook_with_meta``.
    """
    ok, _, _ = await _post_webhook_with_meta(payload)
    return ok


async def _post_webhook_with_meta(
    payload: dict[str, Any],
    *,
    max_attempts: int | None = None,
    base_delay_s: float | None = None,
) -> tuple[bool, int, str | None]:
    """POST with retries. Returns (ok, attempts_made, last_error)."""
    url = settings.alert_webhook_url
    if not url:
        return False, 0, "no_webhook_configured"

    attempts = max_attempts if max_attempts is not None else ALERT_RETRY_ATTEMPTS
    base = base_delay_s if base_delay_s is not None else ALERT_RETRY_BASE_S
    last_err: str | None = None
    for i in range(1, attempts + 1):
        ok, err = await _post_webhook_once(payload)
        if ok:
            return True, i, None
        last_err = err
        if i < attempts:
            await asyncio.sleep(base * (2 ** (i - 1)))
    return False, attempts, last_err


def _format_slack(event: str, summary: str, ref_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a Slack-compatible payload. `text` is the headline; attachments carry detail."""
    icon = {
        "safety_escalation": "🚨",
        "investigation_opened": "🔍",
        "early_warning_threshold": "📈",
        "groundedness_mismatch": "⚠️",
        "takeover_started": "👤",
    }.get(event, "🔔")
    text = f"{icon} *{event.replace('_', ' ').title()}* — {summary}"
    payload: dict[str, Any] = {"text": text}
    if extra:
        payload["attachments"] = [{"fields": [
            {"title": k, "value": str(v), "short": len(str(v)) < 40}
            for k, v in extra.items()
        ]}]
    return payload


# ── Public API ────────────────────────────────────────────────────────────────


async def fire_alert(
    event: str,
    summary: str,
    ref_id: str,
    interaction_id: str | None = None,
    extra: dict[str, Any] | None = None,
    pack_id: str | None = None,
) -> bool:
    """Fire an ops alert. Deduped per (event, pack_id, ref_id, day).

    Args:
        event: one of the canonical event types (see module docstring).
        summary: human-readable headline for the alert body.
        ref_id: cluster_id or interaction_id used for dedup.
        interaction_id: optional — if set, the alert is ledgered against this interaction.
        extra: optional structured fields attached to the Slack attachment.
        pack_id: domain pack identity so the same cluster id in two packs does not collide.

    Returns True if the webhook was actually called and succeeded; False if
    deduped, no webhook configured, or the POST failed after retries.
    """
    if _already_fired(event, ref_id, pack_id):
        return False

    payload = _format_slack(event, summary, ref_id, extra)
    sent, attempts, err = await _post_webhook_with_meta(payload)

    if sent:
        # Dedup only after a successful delivery (M-NEW-1). Failed sends leave
        # no stamp so a later retry/re-fire same day can still attempt delivery.
        try:
            _stamp_dedup(event, ref_id, pack_id)
        except Exception as e:
            logger.warning("failed to stamp alert dedup: %s", e)
    elif settings.alert_webhook_url:
        try:
            _record_dead_letter(
                event=event,
                ref_id=ref_id,
                interaction_id=interaction_id,
                payload=payload,
                attempts=attempts,
                error=err,
            )
        except Exception as e:
            logger.warning("failed to write alert dead-letter: %s", e)

    # Ledger every alert (success or skip) — Qubot reports on alert volume.
    record_action(AgentAction(
        interaction_id=interaction_id or "platform",
        agent="orchestrator",
        action_type="alert_sent",
        input_summary=f"event={event}, ref_id={ref_id}",
        output_summary=f"summary={summary}; webhook_sent={sent}; attempts={attempts}",
        evidence_ids=[str(ref_id)] if ref_id else [],
    ))
    return sent


async def replay_dead_letter(dead_letter_id: str) -> bool:
    """Re-POST a pending dead-letter payload once (no retry cascade). Marks replayed on success."""
    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT payload_json, status FROM alert_dead_letter
            WHERE dead_letter_id = ?
            """,
            [dead_letter_id],
        ).fetchone()
    if not row:
        return False
    payload_json, status = row[0], row[1]
    if status != "pending":
        return False
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return False
    ok, _err = await _post_webhook_once(payload)
    if ok:
        from src.data.timeutil import utc_now

        with ops_con() as con:
            con.execute(
                """
                UPDATE alert_dead_letter
                SET status = 'replayed', last_attempt_at = ?
                WHERE dead_letter_id = ?
                """,
                [utc_now(), dead_letter_id],
            )
    return ok


# ── Convenience wrappers ──────────────────────────────────────────────────────


async def alert_safety_escalation(interaction_id: str, term: str) -> bool:
    return await fire_alert(
        event="safety_escalation",
        summary=f"kill-switch escalation on interaction {interaction_id} (term: '{term}')",
        ref_id=interaction_id,
        interaction_id=interaction_id,
        extra={"term": term, "interaction_id": interaction_id},
    )


async def alert_investigation_opened(
    investigation_id: str,
    cluster_id: int,
    title: str,
    pack_id: str | None = None,
) -> bool:
    return await fire_alert(
        event="investigation_opened",
        summary=f"new investigation {investigation_id} opened for cluster #{cluster_id}",
        ref_id=str(cluster_id),
        pack_id=pack_id,
        extra={
            "investigation_id": investigation_id,
            "cluster_id": cluster_id,
            "title": title,
            "pack_id": pack_id or "",
        },
    )


async def alert_takeover_started(interaction_id: str) -> bool:
    return await fire_alert(
        event="takeover_started",
        summary=f"supervisor took over interaction {interaction_id}",
        ref_id=interaction_id,
        interaction_id=interaction_id,
    )


async def alert_groundedness_mismatch(interaction_id: str, action_id: str, detail: str) -> bool:
    return await fire_alert(
        event="groundedness_mismatch",
        summary=f"ungrounded agent output on interaction {interaction_id} (action {action_id})",
        ref_id=interaction_id,
        interaction_id=interaction_id,
        extra={"action_id": action_id, "detail": detail[:500]},
    )


async def alert_early_warning(
    cluster_id: int,
    live_count: int,
    lead_time_weeks: int | None,
    pack_id: str | None = None,
) -> bool:
    lead_str = f"{lead_time_weeks} weeks" if lead_time_weeks is not None else "n/a"
    return await fire_alert(
        event="early_warning_threshold",
        summary=f"cluster #{cluster_id} crossed early-warning threshold ({live_count} live cases; historical lead-time {lead_str})",
        ref_id=str(cluster_id),
        pack_id=pack_id,
        extra={
            "cluster_id": cluster_id,
            "live_count": live_count,
            "lead_time_weeks": lead_time_weeks,
            "pack_id": pack_id or "",
        },
    )


__all__ = [
    "fire_alert",
    "alert_safety_escalation",
    "alert_investigation_opened",
    "alert_takeover_started",
    "alert_groundedness_mismatch",
    "alert_early_warning",
    "list_dead_letters",
    "replay_dead_letter",
    "ALERT_RETRY_ATTEMPTS",
    "_post_webhook",
    "_post_webhook_with_meta",
    "_post_webhook_once",
]
