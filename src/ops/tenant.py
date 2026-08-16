"""Multi-tenancy with row-level isolation (feature #52) — pilot query layer.

Every ops query that goes through ``tenant_clause`` gets ``tenant_id = ?``.
Default tenant is ``default``. Not full SaaS isolation; single query seam.
"""

from __future__ import annotations

import contextvars
from typing import Any

_current_tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
    "frontline_tenant_id", default="default"
)


def set_tenant(tenant_id: str) -> contextvars.Token:
    tid = (tenant_id or "default").strip() or "default"
    return _current_tenant.set(tid)


def get_tenant() -> str:
    return _current_tenant.get() or "default"


def reset_tenant(token: contextvars.Token) -> None:
    _current_tenant.reset(token)


def tenant_clause(alias: str | None = None) -> tuple[str, list[Any]]:
    """Return SQL fragment and params for tenant filter."""
    col = f"{alias}.tenant_id" if alias else "tenant_id"
    return f"{col} = ?", [get_tenant()]


def with_tenant(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.setdefault("tenant_id", get_tenant())
    return out


def ensure_tenant_column(con, table: str) -> None:
    """Best-effort ADD COLUMN for DuckDB pilots (table name allowlisted)."""
    from src.security.sql_ident import SAFE_ALTER_COLUMNS, safe_ident, safe_table

    try:
        t = safe_table(table)
        c = safe_ident("tenant_id", SAFE_ALTER_COLUMNS, kind="column")
        con.execute(
            f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} VARCHAR DEFAULT 'default'"
        )
    except Exception:
        try:
            t = safe_table(table)
            c = safe_ident("tenant_id", SAFE_ALTER_COLUMNS, kind="column")
            con.execute(f"ALTER TABLE {t} ADD COLUMN {c} VARCHAR DEFAULT 'default'")
        except Exception:
            pass
