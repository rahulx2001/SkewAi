"""Ops alerts tests (per blueprint §15.2).

Covers:
  - Mocked webhook per event type (safety_escalation, investigation_opened,
    takeover_started, groundedness_mismatch, early_warning_threshold)
  - Dedup window: firing twice → only one alert sent
  - Alert failure never raises into the call flow
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.frontline import alerts as alerts_mod
from src.frontline.alerts import (
    alert_groundedness_mismatch,
    alert_investigation_opened,
    alert_safety_escalation,
    alert_takeover_started,
    fire_alert,
)

_HOOK = "https://hooks.example.test/slack"


# ── Mocked webhook per event type ─────────────────────────────────────────────


async def test_safety_escalation_alert_calls_webhook(reset_ops_db):
    """alert_safety_escalation should POST a Slack-compatible payload."""
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            sent = await alert_safety_escalation("int_test_alert", "fire")
    assert sent is True
    mock_post.assert_awaited_once()
    payload = mock_post.call_args.args[0]
    assert "text" in payload
    assert "safety" in payload["text"].lower() or "🚨" in payload["text"]


async def test_investigation_opened_alert_calls_webhook(reset_ops_db):
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            await alert_investigation_opened("inv_0001", 14, "Cluster 14: grinding brakes")
    mock_post.assert_awaited_once()
    payload = mock_post.call_args.args[0]
    assert "investigation" in payload["text"].lower() or "🔍" in payload["text"]


async def test_takeover_started_alert_calls_webhook(reset_ops_db):
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            await alert_takeover_started("int_test_takeover")
    mock_post.assert_awaited_once()


async def test_groundedness_mismatch_alert_calls_webhook(reset_ops_db):
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            await alert_groundedness_mismatch("int_test_mismatch", "act_xxx", "uncited 19V-99999")
    mock_post.assert_awaited_once()


async def test_early_warning_alert_calls_webhook(reset_ops_db):
    from src.frontline.alerts import alert_early_warning

    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            await alert_early_warning(cluster_id=14, live_count=3, lead_time_weeks=11)
    mock_post.assert_awaited_once()


# ── Dedup window ─────────────────────────────────────────────────────────────


async def test_dedup_window_fires_once(reset_ops_db):
    """Firing the same alert twice in one day only POSTs once."""
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            first = await alert_safety_escalation("int_test_dedup", "fire")
            second = await alert_safety_escalation("int_test_dedup", "fire")
    assert first is True
    assert second is False, "second call should be deduped"
    assert mock_post.await_count == 1


async def test_dedup_per_event(reset_ops_db):
    """Different event types on the same interaction_id are NOT deduped against each other."""
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            await alert_safety_escalation("int_test_per_event", "fire")
            await alert_takeover_started("int_test_per_event")
    assert mock_post.await_count == 2


async def test_dedup_per_ref_id(reset_ops_db):
    """Different ref_ids (e.g. different interactions) are NOT deduped against each other."""
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(
            alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(True, None))
        ) as mock_post:
            await alert_safety_escalation("int_a", "fire")
            await alert_safety_escalation("int_b", "fire")
    assert mock_post.await_count == 2


# ── Failure never raises into call flow ───────────────────────────────────────


async def test_webhook_failure_does_not_raise(reset_ops_db):
    """If the underlying httpx POST raises, _post_webhook catches it (returns False)
    and fire_alert never sees the exception — alerting must not break a call."""
    # Point the webhook at a non-routable URL so httpx itself raises.
    # We patch settings.alert_webhook_url (a frozen dataclass) by patching the
    # alerts module's reference.
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = "http://127.0.0.1:1/no-server-here"
        # _post_webhook opens a real httpx client; the connection will be refused.
        # The internal try/except must catch it and return False.
        sent = await fire_alert(
            event="safety_escalation",
            summary="test",
            ref_id="int_test_failure",
            interaction_id="int_test_failure",
        )
    assert sent is False


async def test_no_webhook_configured_does_not_raise(reset_ops_db):
    """When ALERT_WEBHOOK_URL is empty, alerts are no-ops (not errors)."""
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = ""
        sent = await fire_alert(
            event="safety_escalation",
            summary="test",
            ref_id="int_test_no_webhook",
            interaction_id="int_test_no_webhook",
        )
    assert sent is False


# ── Every alert is ledgered ───────────────────────────────────────────────────


async def test_every_alert_is_ledgered(reset_ops_db):
    """Even when the webhook is not configured, an alert_sent row is written."""
    from src.data.warehouse import ops_con

    with patch.object(
        alerts_mod, "_post_webhook_once", new=AsyncMock(return_value=(False, "fail"))
    ):
        with patch.object(alerts_mod, "settings") as mock_settings:
            mock_settings.alert_webhook_url = ""
            await fire_alert(
                event="safety_escalation",
                summary="test ledger",
                ref_id="int_test_ledger",
                interaction_id="int_test_ledger",
            )
    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT action_type, input_summary, output_summary FROM agent_actions
            WHERE interaction_id = ? AND action_type = 'alert_sent'
            """,
            ["int_test_ledger"],
        ).fetchone()
    assert row is not None
    assert "safety_escalation" in row[1]  # input_summary contains event=...


# ── Retry + dead-letter ───────────────────────────────────────────────────────


async def test_webhook_retries_on_failure(reset_ops_db):
    """Failing once then succeeding: real retry path hits _post_webhook_once ≥2 times."""
    mock_once = AsyncMock(side_effect=[(False, "http_500"), (True, None)])
    with patch.object(alerts_mod, "_post_webhook_once", new=mock_once):
        with patch.object(alerts_mod, "settings") as mock_settings:
            mock_settings.alert_webhook_url = "https://hooks.example.test/slack"
            sent = await fire_alert(
                event="safety_escalation",
                summary="retry me",
                ref_id="int_retry_ok",
                interaction_id="int_retry_ok",
            )
    assert sent is True
    assert mock_once.await_count >= 2


async def test_exhausted_retries_write_dead_letter(reset_ops_db):
    """All attempts fail → durable dead-letter row; alert never raises."""
    from src.data.warehouse import ops_con
    from src.frontline.alerts import list_dead_letters

    mock_once = AsyncMock(return_value=(False, "connection_refused"))
    with patch.object(alerts_mod, "_post_webhook_once", new=mock_once):
        with patch.object(alerts_mod, "settings") as mock_settings:
            mock_settings.alert_webhook_url = "https://hooks.example.test/slack"
            sent = await fire_alert(
                event="safety_escalation",
                summary="dl test",
                ref_id="int_dead_letter_1",
                interaction_id="int_dead_letter_1",
            )
    assert sent is False
    assert mock_once.await_count >= 2
    assert mock_once.await_count == alerts_mod.ALERT_RETRY_ATTEMPTS

    dls = list_dead_letters(status="pending")
    match = [d for d in dls if d.get("ref_id") == "int_dead_letter_1"]
    assert match, f"expected dead-letter row, got {dls}"
    assert match[0]["event"] == "safety_escalation"
    assert match[0]["attempts"] >= 2
    assert match[0]["payload_json"]

    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM alert_dead_letter WHERE ref_id = ?",
            ["int_dead_letter_1"],
        ).fetchone()[0]
    assert n >= 1


async def test_failed_delivery_does_not_block_later_success(reset_ops_db):
    """M-NEW-1: after fail+dead-letter, same-day re-fire can still succeed."""
    from src.frontline.alerts import _already_fired

    fail = AsyncMock(return_value=(False, "down"))
    ok = AsyncMock(return_value=(True, None))
    with patch.object(alerts_mod, "settings") as mock_settings:
        mock_settings.alert_webhook_url = _HOOK
        with patch.object(alerts_mod, "_post_webhook_once", new=fail):
            first = await fire_alert(
                event="safety_escalation",
                summary="first fail",
                ref_id="int_rearm_1",
                interaction_id="int_rearm_1",
            )
        assert first is False
        # Failed path must NOT leave a dedup stamp
        assert alerts_mod._already_fired("safety_escalation", "int_rearm_1") is False

        with patch.object(alerts_mod, "_post_webhook_once", new=ok) as mock_ok:
            second = await fire_alert(
                event="safety_escalation",
                summary="retry success",
                ref_id="int_rearm_1",
                interaction_id="int_rearm_1",
            )
        assert second is True
        assert mock_ok.await_count >= 1
        assert alerts_mod._already_fired("safety_escalation", "int_rearm_1") is True

        # Third same day must be deduped (returns False)
        third = await fire_alert(
            event="safety_escalation",
            summary="should dedupe",
            ref_id="int_rearm_1",
            interaction_id="int_rearm_1",
        )
        assert third is False
