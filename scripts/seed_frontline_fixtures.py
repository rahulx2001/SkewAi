"""Build the ops warehouse + seed both domain fixtures.

Equivalent to:
    make frontline-db
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path when invoked as `python -m scripts.seed_frontline_fixtures`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.warehouse import init_ops_db, reset_ops_db
from scripts.seed_domains import build as build_automotive
from scripts.seed_finance_cfpb import build as build_finance


def main() -> int:
    # Intentional full pilot rebuild — same allow path as `make frontline-db`.
    # Domain seeds require force when FRONTLINE_ALLOW_DEFAULT_DB_RESET is unset.
    print("→ Building ops warehouse (data/frontline.duckdb)…")
    reset_ops_db()
    init_ops_db()
    print("  ✓ ops warehouse ready.")

    print("→ Seeding automotive_nhtsa domain fixture…")
    path = build_automotive("automotive_nhtsa", force=True)
    print(f"  ✓ domain warehouse ready: {path}")

    print("→ Seeding finance_cfpb domain fixture…")
    path = build_finance("finance_cfpb", force=True)
    print(f"  ✓ domain warehouse ready: {path}")

    print("\nDone. Next: make contact   (or)   make pack-lint PACK=automotive_nhtsa")
    return 0


if __name__ == "__main__":
    sys.exit(main())
