"""Postgres dual-backend seam (feature #45).

DuckDB remains the default ops warehouse. When ``FRONTLINE_OPS_DSN`` is set to a
Postgres URL, write/read helpers can route through SQLAlchemy/psycopg-style
connections. Without the DSN (CI), this module exposes the same API but
delegates to DuckDB — migrations are Alembic-ready SQL files under
``migrations/``.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from src.data.warehouse import ops_con as duckdb_ops_con


def ops_backend() -> str:
    dsn = os.getenv("FRONTLINE_OPS_DSN", "").strip()
    if dsn.startswith("postgres"):
        return "postgres"
    return "duckdb"


def alembic_ready() -> bool:
    from pathlib import Path
    from src.config import REPO_ROOT

    return (REPO_ROOT / "migrations" / "versions").is_dir() or (
        REPO_ROOT / "migrations" / "001_ops_init.sql"
    ).is_file()


@contextmanager
def ops_connection(read_only: bool = False) -> Iterator[Any]:
    """Yield a DB connection for ops. Postgres when DSN set, else DuckDB."""
    if ops_backend() == "postgres":
        try:
            import psycopg

            dsn = os.environ["FRONTLINE_OPS_DSN"]
            conn = psycopg.connect(dsn)
            try:
                yield conn
                if not read_only:
                    conn.commit()
            finally:
                conn.close()
            return
        except Exception as e:
            # Fall back to DuckDB with marker rather than crash pilot
            with duckdb_ops_con(read_only=read_only) as con:
                yield _Tagged(con, backend="duckdb", postgres_error=str(e))
            return
    with duckdb_ops_con(read_only=read_only) as con:
        yield _Tagged(con, backend="duckdb")


class _Tagged:
    """Thin proxy so callers can inspect ``.backend``."""

    def __init__(self, con: Any, *, backend: str, postgres_error: str | None = None) -> None:
        self._con = con
        self.backend = backend
        self.postgres_error = postgres_error

    def execute(self, *a: Any, **k: Any) -> Any:
        return self._con.execute(*a, **k)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._con, name)


def backend_status() -> dict[str, Any]:
    return {
        "ops_backend": ops_backend(),
        "alembic_ready": alembic_ready(),
        "dsn_set": bool(os.getenv("FRONTLINE_OPS_DSN", "").strip()),
        "note": "DuckDB default; set FRONTLINE_OPS_DSN=postgresql://... for Postgres writes",
    }
