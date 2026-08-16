"""CLI: verify hash chain for an interaction (or all recent).

    python -m scripts.verify_ledger_chain --interaction int_xxx
    python -m scripts.verify_ledger_chain --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.warehouse import ops_con
from src.ledger.chain import verify_chain
from src.ledger.writer import list_actions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interaction", default="")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    ids: list[str] = []
    if args.interaction:
        ids = [args.interaction]
    elif args.all:
        with ops_con(read_only=True) as con:
            rows = con.execute(
                "SELECT DISTINCT interaction_id FROM agent_actions LIMIT 200"
            ).fetchall()
        ids = [r[0] for r in rows]
    else:
        print("pass --interaction ID or --all")
        return 2

    bad = 0
    for iid in ids:
        rows = list_actions(iid)
        res = verify_chain(rows)
        status = "OK" if res["ok"] else "FAIL"
        print(f"{status} {iid} checked={res['checked']} {res.get('detail')}")
        if not res["ok"]:
            bad += 1
            print(f"  first_bad={res.get('first_bad_action_id')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
