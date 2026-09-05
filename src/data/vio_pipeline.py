"""Vehicles-in-Operation (VIO) and fleet exposure ingestion pipeline (0-R3)."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import apply_domain_schema, domain_con


def calculate_incident_rate(
    record_count: int,
    exposure_units: float | None,
) -> tuple[float, str]:
    """
    Normalization Rule:
    Incident Rate_w = Record Count_w / (Exposure Units_w / 1,000)
    If exposure_units is missing/zero, falls back to raw count with method='raw-count-unnormalized'.
    """
    if exposure_units and float(exposure_units) > 0:
        rate = float(record_count) / (float(exposure_units) / 1000.0)
        return rate, "per_1000_exposure_units"
    return float(record_count), "raw-count-unnormalized"


def ingest_vio_data(
    records: list[dict[str, Any]],
    *,
    pack_id: str,
    default_source: str = "ihs_polk",
    default_unit_type: str = "vehicles_in_operation",
) -> dict[str, Any]:
    """Ingest structured VIO exposure rows into the ops warehouse."""
    if not records:
        return {"inserted": 0, "errors": 0, "pack_id": pack_id}

    now = utc_now()
    inserted = 0
    errors = 0

    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        for r in records:
            iso_week = str(r.get("iso_week") or "").strip()
            category = (r.get("category") or "").strip() or None
            entity_2 = (r.get("entity_2") or r.get("make") or "").strip().upper() or None
            raw_units = r.get("exposure_units")

            if not iso_week or raw_units is None:
                errors += 1
                continue

            try:
                units = float(raw_units)
                if units <= 0:
                    errors += 1
                    continue
            except (ValueError, TypeError):
                errors += 1
                continue

            unit = str(r.get("unit") or "units").strip()
            unit_type = str(r.get("unit_type") or default_unit_type).strip()
            source = str(r.get("source") or default_source).strip()

            con.execute(
                """
                INSERT OR REPLACE INTO exposure (
                    pack_id, iso_week, category, entity_2, exposure_units, unit,
                    unit_type, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [pack_id, iso_week, category, entity_2, units, unit, unit_type, source, now],
            )
            inserted += 1

    return {
        "inserted": inserted,
        "errors": errors,
        "pack_id": pack_id,
        "source": default_source,
    }


def ingest_vio_csv(
    pack_id: str,
    csv_file: str | Path | io.StringIO,
    *,
    source: str = "ihs_polk",
    unit_type: str = "vehicles_in_operation",
) -> dict[str, Any]:
    """Ingest a CSV of exposure denominators into the ops warehouse."""
    if isinstance(csv_file, (str, Path)):
        p = Path(csv_file)
        if not p.is_file():
            raise FileNotFoundError(f"VIO CSV file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records = list(reader)
    else:
        reader = csv.DictReader(csv_file)
        records = list(reader)

    return ingest_vio_data(
        records,
        pack_id=pack_id,
        default_source=source,
        default_unit_type=unit_type,
    )


__all__ = [
    "calculate_incident_rate",
    "ingest_vio_data",
    "ingest_vio_csv",
]
