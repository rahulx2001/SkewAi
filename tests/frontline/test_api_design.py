"""API design contract: pagination meta, problem-shaped errors, version header."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.main import API_VERSION, app
from src.api.pagination import encode_cursor, page_meta, paginate_list
from src.api.problems import problem
from src.data.warehouse import ops_con


@pytest.fixture
def client(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


def _seed_cases(n: int = 5) -> None:
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        for i in range(n):
            iid = f"int_api_{i}"
            cid = f"case_api_{i}"
            con.execute(
                """
                INSERT INTO interactions
                (interaction_id, pack_id, pack_version, started_at, channel, status)
                VALUES (?, 'automotive_nhtsa', 't', ?, 'sim', 'completed')
                """,
                [iid, now],
            )
            con.execute(
                """
                INSERT INTO cases
                (case_id, interaction_id, pack_id, created_at, category, description_summary,
                 onset, severity, severity_source, priority, safety_flags, status, followup_draft)
                VALUES (?, ?, 'automotive_nhtsa', ?, 'brakes', 'd', ?, 'Low', 'rules', 3, '{}', 'open', '')
                """,
                [cid, iid, now, now],
            )


def test_problem_helper_shape():
    body = problem(404, "missing thing", instance="/api/x")
    assert body["type"] == "about:blank#not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["detail"] == "missing thing"
    assert body["instance"] == "/api/x"


def test_paginate_list_unit():
    page, meta = paginate_list(list(range(10)), limit=3, offset=3)
    assert page == [3, 4, 5]
    assert meta["has_more"] is True
    assert meta["next_offset"] == 6
    assert meta["next_cursor"] == encode_cursor(6)
    page2, meta2 = paginate_list(list(range(10)), limit=50, offset=0)
    assert meta2["has_more"] is False
    assert meta2["total"] == 10


def test_list_cases_pagination(client):
    _seed_cases(5)
    r = client.get("/api/frontline/cases?limit=2&offset=0")
    assert r.status_code == 200
    assert r.headers.get("api-version") == API_VERSION or r.headers.get("API-Version") == API_VERSION
    body = r.json()
    assert "cases" in body
    assert body["count"] == 2
    assert "pagination" in body
    p = body["pagination"]
    assert p["limit"] == 2
    assert p["offset"] == 0
    assert p["returned"] == 2
    assert p["has_more"] is True
    assert p["next_offset"] == 2
    assert p["next_cursor"]

    r2 = client.get(f"/api/frontline/cases?limit=2&cursor={p['next_cursor']}")
    assert r2.status_code == 200
    assert r2.json()["pagination"]["offset"] == 2


def test_list_interactions_pagination(client):
    _seed_cases(3)
    r = client.get("/api/interactions?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert "interactions" in body
    assert "pagination" in body
    assert body["pagination"]["returned"] == body["count"]


def test_404_problem_shape(client):
    r = client.get("/api/frontline/cases/case_does_not_exist")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert "type" in body
    assert isinstance(body["detail"], str)
    assert "case" in body["detail"].lower() or "not found" in body["detail"].lower()


def test_401_problem_shape(reset_ops_db, monkeypatch):
    monkeypatch.setenv("FRONTLINE_API_KEY", "design-secret")
    with TestClient(app) as c:
        r = c.get("/api/frontline/cases")
        assert r.status_code == 401
        body = r.json()
        assert body["status"] == 401
        assert body["type"] == "about:blank#unauthorized"
        assert "detail" in body
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)


def test_root_discovery(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["api_version"] == API_VERSION
    assert "links" in body
    assert body["links"]["cases"] == "/api/frontline/cases"
    assert "auth" in body


def test_health_api_version(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("api_version") == API_VERSION


def test_openapi_yaml_exists():
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "docs" / "openapi.yaml"
    text = p.read_text(encoding="utf-8")
    # Generated file may carry a `# ...` banner header; the OpenAPI document
    # itself must be the first non-comment line.
    first_doc_line = next((ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")), "")
    assert first_doc_line.startswith("openapi:")
    assert "/api/frontline/cases" in text
    assert "Problem" in text
    assert "pagination" in text.lower() or "Pagination" in text
