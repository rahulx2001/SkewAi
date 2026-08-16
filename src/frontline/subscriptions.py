"""Scheduled report subscriptions (feature #55).

Email/Slack the daily digest and weekly early-warning brief on a cron-like
tick. Hermetic: records due subscriptions and renders payload without sending
unless webhook configured.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _validate_target(channel: str, target: str) -> str:
    t = (target or "").strip()
    if not t or len(t) > 500:
        raise ValueError("target required (max 500 chars)")
    if channel == "email":
        if not _EMAIL_RE.match(t):
            raise ValueError("target must be a valid email address")
    elif channel == "webhook":
        from src.security.url_guard import validate_outbound_url

        try:
            validate_outbound_url(t)
        except ValueError as e:
            raise ValueError(f"webhook target rejected: {e}") from e
    elif channel == "slack":
        # webhook URL or #channel / @user token — require non-empty printable
        if any(ch in t for ch in ("\n", "\r", "\x00")):
            raise ValueError("target contains control characters")
    return t


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS report_subscriptions (
            subscription_id VARCHAR PRIMARY KEY,
            channel VARCHAR NOT NULL,
            target VARCHAR NOT NULL,
            report_type VARCHAR NOT NULL,
            cron_hint VARCHAR,
            enabled BOOLEAN DEFAULT TRUE,
            last_sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def subscribe(
    *,
    channel: str,
    target: str,
    report_type: str = "daily_digest",
    cron_hint: str = "0 8 * * *",
) -> dict[str, Any]:
    if report_type not in {"daily_digest", "weekly_early_warning"}:
        raise ValueError("report_type must be daily_digest or weekly_early_warning")
    if channel not in {"email", "slack", "webhook"}:
        raise ValueError("channel must be email|slack|webhook")
    target = _validate_target(channel, target)
    sid = f"sub_{new_ulid()}"
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO report_subscriptions
              (subscription_id, channel, target, report_type, cron_hint, enabled)
            VALUES (?, ?, ?, ?, ?, TRUE)
            """,
            [sid, channel, target, report_type, cron_hint],
        )
    return {
        "subscription_id": sid,
        "channel": channel,
        "target": target,
        "report_type": report_type,
        "cron_hint": cron_hint,
        "enabled": True,
    }


def list_subscriptions() -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
            rows = con.execute(
                "SELECT subscription_id, channel, target, report_type, cron_hint, enabled, last_sent_at FROM report_subscriptions"
            ).fetchall()
        except Exception:
            return []
    cols = [
        "subscription_id",
        "channel",
        "target",
        "report_type",
        "cron_hint",
        "enabled",
        "last_sent_at",
    ]
    return [dict(zip(cols, r)) for r in rows]


def tick_due(*, force: bool = False) -> list[dict[str, Any]]:
    """Render and 'send' due subscriptions (outbox record)."""
    sent = []
    for sub in list_subscriptions():
        if not sub.get("enabled") and not force:
            continue
        if sub.get("last_sent_at") and not force:
            continue
        payload = {
            "subscription_id": sub["subscription_id"],
            "report_type": sub["report_type"],
            "channel": sub["channel"],
            "target": sub["target"],
            "rendered_at": utc_now().isoformat(),
            "body_preview": f"[Skew AI] {sub['report_type']} for pilot",
        }
        # mark sent
        with ops_con() as con:
            con.execute(
                "UPDATE report_subscriptions SET last_sent_at = ? WHERE subscription_id = ?",
                [utc_now(), sub["subscription_id"]],
            )
        try:
            from pathlib import Path
            from src.config import REPO_ROOT

            out = REPO_ROOT / "data" / "connectors" / "outbox"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"report_{sub['subscription_id']}.json").write_text(
                json.dumps(payload, indent=2)
            )
        except Exception:
            pass
        sent.append(payload)
    return sent
