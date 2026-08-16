"""Age-based retention for unbounded ops tables (pilot hygiene).

Deletes rows older than a configurable retention window. Safe to re-run.
Not a full compliance DSAR product — just stops unbounded growth of:
  alert_dedup, alert_dead_letter, connector_deliveries, risk_snapshots,
  agent_actions, interaction_turns (optional).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con

# Default retention days (env override: FRONTLINE_PRUNE_DAYS)
_DEFAULT_DAYS = 30

# Tables / column used for age filter
_PRUNE_TARGETS: list[tuple[str, str]] = [
    ("alert_dedup", "fired_at"),
    ("alert_dead_letter", "created_at"),
    ("connector_deliveries", "created_at"),
    ("risk_snapshots", "ts"),
    ("agent_actions", "ts"),
    ("interaction_turns", "ts"),
]


def prune_days() -> int:
    raw = os.getenv("FRONTLINE_PRUNE_DAYS", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_DAYS


def prune_ops_tables(
    *,
    older_than_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Delete aged rows from growth tables. Returns counts deleted per table."""
    days = older_than_days if older_than_days is not None else prune_days()
    cutoff = (now or utc_now()) - timedelta(days=days)
    # Compare as naive UTC wall clock (same basis as writers).
    if cutoff.tzinfo is not None:
        cutoff = cutoff.astimezone(timezone.utc).replace(tzinfo=None)

    from src.security.sql_ident import safe_column, safe_table

    deleted: dict[str, int] = {}
    with ops_con() as con:
        for table, col in _PRUNE_TARGETS:
            try:
                t = safe_table(table)
                c = safe_column(col)
                before = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                con.execute(
                    f"DELETE FROM {t} WHERE {c} IS NOT NULL AND {c} < ?",
                    [cutoff],
                )
                after = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                deleted[table] = int(before) - int(after)
            except Exception as e:
                deleted[table] = -1  # table missing or column mismatch
                deleted[f"{table}_error"] = f"{type(e).__name__}:{e}"

    return {
        "cutoff": cutoff.isoformat() + "Z",
        "older_than_days": days,
        "deleted": deleted,
    }


__all__ = ["prune_ops_tables", "prune_days"]
