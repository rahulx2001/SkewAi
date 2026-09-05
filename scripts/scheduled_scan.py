"""Scheduled fleet-scan runner (Axion slice, Phase 3).

Runs the whole-pack scan without any customer contact — the reliability
engineer's early warning:

    python -m scripts.scheduled_scan --pack automotive_nhtsa
    python -m scripts.scheduled_scan --all-packs --rebuild-clusters

Suggested cadence: every 30 minutes for anomaly/risk evaluation
(cheap: SQL + scoring), nightly with --rebuild-clusters (heavy:
re-embeds the corpus). Enqueue instead of running inline when workers
exist: the ``scheduled_scan`` job type runs the same function.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scheduled fleet scan")
    parser.add_argument("--pack", default="automotive_nhtsa")
    parser.add_argument("--all-packs", action="store_true")
    parser.add_argument("--rebuild-clusters", action="store_true")
    parser.add_argument("--no-alert", action="store_true")
    args = parser.parse_args(argv)

    from src.domains.loader import list_packs
    from src.frontline.fleet_scan import run_fleet_scan

    packs = (
        [p for p in list_packs() if not p.startswith("_") and not p.startswith(".")]
        if args.all_packs
        else [args.pack]
    )
    reports = []
    for pack_id in packs:
        try:
            reports.append(
                run_fleet_scan(
                    pack_id,
                    rebuild_clusters=args.rebuild_clusters,
                    alert=not args.no_alert,
                )
            )
        except FileNotFoundError as e:
            reports.append({"pack_id": pack_id, "error": f"no warehouse: {e}"})
        except Exception as e:
            reports.append({"pack_id": pack_id, "error": f"{type(e).__name__}: {e}"})
    print(json.dumps(reports, indent=2, default=str))
    failed = [r for r in reports if r.get("error") or r.get("errors")]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
