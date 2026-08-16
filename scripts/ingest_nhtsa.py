"""Ingest real NHTSA complaints through the pack mapping.yaml loader.

This is **not** ``ingest_scale`` (synthetic clones of the 10-row fixture).

Usage
-----
    python -m scripts.ingest_nhtsa --limit 50000
    python -m scripts.ingest_nhtsa --csv /path/to/complaints.csv --limit 50000
    NHTSA_COMPLAINTS_CSV=/path/to/file.csv python -m scripts.ingest_nhtsa

Download (when ``--csv`` / env is unset):
    Official ODI flat file ZIP: https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip
    Converted to a headered CSV whose columns match
    ``domains/automotive_nhtsa/data/mapping.yaml``.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import REPO_ROOT
from src.domains.mapping_ingest import ingest_mapped_csv

PACK_ID = "automotive_nhtsa"
DEFAULT_LIMIT = 50_000
NHTSA_FLAT_URL = "https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip"

# Official FLAT_CMPL column order (NHTSA CMPL.txt). Mapping.yaml uses
# CMPLID / DATEA / DATEC / MODEL_YR / MAKETXT / MODELTXT / CDESC / NUM_CYLS / STATE.
_FLAT_FIELDS = [
    "CMPLID",
    "ODINO",
    "MFR_NAME",
    "MAKETXT",
    "MODELTXT",
    "YEARTXT",
    "CRASH",
    "FAILDATE",
    "FIRE",
    "INJURED",
    "DEATHS",
    "COMPDESC",
    "CITY",
    "STATE",
    "VIN",
    "DATEA",
    "LDATE",
    "MILES",
    "OCCURENCES",
    "CDESCR",
    "CMPL_TYPE",
    "POLICE_RPT_YN",
    "PURCH_DT",
    "ORIG_OWNER_YN",
    "ANTI_BRAKES_YN",
    "CRUISE_CONT_YN",
    "NUM_CYLS",
    "DRIVE_TRAIN",
    "FUEL_SYS",
    "FUEL_TYPE",
    "TRANS_TYPE",
    "VEH_SPEED",
    "DOT",
    "TIRE_SIZE",
    "LOC_OF_TIRE",
    "TIRE_FAIL_TYPE",
    "ORIG_EQUIP_YN",
    "MANUF_DT",
    "SEAT_TYPE",
    "RESTRAINT_TYPE",
    "DEALER_NAME",
    "DEALER_TEL",
    "DEALER_CITY",
    "DEALER_STATE",
    "DEALER_ZIP",
    "PROD_TYPE",
    "REPAIRED_YN",
    "MEDICAL_ATTN",
    "VEHICLES_TOWED_YN",
]

CSV_HEADERS = [
    "CMPLID",
    "DATEA",
    "DATEC",
    "MODEL_YR",
    "MAKETXT",
    "MODELTXT",
    "CDESC",
    "NUM_CYLS",
    "STATE",
]


def flat_line_to_mapping_row(line: str) -> dict[str, str] | None:
    """Parse one tab-delimited FLAT_CMPL line into mapping.yaml headers."""
    parts = line.rstrip("\n\r").split("\t")
    if len(parts) < 20:
        parts = line.rstrip("\n\r").split("|")
    if len(parts) < 16:
        return None
    raw = {name: (parts[i].strip() if i < len(parts) else "") for i, name in enumerate(_FLAT_FIELDS)}
    text = raw.get("CDESCR") or raw.get("COMPDESC") or ""
    if not raw.get("CMPLID") or not text:
        return None
    return {
        "CMPLID": raw["CMPLID"],
        "DATEA": raw.get("DATEA") or "",
        "DATEC": raw.get("FAILDATE") or "",
        "MODEL_YR": raw.get("YEARTXT") or "",
        "MAKETXT": raw.get("MAKETXT") or "",
        "MODELTXT": raw.get("MODELTXT") or "",
        "CDESC": text,
        "NUM_CYLS": raw.get("NUM_CYLS") or "",
        "STATE": raw.get("STATE") or "",
    }


def write_mapping_csv_from_flat(
    flat_lines: Iterable[str],
    dest: Path,
    *,
    limit: int,
) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with dest.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for line in flat_lines:
            if not line.strip():
                continue
            row = flat_line_to_mapping_row(line)
            if row is None:
                continue
            writer.writerow(row)
            written += 1
            if written >= limit:
                break
    return written


def _download_flat_zip(url: str, dest_zip: Path) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "skewai-nhtsa-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest_zip.open("wb") as fh:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)


def _iter_flat_from_zip(zip_path: Path) -> Iterable[str]:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise RuntimeError(f"empty zip: {zip_path}")
        with zf.open(names[0]) as raw:
            wrapper = io.TextIOWrapper(raw, encoding="latin-1", errors="replace")
            yield from wrapper


def resolve_complaints_csv(*, csv_arg: str | None, limit: int, work_dir: Path) -> tuple[Path, str]:
    """Return (csv_path, provenance). provenance is 'local' or 'nhtsa_flat_download'."""
    local = csv_arg or os.environ.get("NHTSA_COMPLAINTS_CSV", "").strip()
    if local:
        p = Path(local).expanduser()
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        if not p.exists():
            raise FileNotFoundError(f"NHTSA CSV not found: {p}")
        return p, "local"

    zip_path = work_dir / "FLAT_CMPL.zip"
    csv_path = work_dir / "nhtsa_complaints_mapped.csv"
    _download_flat_zip(NHTSA_FLAT_URL, zip_path)
    n = write_mapping_csv_from_flat(_iter_flat_from_zip(zip_path), csv_path, limit=limit)
    if n == 0:
        raise RuntimeError("FLAT_CMPL produced 0 mapped rows")
    return csv_path, "nhtsa_flat_download"


def run(
    *,
    pack_id: str = PACK_ID,
    csv_path: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    work = Path(tempfile.mkdtemp(prefix="skewai-nhtsa-"))
    try:
        src, provenance = resolve_complaints_csv(csv_arg=csv_path, limit=limit, work_dir=work)
        result = ingest_mapped_csv(
            pack_id, src, limit=limit, enforce_trust=False
        )
        result["provenance"] = provenance
        result["limit"] = limit
        result["ok"] = True
        result["error"] = None
        return result
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, FileNotFoundError) as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "provenance": "failed",
            "limit": limit,
            "pack_id": pack_id,
            "upserted": 0,
        }
    finally:
        # Keep converted CSV if download succeeded is unnecessary; tmp cleaned by OS.
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ingest real NHTSA complaints via mapping.yaml")
    p.add_argument("--pack", default=PACK_ID)
    p.add_argument("--csv", default=None, help="Local headered CSV (skips download)")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = p.parse_args(argv)
    result = run(pack_id=args.pack, csv_path=args.csv, limit=args.limit)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
