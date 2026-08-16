"""Webhook catalog + delivery of due subscription ticks to Slack/Teams."""

from __future__ import annotations

from typing import Any

from src.frontline.subscriptions import subscribe, tick_due

CATALOG = [
    {
        "event": "investigation_opened",
        "description": "A live intercept or case opened an investigation",
        "payload": ["investigation_id", "cluster_id", "pack_id"],
    },
    {
        "event": "early_warning_threshold",
        "description": "Cluster crossed the early-warning live-risk threshold",
        "payload": ["cluster_id", "live_count", "lead_time_weeks"],
    },
    {
        "event": "groundedness_mismatch",
        "description": "Qubot marked an action ungrounded or source-drifted",
        "payload": ["interaction_id", "action_id", "detail"],
    },
    {
        "event": "daily_digest",
        "description": "Scheduled daily ops digest",
        "payload": ["subscription_id", "body_preview"],
    },
    {
        "event": "weekly_early_warning",
        "description": "Scheduled weekly early-warning brief",
        "payload": ["subscription_id", "body_preview"],
    },
]


def list_catalog() -> list[dict[str, Any]]:
    return list(CATALOG)


def fire_due_tick(*, force: bool = True, channel: str = "slack") -> dict[str, Any]:
    """Ensure a subscription exists and produce Slack/Teams payloads."""
    if channel not in {"slack", "teams", "webhook", "email"}:
        raise ValueError(channel)
    target = {
        "slack": "#skew-ops",
        "teams": "#skew-ops-teams",
        "webhook": "https://example.com/hooks/skew",
        "email": "ops@example.com",
    }[channel]
    # Slack/Teams share the slack channel validator in subscriptions; map teams→slack store.
    store_channel = "slack" if channel in {"slack", "teams"} else channel
    sub = subscribe(
        channel=store_channel,
        target=target,
        report_type="daily_digest",
    )
    sent = tick_due(force=force)
    payloads = []
    for item in sent:
        payloads.append(
            {
                "channel": channel,
                "target": item.get("target"),
                "text": item.get("body_preview"),
                "subscription_id": item.get("subscription_id"),
                "rendered_at": item.get("rendered_at"),
            }
        )
    return {"subscription": sub, "sent": payloads, "count": len(payloads)}


__all__ = ["CATALOG", "list_catalog", "fire_due_tick"]
