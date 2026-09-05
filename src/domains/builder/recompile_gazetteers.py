"""Recompile domain pack gazetteers from warehouse records (audit 3.4).

CLI: python -m src.domains.builder.recompile_gazetteers --pack automotive_nhtsa
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import REPO_ROOT
from src.data.warehouse import domain_con
from src.domains.loader import load_pack


def recompile_pack_gazetteers(
    pack_id: str,
    *,
    min_count: int = 1,
    backup: bool = True,
) -> dict[str, Any]:
    """Extract observed entities from warehouse `records` and update pack gazetteers."""
    pack = load_pack(pack_id)
    gaz_dir = REPO_ROOT / "domains" / pack_id / "gazetteers"
    if not gaz_dir.exists():
        gaz_dir.mkdir(parents=True, exist_ok=True)

    with domain_con(pack_id, read_only=True) as con:
        rows = con.execute(
            """
            SELECT entity_1, entity_2, entity_3, category, COUNT(*) as cnt
            FROM records
            GROUP BY entity_1, entity_2, entity_3, category
            HAVING COUNT(*) >= ?
            """,
            [min_count],
        ).fetchall()

    e1_set: set[str] = set()
    e2_set: set[str] = set()
    e3_set: set[str] = set()
    cat_set: set[str] = set()

    for r in rows:
        e1, e2, e3, cat = r[0], r[1], r[2], r[3]
        if e1 and str(e1).strip():
            e1_set.add(str(e1).strip())
        if e2 and str(e2).strip():
            e2_set.add(str(e2).strip())
        if e3 and str(e3).strip():
            e3_set.add(str(e3).strip())
        if cat and str(cat).strip():
            cat_set.add(str(cat).strip())

    # Determine valid gazetteer targets from the pack manifest
    slot_mapping: dict[str, set[str]] = {}
    for slot in pack.manifest.slot_frame:
        if slot.validation == "gazetteer" and slot.gazetteer:
            filename = f"{slot.gazetteer}.csv"
            if slot.name == "entity_1":
                slot_mapping[filename] = e1_set
            elif slot.name == "entity_2":
                slot_mapping[filename] = e2_set
            elif slot.name == "entity_3":
                slot_mapping[filename] = e3_set
            elif slot.name == "category":
                slot_mapping[filename] = cat_set

    updated_files: list[str] = []
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    for filename, new_values in slot_mapping.items():
        target_file = gaz_dir / filename
        if not target_file.exists() and not new_values:
            continue

        existing_entries: dict[str, str | None] = {}  # canonical -> extra col
        if target_file.exists():
            if backup:
                backup_dir = gaz_dir / ".backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target_file, backup_dir / f"{filename}.{timestamp}.bak")
            try:
                with target_file.open("r", encoding="utf-8", newline="", errors="replace") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    for row in reader:
                        if not row:
                            continue
                        val = row[0].strip()
                        if val and not val.startswith("#"):
                            extra = row[1].strip() if len(row) > 1 else None
                            existing_entries[val] = extra
            except Exception:
                pass

        for nv in new_values:
            if nv not in existing_entries:
                existing_entries[nv] = None

        if existing_entries:
            with target_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["value", "frequency"])
                for val in sorted(existing_entries.keys()):
                    extra = existing_entries[val]
                    if extra:
                        writer.writerow([val, extra])
                    else:
                        writer.writerow([val])
            updated_files.append(str(target_file))

    return {
        "pack_id": pack_id,
        "min_count": min_count,
        "records_scanned": len(rows),
        "entities_found": {
            "entity_1": len(e1_set),
            "entity_2": len(e2_set),
            "entity_3": len(e3_set),
            "category": len(cat_set),
        },
        "updated_files": updated_files,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recompile pack gazetteers from warehouse records")
    ap.add_argument("--pack", required=True, help="Pack identifier (e.g. automotive_nhtsa)")
    ap.add_argument("--min-count", type=int, default=1, help="Minimum record occurrences")
    ap.add_argument("--no-backup", action="store_true", help="Skip creating backups")
    args = ap.parse_args(argv)

    try:
        report = recompile_pack_gazetteers(
            args.pack,
            min_count=args.min_count,
            backup=not args.no_backup,
        )
        print(f"Recompiled gazetteers for '{args.pack}':")
        print(f"  Records scanned: {report['records_scanned']}")
        print(f"  Files updated: {len(report['updated_files'])}")
        for f in report["updated_files"]:
            print(f"    - {f}")
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
