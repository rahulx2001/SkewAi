"""Weekly crypto-shred drill on a disposable synthetic contact.

Creates a throwaway interaction, encrypts a payload under its DEK, shreds the
DEK, then verifies: payload unreadable, hash chain still validates, report
row written. Failures alert ops. Run unattended via:

    python -m src.compliance.erasure_drill --weekly
    enqueue("erasure_drill", {"weekly": True})
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

DRILL_INTERVAL = timedelta(days=7)


def _ensure_reports(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS erasure_drill_reports (
            report_id          VARCHAR PRIMARY KEY,
            ran_at             TIMESTAMP NOT NULL,
            interaction_id     VARCHAR,
            passed             BOOLEAN NOT NULL,
            chain_ok           BOOLEAN,
            payload_unreadable BOOLEAN,
            dek_destroyed      BOOLEAN,
            error              VARCHAR,
            detail_json        VARCHAR
        )
        """
    )


def last_drill_at() -> Any | None:
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                "SELECT MAX(ran_at) FROM erasure_drill_reports"
            ).fetchone()
        except Exception:
            return None
    return row[0] if row and row[0] else None


def maybe_run_weekly_drill() -> dict[str, Any] | None:
    """Run the drill if none has passed in the last 7 days."""
    last = last_drill_at()
    if last is not None:
        try:
            from datetime import datetime

            if isinstance(last, str):
                last_dt = datetime.fromisoformat(last)
            else:
                last_dt = last
            if last_dt.tzinfo is None:
                now = utc_now().replace(tzinfo=None)
            else:
                now = utc_now()
            if (now - last_dt) < DRILL_INTERVAL:
                return None
        except Exception:
            pass
    return run_erasure_drill()


def run_erasure_drill() -> dict[str, Any]:
    """Create, shred, and verify a disposable contact. Always writes a report row."""
    from src.frontline.dsr import delete_interaction
    from src.ledger import AgentAction, record_action
    from src.ledger.chain import verify_chain
    from src.ledger.writer import list_actions
    from src.security.pii import (
        SubjectKeyStore,
        decrypt_subject_pii,
        encrypt_subject_pii,
    )

    iid = "int_drill_" + new_ulid()
    secret = "drill-pii-do-not-keep"
    chain_ok = False
    payload_unreadable = False
    dek_destroyed = False
    error: str | None = None
    token = ""
    try:
        now = utc_now().replace(tzinfo=None)
        with ops_con() as con:
            _ensure_reports(con)
            con.execute(
                """
                INSERT INTO interactions
                (interaction_id, pack_id, pack_version, started_at, channel, status)
                VALUES (?, 'automotive_nhtsa', 'drill', ?, 'synthetic', 'completed')
                """,
                [iid, now],
            )
        record_action(AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="state_transition",
            input_summary="erasure drill synthetic contact",
            output_summary="created",
        ))
        token = encrypt_subject_pii(iid, secret)
        if decrypt_subject_pii(iid, token) != secret:
            raise RuntimeError("pre-shred decrypt mismatch")
        before = list_actions(iid)
        if not verify_chain(before)["ok"]:
            raise RuntimeError("chain invalid before shred")
        delete_interaction(iid, mode="crypto_shred")
        dek_destroyed = not SubjectKeyStore.has_dek(iid)
        try:
            decrypt_subject_pii(iid, token)
            payload_unreadable = False
        except KeyError:
            payload_unreadable = True
        after = list_actions(iid)
        chain_ok = bool(verify_chain(after)["ok"])
        if not (dek_destroyed and payload_unreadable and chain_ok):
            error = (
                f"dek_destroyed={dek_destroyed} "
                f"payload_unreadable={payload_unreadable} chain_ok={chain_ok}"
            )
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    passed = bool(dek_destroyed and payload_unreadable and chain_ok and not error)
    report = {
        "ok": passed,
        "passed": passed,
        "interaction_id": iid,
        "chain_ok": chain_ok,
        "payload_unreadable": payload_unreadable,
        "dek_destroyed": dek_destroyed,
        "error": error,
    }
    _write_report(report)
    if not passed:
        _alert_failure(report)
    return report


def _write_report(report: dict[str, Any]) -> None:
    rid = "edrill_" + new_ulid()
    with ops_con() as con:
        _ensure_reports(con)
        con.execute(
            """
            INSERT INTO erasure_drill_reports
            (report_id, ran_at, interaction_id, passed, chain_ok,
             payload_unreadable, dek_destroyed, error, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                rid,
                utc_now().replace(tzinfo=None),
                report.get("interaction_id"),
                bool(report.get("passed")),
                bool(report.get("chain_ok")),
                bool(report.get("payload_unreadable")),
                bool(report.get("dek_destroyed")),
                report.get("error"),
                json.dumps({k: v for k, v in report.items() if k != "error"}),
            ],
        )


def _alert_failure(report: dict[str, Any]) -> None:
    try:
        import asyncio

        from src.frontline.alerts import fire_alert

        async def _go() -> None:
            await fire_alert(
                "erasure_drill_failed",
                f"Weekly erasure drill failed: {report.get('error') or 'checks failed'}",
                report.get("interaction_id") or "erasure_drill",
                extra={"passed": False},
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_go())
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Run the crypto-shred erasure drill")
    p.add_argument(
        "--weekly",
        action="store_true",
        help="skip if a drill ran in the last 7 days",
    )
    args = p.parse_args(argv)
    result = maybe_run_weekly_drill() if args.weekly else run_erasure_drill()
    if result is None:
        print("skipped: last drill within 7 days")
        return 0
    print(json.dumps(result, default=str))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
