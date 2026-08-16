"""Engineering baseline tests supporting SOC 2 Security criteria (not a certificate)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.security.audit_log import read_recent, security_event
from src.security.harden import is_production_like, validate_startup_security


def test_production_like_detects_env(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    assert is_production_like() is True
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("SOC2_MODE", "1")
    assert is_production_like() is True


def test_startup_fails_closed_in_production_without_key(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("FRONTLINE_OPEN_MODE", "1")  # must still fail
    with pytest.raises(RuntimeError, match="Security startup check failed"):
        validate_startup_security()


def test_startup_ok_when_hardened_with_secrets(monkeypatch):
    monkeypatch.setenv("PILOT_HARDENED", "1")
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", "soc2-test-key-at-least-16")
    monkeypatch.setenv("SESSION_SECRET", "soc2-session-secret-32bytes!!!!")
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    status = validate_startup_security()
    assert status["ok"] is True
    assert status["production_like"] is True


def test_security_event_writes_jsonl(tmp_path, monkeypatch):
    from src.config import REPO_ROOT

    # Audit path must sit under data/ jail (M16)
    log_path = REPO_ROOT / "data" / "test_soc2_audit_event.jsonl"
    if log_path.is_file():
        log_path.unlink()
    monkeypatch.setenv("SECURITY_AUDIT_LOG_PATH", str(log_path))
    ev = security_event("test.action", outcome="success", actor="tester", role="admin")
    assert ev["action"] == "test.action"
    assert log_path.is_file()
    rows = read_recent(10)
    assert any(r.get("action") == "test.action" for r in rows)
    log_path.unlink(missing_ok=True)


def test_security_headers_on_health(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.delenv("FRONTLINE_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PILOT_HARDENED", raising=False)
    monkeypatch.delenv("SOC2_MODE", raising=False)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in {k.lower() for k in r.headers.keys()}
    # HSTS only when production-like (FIND-R08)
    assert r.headers.get("strict-transport-security") is None
    body = r.json()
    assert "security" in body
    assert body["security"].get("audit_log") is True


def test_hsts_when_production_like(reset_ops_db, monkeypatch):
    monkeypatch.setenv("PILOT_HARDENED", "1")
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", "hsts-test-key-16chars")
    monkeypatch.setenv("SESSION_SECRET", "hsts-session-secret-32bytes!!!!")
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.headers.get("strict-transport-security")


def test_packs_require_key_when_hardened(reset_ops_db, seed_automotive_pack, monkeypatch):
    key = "packs-auth-key-32-characters!!"
    monkeypatch.setenv("FRONTLINE_API_KEY", key)
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SESSION_SECRET", "packs-session-secret-32bytes!!!!")
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    with TestClient(app) as c:
        r = c.get("/api/packs")
        assert r.status_code == 401
        r2 = c.get("/api/packs", headers={"X-API-Key": key})
        assert r2.status_code == 200
        assert "packs" in r2.json()


def test_dsr_emits_audit_when_hardened(reset_ops_db, seed_automotive_pack, monkeypatch, tmp_path):
    from src.config import REPO_ROOT

    key = "soc2-dsr-audit-key-32chars!!!!!"
    monkeypatch.setenv("FRONTLINE_API_KEY", key)
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SESSION_SECRET", "soc2-session-secret-for-dsr!!!!")
    monkeypatch.setenv("FRONTLINE_BOOTSTRAP_ADMIN", "1")
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    log_path = REPO_ROOT / "data" / "test_soc2_dsr_audit.jsonl"
    if log_path.is_file():
        log_path.unlink()
    monkeypatch.setenv("SECURITY_AUDIT_LOG_PATH", str(log_path))
    with TestClient(app) as c:
        mint = c.post(
            "/api/frontline/auth/session",
            headers={"X-API-Key": key},
            json={"subject": "auditor", "role": "admin"},
        )
        assert mint.status_code == 200
        r = c.delete(
            "/api/frontline/dsr/int_audit_test",
            headers={
                "X-API-Key": key,
                "X-Frontline-Session": mint.json()["token"],
            },
        )
    assert r.status_code == 200
    text = log_path.read_text(encoding="utf-8")
    assert "dsr.delete" in text
    log_path.unlink(missing_ok=True)
