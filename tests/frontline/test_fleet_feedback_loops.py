"""Fleet feedback loop and cross-source verification tests (0-R2, 0-R3, 8-R4)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
import pytest

from src.data.timeutil import utc_now
from src.data.vio_pipeline import calculate_incident_rate, ingest_vio_csv, ingest_vio_data
from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.ml_runtime.entity_resolution import (
    find_canonical_identity,
    get_or_create_canonical_identity,
    record_entity_observation,
)


# ── 1. Canonical Identity Cross-Source Join (0-R2) ──────────────────────────

def test_canonical_identity_cross_source_join(reset_ops_db):
    vin = "1HGCM82633A004352"

    # Source 1: Frontline voice contact observes spoken VIN
    obs_id = record_entity_observation(
        interaction_id="int_001",
        raw_spoken_text="my vehicle is 1HGCM82633A004352",
        extracted_vin=vin,
        confidence=0.92,
        vin_status="candidate_checksum_valid",
        source_channel="voice",
    )
    assert obs_id.startswith("obs_")

    # Associate with canonical identity
    canon_frontline = get_or_create_canonical_identity(
        vin=vin,
        make="HONDA",
        model="ACCORD",
        year=2003,
        identity_status="candidate_checksum_valid",
        source="voice_intake",
    )
    assert canon_frontline["canonical_id"].startswith("cid_")
    assert canon_frontline["identity_status"] == "candidate_checksum_valid"

    # Source 2: Warranty claim arrives for same VIN
    canon_warranty = get_or_create_canonical_identity(
        vin=vin,
        make="HONDA",
        model="ACCORD",
        year=2003,
        identity_status="customer_confirmed",
        source="warranty",
    )

    # Must resolve to the exact same canonical_id
    assert canon_warranty["canonical_id"] == canon_frontline["canonical_id"]

    # Lookup confirms persistence
    found = find_canonical_identity(vin)
    assert found is not None
    assert found["canonical_id"] == canon_frontline["canonical_id"]
    assert found["make"] == "HONDA"


# ── 2. VIO Exposure Ingestion Pipeline & Normalization (0-R3) ───────────────

def test_vio_exposure_pipeline_and_normalization(reset_ops_db):
    # Test normalization formula
    # 50 complaints on 20,000 exposure units -> (50 / (20,000 / 1,000)) = 2.5 per 1,000 units
    rate, method = calculate_incident_rate(record_count=50, exposure_units=20000.0)
    assert rate == pytest.approx(2.5)
    assert method == "per_1000_exposure_units"

    # Missing exposure fallback
    raw_rate, raw_method = calculate_incident_rate(record_count=50, exposure_units=None)
    assert raw_rate == 50.0
    assert raw_method == "raw-count-unnormalized"

    # Ingest production VIO CSV
    csv_text = (
        "iso_week,category,make,exposure_units,unit_type,source\n"
        "2026-W22,SERVICE BRAKES,HONDA,50000,vehicles_in_operation,ihs_polk\n"
        "2026-W22,ENGINE,HONDA,48000,vehicles_in_operation,ihs_polk\n"
    )
    csv_data = io.StringIO(csv_text)
    report = ingest_vio_csv(pack_id="automotive_nhtsa", csv_file=csv_data)
    assert report["inserted"] == 2
    assert report["errors"] == 0

    from src.data.warehouse import domain_con

    with domain_con("automotive_nhtsa") as con:
        rows = con.execute(
            "SELECT iso_week, category, entity_2, exposure_units, unit_type, source FROM exposure WHERE pack_id = ?",
            ["automotive_nhtsa"],
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "2026-W22"
        assert rows[0][4] == "vehicles_in_operation"
        assert rows[0][5] == "ihs_polk"


# ── 3. Fix Regression Automated P1 Alert Broadcast (8-R4) ────────────────────

@pytest.mark.asyncio
async def test_fix_regression_p1_alert_broadcast(reset_ops_db, pack):
    from unittest.mock import AsyncMock, patch
    from src.agents.orchestrator import create_interaction

    fix_id = "fix_" + new_ulid()
    now = utc_now()

    # Step 1: Record a recent fix in warehouse (<90 days old)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO recorded_fixes (fix_id, pack_id, investigation_id, category, entity_2, entity_3, fixed_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [fix_id, pack.manifest.id, "inv_123", "SERVICE BRAKES", "HONDA", "CIVIC", now, "Master cylinder recall"],
        )

    # Step 2: New contact arrives matching the fixed slice
    orch, _ = await create_interaction(channel="text", pack_id=pack.manifest.id)
    slots = {"entity_2": "HONDA", "entity_3": "CIVIC", "category": "SERVICE BRAKES"}

    with patch("src.frontline.alerts.fire_alert", new_callable=AsyncMock) as mock_alert:
        orch._watch_fix_regression(category="SERVICE BRAKES", slots=slots, record_id="rec_test_999")

        # Allow async task to dispatch
        import asyncio
        await asyncio.sleep(0.05)

        # Step 3: Assert automated P1 alert was fired
        assert mock_alert.called
        call_kwargs = mock_alert.call_args.kwargs
        assert call_kwargs["event"] == "fix_regression"
        assert call_kwargs["ref_id"] == fix_id
        assert "[P1 CRITICAL]" in call_kwargs["summary"]
        assert call_kwargs["extra"]["priority"] == "P1"
        assert call_kwargs["extra"]["severity"] == "Critical"
        assert call_kwargs["extra"]["regression"] is True
