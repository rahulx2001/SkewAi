"""F-054: pack_id / path identifiers cannot traverse onto the filesystem."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.security.identifiers import (
    InvalidIdentifier,
    safe_cluster_id,
    safe_out_dir,
    safe_pack_id,
    safe_token_id,
)


def test_safe_pack_id_rejects_traversal_null_oversize_and_unicode():
    with pytest.raises(InvalidIdentifier):
        safe_pack_id("../etc")
    with pytest.raises(InvalidIdentifier):
        safe_pack_id("foo/bar")
    with pytest.raises(InvalidIdentifier):
        safe_pack_id("automotive_nhtsa\x00.duckdb")
    with pytest.raises(InvalidIdentifier):
        safe_pack_id("a" * 10_000)
    with pytest.raises(InvalidIdentifier):
        safe_pack_id("ａｕｔｏｍｏｔｉｖｅ")  # fullwidth, NFKC-shifted
    assert safe_pack_id("automotive_nhtsa") == "automotive_nhtsa"
    assert safe_pack_id(None, optional=True) is None


def test_safe_token_and_cluster_id():
    assert safe_token_id("int_01HXTEST", kind="interaction_id").startswith("int_")
    with pytest.raises(InvalidIdentifier):
        safe_token_id("../int_x", kind="interaction_id")
    assert safe_cluster_id(14) == 14
    with pytest.raises(InvalidIdentifier):
        safe_cluster_id(-1)
    with pytest.raises(InvalidIdentifier):
        safe_cluster_id(99_999_999)


def test_domain_con_rejects_traversal_pack_id():
    from src.data.warehouse import domain_con

    with pytest.raises(InvalidIdentifier):
        with domain_con("../etc/passwd", read_only=True):
            pass


def test_out_dir_jail(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTLINE_EXPORT_DIR", str(tmp_path))
    allowed = safe_out_dir(tmp_path, default=tmp_path)
    assert allowed == tmp_path.resolve()
    with pytest.raises(InvalidIdentifier):
        safe_out_dir("/etc", default=tmp_path)


def test_gitignore_covers_root_duckdb():
    text = open(".gitignore", encoding="utf-8").read()
    assert "*.duckdb" in text.splitlines() or any(
        line.strip() == "*.duckdb" for line in text.splitlines()
    )


def test_api_pack_id_fuzz_rejected(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.delenv("FRONTLINE_AUTH_REQUIRED", raising=False)
    payloads = [
        "../etc",
        "..\\windows",
        "automotive_nhtsa\x00x",
        "a" * 10_000,
        "packs/../../secret",
        "AUTO\u2044nhtsa",
    ]
    paths = [
        "/api/frontline/simulate",
        "/api/frontline/hotspots",
        "/api/frontline/analytics/financial",
        "/api/frontline/analytics/fairness",
        "/api/frontline/wallboard",
        "/api/frontline/severity-drift",
        "/api/frontline/cohorts",
        "/api/frontline/regulator-watch",
        "/api/frontline/alert-rules",
        "/api/frontline/clusters/rebuild",
        "/api/enterprise/copq",
        "/api/enterprise/fix-effectiveness",
        "/api/frontline/provenance/open_cases",
        "/api/frontline/analytics/hotspots",
        "/api/frontline/analytics/severity-drift",
        "/api/frontline/analytics/cohorts",
        "/api/frontline/analytics/regulator",
        "/api/frontline/analytics/financial",
        "/api/frontline/analytics/fairness",
        "/api/frontline/packs/../etc",
        "/api/frontline/hotspots-map",
        "/api/frontline/financial",
        "/api/frontline/fairness",
        "/api/frontline/map/hotspots",
        "/api/v3/learning/trends",
    ]
    with TestClient(app) as c:
        for path in paths:
            for bad in payloads:
                r = c.get(path, params={"pack_id": bad})
                assert r.status_code in {400, 404, 405, 422}, (
                    f"{path} pack_id={bad!r} -> {r.status_code} {r.text[:120]}"
                )
                if r.status_code == 400:
                    # Guard actually fired (not just missing route).
                    pass


def test_api_investigation_and_cluster_path_ids_rejected(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/frontline/investigations/inv_.._etc").status_code == 400
        assert c.get("/api/frontline/investigations/%2e%2e%2fetc").status_code == 400
        assert c.get("/api/frontline/investigations/inv_ok").status_code != 400
        assert c.post("/api/frontline/clusters/-1/feedback", json={"verdict": "wrong"}).status_code == 400
        assert c.get("/api/frontline/clusters/14/feedback").status_code != 400


def test_api_valid_pack_id_not_rejected_as_400(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        r = c.get("/api/frontline/analytics/fairness", params={"pack_id": "automotive_nhtsa"})
        assert r.status_code != 400


def test_ws_connect_rate_limiter():
    from src.api.limiter import check_ws_connect_rate, _ws_hits

    _ws_hits.clear()
    key = "fuzz-client"
    for _ in range(30):
        assert check_ws_connect_rate(key) is True
    assert check_ws_connect_rate(key) is False


def test_start_and_ingest_are_rate_limited():
    import src.api.routes.interactions as m

    src = open(m.__file__, encoding="utf-8").read()
    assert '@limiter.limit("30 per minute")' in src
    assert "check_ws_connect_rate" in src
    assert src.count("check_ws_connect_rate") >= 2
