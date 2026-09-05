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
    # Authorization limits (board #10): pack-owned policy, enforced before
    # any write. Over-cap or supervisor-required bookings are NOT created;
    # the caller gets requires_approval with the reason, ledgered.
    try:
        from src.domains.loader import load_pack as _load_pack

        _policy = _load_pack(pack_id).manifest.booking_policy
        _max_per_case = max(1, int(_policy.max_per_case))
        _need_supervisor = bool(_policy.require_supervisor)
    except Exception:
        _max_per_case, _need_supervisor = 1, False
    with ops_con() as con:
        _ensure(con)
        _existing = 0
        if case_id:
            try:
                _existing = int(con.execute(
                    "SELECT COUNT(*) FROM appointments WHERE case_id = ? AND status = 'booked'",
                    [case_id],
                ).fetchone()[0])
            except Exception:
                _existing = 0
        if _need_supervisor or _existing >= _max_per_case:
            reason = (
                "supervisor approval required by pack policy"
                if _need_supervisor
                else f"booking cap reached ({_existing}/{_max_per_case} for this case)"
            )
            if interaction_id:
                try:
                    from src.ledger import AgentAction as _AA
                    from src.ledger import record_action as _ra

                    _ra(_AA(
                        interaction_id=interaction_id,
                        agent="case",
                        action_type="appointment_booked",
                        input_summary=str(slot_start),
                        output_summary=f"requires_approval: {reason}",
                        case_id=case_id,
                        ok=False,
                        error=reason,
                    ))
                except Exception:
                    pass
            return {
                "appointment_id": None,
                "status": "requires_approval",
                "slot_start": slot_start,
                "slot_end": end,
                "location": location,
                "reason": reason,
                "stub": True,
                "availability": "stub",
            }
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
        "stub": True,
        "test_mode": True,
        "availability": "stub",
        "note": "Pilot stub: writes to ops appointments only, no real calendar/double-book check.",
        "customer_message": (
            f"You're booked for {slot_start} at {location}. "
            + (f"Manage: {cal}" if cal else "We'll send a confirmation.")
            + " (Pilot scheduling — a specialist will confirm this booking.)"
        ),
    }


def offer_for_advisory(
    *,
    advisory_id: str | None,
    case_id: str | None,
    pack_id: str,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """Build an offer payload when an advisory matches (free remedy).

    Availability is labeled (item 40): slots come from the pilot stub
    calendar, so the offer carries ``availability: "stub"`` and the prompt
    says confirmation comes from a specialist — never presented as live
    calendar booking.
    """
    from src.frontline.capabilities import capability_status

    slots = list_open_slots(days_ahead=5, per_day=1)[:3]
    return {
        "offer_type": "free_remedy_appointment",
        "advisory_id": advisory_id,
        "case_id": case_id,
        "pack_id": pack_id,
        "interaction_id": interaction_id,
        "open_slots": slots,
        "availability": capability_status("booking")["availability"],
        "availability_note": capability_status("booking")["note"],
        "prompt": (
            "There is a free remedy appointment available for this advisory. "
            "Would you like to book one of these times? "
            "(Pilot scheduling — a specialist will confirm the booking.)"
        ),
    }
