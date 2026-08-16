"""Usage dashboard, Stripe test-mode billing, seats, roles, plan tiers."""

from __future__ import annotations

import json
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.frontline.metering import record_usage, usage_summary
from src.ids import new_ulid

PLAN_TIERS = {
    "trial": {"seats": 2, "contacts_month": 50, "roles": ("agent",)},
    "pilot": {"seats": 10, "contacts_month": 2000, "roles": ("agent", "supervisor", "auditor")},
    "enterprise": {
        "seats": 100,
        "contacts_month": 100000,
        "roles": ("agent", "supervisor", "auditor", "admin", "service"),
    },
}


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_accounts (
            tenant_id VARCHAR PRIMARY KEY,
            plan VARCHAR NOT NULL,
            seats_used INTEGER NOT NULL,
            stripe_customer VARCHAR,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_invoices (
            invoice_id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            stripe_session VARCHAR,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_seats (
            seat_id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            user_id VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )


def get_account(tenant_id: str = "default") -> dict[str, Any]:
    with ops_con() as con:
        _ensure(con)
        row = con.execute(
            "SELECT tenant_id, plan, seats_used, stripe_customer FROM billing_accounts WHERE tenant_id = ?",
            [tenant_id],
        ).fetchone()
        if not row:
            con.execute(
                """
                INSERT INTO billing_accounts (tenant_id, plan, seats_used, stripe_customer, updated_at)
                VALUES (?, 'trial', 0, NULL, ?)
                """,
                [tenant_id, utc_now()],
            )
            return {
                "tenant_id": tenant_id,
                "plan": "trial",
                "seats_used": 0,
                "limits": PLAN_TIERS["trial"],
            }
    return {
        "tenant_id": row[0],
        "plan": row[1],
        "seats_used": int(row[2] or 0),
        "stripe_customer": row[3],
        "limits": PLAN_TIERS.get(row[1], PLAN_TIERS["trial"]),
    }


def set_plan(tenant_id: str, plan: str) -> dict[str, Any]:
    if plan not in PLAN_TIERS:
        raise ValueError(f"unknown plan {plan}")
    get_account(tenant_id)
    with ops_con() as con:
        _ensure(con)
        con.execute(
            "UPDATE billing_accounts SET plan = ?, updated_at = ? WHERE tenant_id = ?",
            [plan, utc_now(), tenant_id],
        )
    return get_account(tenant_id)


def assign_seat(tenant_id: str, user_id: str, role: str) -> dict[str, Any]:
    acct = get_account(tenant_id)
    limits = acct["limits"]
    if role not in limits["roles"]:
        raise PermissionError(f"role {role} not on plan {acct['plan']}")
    if int(acct["seats_used"]) >= int(limits["seats"]):
        raise PermissionError(f"seat limit {limits['seats']} reached")
    sid = "seat_" + new_ulid()
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO tenant_seats (seat_id, tenant_id, user_id, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [sid, tenant_id, user_id, role, utc_now()],
        )
        con.execute(
            "UPDATE billing_accounts SET seats_used = seats_used + 1, updated_at = ? WHERE tenant_id = ?",
            [utc_now(), tenant_id],
        )
    return {"seat_id": sid, "tenant_id": tenant_id, "user_id": user_id, "role": role}


def enforce_plan(tenant_id: str, *, metric: str = "contacts", quantity: float = 1.0, role: str | None = None) -> dict[str, Any]:
    acct = get_account(tenant_id)
    limits = acct["limits"]
    if role and role not in limits["roles"]:
        return {"allowed": False, "reason": f"role {role} not on plan {acct['plan']}"}
    summary = usage_summary(tenant_id=tenant_id)
    used = float((summary.get("metrics") or {}).get(metric) or 0)
    cap = float(limits.get("contacts_month") or 0)
    if metric == "contacts" and used + quantity > cap:
        return {"allowed": False, "reason": f"over plan: {used}+{quantity} > {cap}"}
    return {"allowed": True, "plan": acct["plan"], "used": used, "cap": cap}


def usage_dashboard(tenant_id: str = "default") -> dict[str, Any]:
    acct = get_account(tenant_id)
    summary = usage_summary(tenant_id=tenant_id)
    return {
        "tenant_id": tenant_id,
        "plan": acct["plan"],
        "limits": acct["limits"],
        "seats_used": acct["seats_used"],
        "metrics": summary.get("metrics") or {},
        "month": summary.get("month"),
    }


def stripe_checkout(
    tenant_id: str,
    *,
    plan: str = "pilot",
    amount_cents: int = 9900,
    stripe_session: str | None = None,
) -> dict[str, Any]:
    """Test-mode Stripe path: persist an invoice + session id (no live charge)."""
    if plan not in PLAN_TIERS:
        raise ValueError(plan)
    iid = "in_" + new_ulid()
    session = stripe_session or ("cs_test_" + new_ulid())
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO billing_invoices
            (invoice_id, tenant_id, amount_cents, currency, status, stripe_session, created_at)
            VALUES (?, ?, ?, 'usd', 'open', ?, ?)
            """,
            [iid, tenant_id, int(amount_cents), session, utc_now()],
        )
    return {
        "invoice_id": iid,
        "tenant_id": tenant_id,
        "plan": plan,
        "amount_cents": amount_cents,
        "status": "open",
        "stripe_session": session,
        "checkout_url": f"https://checkout.stripe.com/c/pay/{session}",
        "test_mode": True,
    }


def stripe_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a Stripe-like webhook (checkout.session.completed)."""
    event = payload.get("type") or payload.get("event") or ""
    session = (
        (payload.get("data") or {}).get("object", {}).get("id")
        or payload.get("stripe_session")
        or ""
    )
    tenant_id = payload.get("tenant_id") or "default"
    plan = payload.get("plan") or "pilot"
    with ops_con() as con:
        _ensure(con)
        if session:
            con.execute(
                "UPDATE billing_invoices SET status = 'paid' WHERE stripe_session = ?",
                [session],
            )
    if event in {"checkout.session.completed", "invoice.paid", ""}:
        set_plan(tenant_id, plan)
    return {"ok": True, "event": event or "invoice.paid", "plan": plan, "tenant_id": tenant_id}


def record_metered(metric: str, quantity: float = 1.0, *, tenant_id: str = "default") -> dict[str, Any]:
    gate = enforce_plan(tenant_id, metric=metric, quantity=quantity)
    if not gate["allowed"]:
        return {"recorded": False, **gate}
    ev = record_usage(metric, quantity, tenant_id=tenant_id)
    return {"recorded": True, "event": ev, **gate}


__all__ = [
    "PLAN_TIERS",
    "get_account",
    "set_plan",
    "assign_seat",
    "enforce_plan",
    "usage_dashboard",
    "stripe_checkout",
    "stripe_webhook",
    "record_metered",
]
