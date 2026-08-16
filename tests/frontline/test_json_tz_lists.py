"""JSON-safe UTC timestamps on list interactions / cases (M7 / M-NEW-2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.jsonutil import ensure_utc, json_safe
from src.api.main import app
from src.data.warehouse import ops_con
from src.ids import new_ulid


def test_json_safe_datetime_is_utc_z():
    naive = datetime(2026, 1, 2, 12, 0, 0)
    out = json_safe(naive)
    assert isinstance(out, str)
    assert out.endswith("Z") or "+00:00" in out
    aware = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert json_safe(aware).endswith("Z") or "+00:00" in json_safe(aware)
    assert ensure_utc(naive).tzinfo is not None


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


def test_list_interactions_json_encodable_with_iso_timestamps(client):
    iid = "int_jsontz_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, 'automotive_nhtsa', 't', ?, 'web_text', 'active', FALSE, 0)
            """,
            [iid, datetime.now(timezone.utc)],
        )
    r = client.get("/api/interactions", params={"limit": 10})
    assert r.status_code == 200
    # Body must already be JSON (no datetime encode error)
    body = r.json()
    assert body["count"] >= 1
    found = [x for x in body["interactions"] if x["interaction_id"] == iid]
    assert found
    started = found[0]["started_at"]
    assert isinstance(started, str)
    # Round-trip as JSON again
    json.dumps(body)


@pytest.mark.asyncio
async def test_list_cases_json_encodable(client):
    from src.agents.base import InteractionContext
    from src.agents.case_agent import CaseAgent
    from src.domains.loader import load_pack

    pack = load_pack("automotive_nhtsa", reload=True)
    iid = "int_casejson_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, 'automotive_nhtsa', 't', ?, 'web_text', 'active', FALSE, 0)
            """,
            [iid, datetime.now(timezone.utc)],
        )
    ctx = InteractionContext(interaction_id=iid, pack=pack)
    ctx.slots = {
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
        "description": "noise",
    }
    await CaseAgent(ctx).run()

    r = client.get("/api/frontline/cases", params={"limit": 20})
    assert r.status_code == 200
    body = r.json()
    json.dumps(body)
    assert body["count"] >= 1
    created = body["cases"][0].get("created_at")
    assert isinstance(created, str)
