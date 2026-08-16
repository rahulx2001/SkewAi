"""Appointment / dealer booking agent (feature #17).

On advisory match, offers a free remedy appointment. Calendar is a pilot stub
that writes to ops ``appointments`` table; optional Cal.com URL is returned
when ``CALCOM_BOOKING_URL`` is set.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            appointment_id VARCHAR PRIMARY KEY,
            case_id VARCHAR,
            interaction_id VARCHAR,
            pack_id VARCHAR,
            slot_start TIMESTAMP,
            slot_end TIMESTAMP,
            dealer_or_location VARCHAR,
            status VARCHAR,
            calendar_url VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def list_open_slots(*, days_ahead: int = 7, per_day: int = 2) -> list[dict[str, Any]]:
    """Generate deterministic open slots (no external calendar required)."""
    base = utc_now().replace(hour=10, minute=0, second=0, microsecond=0)
    slots = []
    for d in range(1, max(1, days_ahead) + 1):
        for h_off in range(per_day):
            start = base + timedelta(days=d, hours=h_off * 3)
            end = start + timedelta(hours=1)
            slots.append(
                {
                    "slot_start": start.isoformat(),
                    "slot_end": end.isoformat(),
                    "label": start.strftime("%Y-%m-%d %H:%M UTC"),
                }
            )
    return slots


def book_appointment(
    *,
    case_id: str | None,
    interaction_id: str | None,
    pack_id: str,
    slot_start: str,
    slot_end: str | None = None,
    location: str = "authorized_service",
) -> dict[str, Any]:
    aid = f"appt_{new_ulid()}"
    cal = os.getenv("CALCOM_BOOKING_URL", "").strip() or None
    end = slot_end
    if not end:
        try:
            from datetime import datetime

            start_dt = datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
            end = (start_dt + timedelta(hours=1)).isoformat()
        except Exception:
            end = slot_start
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO appointments
              (appointment_id, case_id, interaction_id, pack_id,
               slot_start, slot_end, dealer_or_location, status, calendar_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'booked', ?)
            """,
            [aid, case_id, interaction_id, pack_id, slot_start, end, location, cal],
        )
    ledgered = False
    if interaction_id:
        try:
            from src.ledger import AgentAction, record_action

            record_action(
                AgentAction(
                    interaction_id=interaction_id,
                    agent="case",
                    action_type="appointment_booked",
                    input_summary=str(slot_start),
                    output_summary=f"appointment_id={aid}; location={location}",
                    case_id=case_id,
                    ok=True,
                )
            )
            ledgered = True
        except Exception:
            pass
    return {
        "appointment_id": aid,
        "status": "booked",
        "slot_start": slot_start,
        "slot_end": end,
        "location": location,
        "calendar_url": cal,
        "ledgered": ledgered,
        "customer_message": (
            f"You're booked for {slot_start} at {location}. "
            + (f"Manage: {cal}" if cal else "We'll send a confirmation.")
        ),
    }


def offer_for_advisory(
    *,
    advisory_id: str | None,
    case_id: str | None,
    pack_id: str,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """Build an offer payload when an advisory matches (free remedy)."""
    slots = list_open_slots(days_ahead=5, per_day=1)[:3]
    return {
        "offer_type": "free_remedy_appointment",
        "advisory_id": advisory_id,
        "case_id": case_id,
        "pack_id": pack_id,
        "interaction_id": interaction_id,
        "open_slots": slots,
        "prompt": (
            "There is a free remedy appointment available for this advisory. "
            "Would you like to book one of these times?"
        ),
    }
