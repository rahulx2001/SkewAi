"""Gating tests for the 2026-08-16 findings inventory (H1–H4, M1/M3/M6, L1–L3)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.data.timeutil import utc_now
from src.data.trust import schema_contract_ok
from src.data.warehouse import ops_con
from src.frontline.oidc import (
    consume_handoff,
    handoff_expired,
    provider_status,
    save_local_provider,
)
from src.frontline.outreach import notify_affected_owners, register_owner
from src.jobs.registry import is_live_heartbeat, list_workers, register_worker


def test_h1_stale_workers_excluded_from_health(reset_ops_db):
    from src.jobs.registry import _ensure, WORKER_TTL_S

    stale_id = "w_stale_inventory"
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO worker_registry (worker_id, host, heartbeat_at, status)
            VALUES (?, 'old', ?, 'up')
            """,
            [stale_id, utc_now() - timedelta(seconds=WORKER_TTL_S + 30)],
        )
    live = register_worker(host="test-live")
    ids = {w["worker_id"] for w in list_workers()}
    assert live["worker_id"] in ids
    assert stale_id not in ids
    assert is_live_heartbeat(utc_now() - timedelta(seconds=5)) is True
    assert is_live_heartbeat(utc_now() - timedelta(seconds=WORKER_TTL_S + 5)) is False

    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["worker_count"] >= 1
    assert "soc2_engineering_baseline" not in body
    assert body.get("soc2_engineering_baseline") is not True


def test_h3_json_session_mint_closed(reset_ops_db, monkeypatch):
    monkeypatch.setenv("FRONTLINE_OPEN_MODE", "1")
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as client:
        r = client.post(
            "/api/frontline/auth/session",
            json={"subject": "auditor", "role": "admin"},
        )
    assert r.status_code == 403
    assert "token" not in (r.json() or {}) or not r.json().get("token")


def test_h4_expired_handoff_rejected(reset_ops_db):
    from src.frontline.oidc import _ensure, HANDOFF_TTL_S

    hid = "hf_expired_inventory"
    created = utc_now() - timedelta(seconds=HANDOFF_TTL_S + 5)
    assert handoff_expired(created) is True
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO oidc_handoffs
            (handoff_id, token, subject, email, role, exp, created_at, used)
            VALUES (?, 'tok', 'a@b.com', 'a@b.com', 'agent', 0, ?, FALSE)
            """,
            [hid, created],
        )
    with pytest.raises(ValueError, match="handoff_expired"):
        consume_handoff(hid)


def test_m1_schema_rejects_unknown_fields():
    ok, reason = schema_contract_ok(
        {"record_id": "r1", "text": "brake fade", "mystery_col": "x"}
    )
    assert ok is False
    assert "unknown field" in reason


def test_m3_oidc_finish_does_not_use_admin_issuer():
    src = Path("src/frontline/oidc.py").read_text(encoding="utf-8")
    assert 'issuer_role="admin"' not in src
    assert "issue_idp_session" in src


def test_m6_untrusted_ingest_requires_explicit_flag():
    from src.domains.mapping_ingest import ingest_mapped_csv
    from src.security.identifiers import InvalidIdentifier

    # Path jail fires first. /tmp is tempfile.gettempdir() on Linux CI, so
    # pytest adds it to the jail; /etc is never an allowed root.
    with pytest.raises(InvalidIdentifier):
        ingest_mapped_csv(
            "automotive_nhtsa",
            "/etc/does-not-matter.csv",
            enforce_trust=False,
        )
    # Inside the jail, the untrusted-ingest flag is still required.
    with pytest.raises(ValueError, match="allow_untrusted_historical_backfill"):
        ingest_mapped_csv(
            "automotive_nhtsa",
            "domains/automotive_nhtsa/gazetteers/makes.csv",
            enforce_trust=False,
        )
    nhtsa = Path("scripts/ingest_nhtsa.py").read_text(encoding="utf-8")
    assert "allow_untrusted_historical_backfill=True" in nhtsa


def test_regulator_watch_error_does_not_leak_paths(monkeypatch, reset_ops_db):
    def _boom(*_a, **_k):
        raise FileNotFoundError("/Users/rahulkumarsinghj/secret.duckdb")

    monkeypatch.setattr("src.domains.loader.load_pack", _boom)
    from src.frontline.analytics import regulator_filing_watch

    out = regulator_filing_watch(pack_id="automotive_nhtsa")
    blob = str(out)
    assert "/Users/" not in blob
    assert "secret.duckdb" not in blob
    assert out.get("error") == "FileNotFoundError"


def test_l1_browser_helper_has_no_passwordless_signin():
    src = Path("dashboard/src/apiAuth.js").read_text(encoding="utf-8")
    assert "export async function signIn" not in src
    assert "SESSION_STORAGE" not in src
    assert "localStorage.setItem" not in src or "frontline_session" not in src
    assert "completeGoogleHandoff" in src


def test_l3_notify_records_ledger_and_does_not_swallow(
    reset_ops_db, seed_automotive_pack, monkeypatch
):
    pack_id = "automotive_nhtsa"
    register_owner(
        pack_id=pack_id,
        entity_2="HONDA",
        entity_3="CR-V",
        cluster_id=3,
        channel="email",
        address="owner@example.com",
    )
    out = notify_affected_owners(pack_id=pack_id, cluster_id=3, entity_2="HONDA")
    assert out["count"] == 1
    assert out["ledger_recorded"] is True
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM agent_actions WHERE action_type = 'alert_sent'"
        ).fetchone()
    assert int(n[0]) >= 1

    def _boom(*_a, **_k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr("src.frontline.outreach.record_action", _boom)
    with pytest.raises(RuntimeError, match="ledger down"):
        notify_affected_owners(pack_id=pack_id, cluster_id=3, entity_2="HONDA")


def test_google_local_config_wires_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("OIDC_LOCAL_PATH", str(tmp_path / "oidc.json"))
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PILOT_HARDENED", raising=False)
    monkeypatch.delenv("SOC2_MODE", raising=False)
    assert provider_status()["configured"] is False
    save_local_provider(
        client_id="1234567890-local.apps.googleusercontent.com",
        client_secret="GOCSPX-local-test-secret",
    )
    st = provider_status()
    assert st["configured"] is True
    assert st["provider"] == "google"
    assert st["source"] == "local"
    assert st["authorization_endpoint"].startswith("https://accounts.google.com/")


def test_google_config_http_then_start(reset_ops_db, tmp_path, monkeypatch):
    monkeypatch.setenv("OIDC_LOCAL_PATH", str(tmp_path / "oidc.json"))
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PILOT_HARDENED", raising=False)
    monkeypatch.setenv("FRONTLINE_OPEN_MODE", "1")
    with TestClient(app) as client:
        denied = client.put(
            "/api/frontline/auth/oidc/config",
            json={"client_id": "short", "client_secret": "x"},
        )
        assert denied.status_code == 400
        saved = client.put(
            "/api/frontline/auth/oidc/config",
            json={
                "client_id": "1234567890-http.apps.googleusercontent.com",
                "client_secret": "GOCSPX-http-test-secret",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["configured"] is True
        st = client.get("/api/frontline/auth/oidc/status")
        assert st.json()["configured"] is True
        start = client.get(
            "/api/frontline/auth/oidc/start",
            params={"next": "http://127.0.0.1:8787/ui/"},
            follow_redirects=False,
        )
        assert start.status_code == 302
        assert start.headers["location"].startswith(
            "https://accounts.google.com/o/oauth2/v2/auth"
        )
