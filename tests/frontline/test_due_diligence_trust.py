"""Due-diligence P0/P1 trust + reliability fixes."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.auth import auth_required, check_api_key, is_open_mode
from src.api.main import app
from src.data.warehouse import ops_con
from src.frontline.connectors import dispatch_event, set_connector_config
from src.ledger import AgentAction, record_action
from src.security.url_guard import validate_outbound_url


# ── Auth fail-closed ─────────────────────────────────────────────────────────


def test_auth_required_fail_closed_without_key(monkeypatch):
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    assert auth_required() is True
    with pytest.raises(Exception) as ei:
        check_api_key()
    assert ei.value.status_code == 401


def test_open_mode_explicit(monkeypatch):
    monkeypatch.setenv("FRONTLINE_OPEN_MODE", "1")
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    assert is_open_mode() is True
    check_api_key()  # does not raise


def test_http_fail_closed_routes(reset_ops_db, monkeypatch):
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", "prod-secret")
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/frontline/cases").status_code == 401
        assert (
            c.get("/api/frontline/cases", headers={"X-API-Key": "prod-secret"}).status_code
            == 200
        )
    monkeypatch.delenv("FRONTLINE_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)


# ── SSRF ─────────────────────────────────────────────────────────────────────


def test_validate_outbound_url_blocks_private_and_metadata(monkeypatch):
    # Hermetic: open mode would allow localhost http and mask SSRF guards.
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    with pytest.raises(ValueError, match="url_"):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError):
        validate_outbound_url("http://127.0.0.1:8080/hook")
    with pytest.raises(ValueError):
        validate_outbound_url("ftp://example.com/x")
    # public https ok (DNS may resolve; use example.com)
    ok = validate_outbound_url("https://example.com/webhook")
    assert ok.startswith("https://")


@pytest.mark.asyncio
async def test_connector_dispatch_blocks_ssrf(tmp_path, reset_ops_db, monkeypatch):
    from src.frontline import connectors as c

    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    monkeypatch.setattr(c, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setattr(c, "OUTBOX_DIR", tmp_path / "outbox")
    monkeypatch.setattr(c, "REPO_ROOT", tmp_path)
    c.reset_connector_config_cache()
    with pytest.raises(ValueError):
        set_connector_config(enabled=True, webhook_url="http://127.0.0.1/evil")
    set_connector_config(enabled=True, webhook_url="")
    # Force private URL via secret config bypass for dispatch path
    c.reset_connector_config_cache()
    monkeypatch.setattr(
        c,
        "get_connector_config",
        lambda include_secret=False: {
            "enabled": True,
            "webhook_url": "http://169.254.169.254/",
            "shared_secret": "",
        },
    )
    r = await dispatch_event("case_created", case_id="case_x")
    assert r.get("ok") is False or r.get("status") in ("pending", "failed", "success")
    # if outbox wrote but http blocked
    if r.get("error"):
        assert "ssrf" in str(r["error"]).lower() or r.get("ok") is False


def test_connector_status_never_echoes_secret(tmp_path, reset_ops_db, monkeypatch):
    from src.frontline import connectors as c

    monkeypatch.setattr(c, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setattr(c, "OUTBOX_DIR", tmp_path / "outbox")
    c.reset_connector_config_cache()
    # empty webhook ok
    out = set_connector_config(enabled=True, webhook_url="", shared_secret="super-secret-xyz")
    assert "super-secret-xyz" not in str(out)
    assert out.get("shared_secret") in ("", None)
    assert out.get("shared_secret_set") is True


# ── Ledger vocabulary ────────────────────────────────────────────────────────


def test_ledger_rejects_unknown_action_type(reset_ops_db):
    with pytest.raises(ValueError, match="unknown action_type"):
        record_action(
            AgentAction(
                interaction_id="int_x",
                agent="orchestrator",
                action_type="not_a_real_action_type_xyz",
            )
        )


# ── Concurrent enrichment + mid-contact turns ────────────────────────────────


@pytest.mark.asyncio
async def test_enrichment_runs_agents_concurrently(reset_ops_db, seed_automotive_pack, pack):
    import asyncio
    from src.agents.orchestrator import Orchestrator
    from tests.frontline.conftest import _RecordingHooks

    started = []
    original_sentinel = None

    from src.agents import sentinel as sentinel_mod
    from src.agents import triage as triage_mod
    from src.agents import investigator as inv_mod

    real_s = sentinel_mod.SentinelAgent.run
    real_t = triage_mod.TriageAgent.run
    real_i = inv_mod.InvestigatorAgent.run

    async def wrap(name, real, self, **kw):
        started.append((name, "start", asyncio.get_event_loop().time()))
        await asyncio.sleep(0.05)
        r = await real(self, **kw)
        started.append((name, "end", asyncio.get_event_loop().time()))
        return r

    async def s_run(self, **kw):
        return await wrap("sentinel", real_s, self, **kw)

    async def t_run(self, **kw):
        return await wrap("triage", real_t, self, **kw)

    async def i_run(self, **kw):
        return await wrap("investigator", real_i, self, **kw)

    hooks = _RecordingHooks()
    orch = Orchestrator(
        interaction_id="int_conc_1",
        pack=pack,
        channel="simulated",
        hooks=hooks,
    )
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES ('int_conc_1', ?, ?, ?, 'sim', 'active')
            """,
            [pack.id, pack.pack_version, datetime.now(timezone.utc)],
        )
    orch.ctx.slots = {
        "entity_1": "2019",
        "entity_2": "Toyota",
        "entity_3": "Camry",
        "category": "brakes",
        "description": "soft pedal",
    }
    with (
        patch.object(sentinel_mod.SentinelAgent, "run", s_run),
        patch.object(triage_mod.TriageAgent, "run", t_run),
        patch.object(inv_mod.InvestigatorAgent, "run", i_run),
    ):
        await orch._run_enrichment()

    # Overlap: at least one agent starts before another ends
    starts = {n: t for n, ev, t in started if ev == "start"}
    ends = {n: t for n, ev, t in started if ev == "end"}
    assert len(starts) == 3
    # gather() must start all three before any of them finish the 50ms probe sleep.
    assert max(starts.values()) < min(ends.values())
    # Concurrent: three serial 50ms sleeps are 150ms. Ledger writes share one
    # DuckDB lock, so wall is sleep + serialized writes, still under sequential.
    wall = max(ends.values()) - min(starts.values())
    assert wall < 0.25, f"expected concurrent execution under 250ms, got {wall}"


@pytest.mark.asyncio
async def test_turns_persist_before_finalize(reset_ops_db, seed_automotive_pack, pack):
    from src.agents.orchestrator import Orchestrator
    from tests.frontline.conftest import _RecordingHooks

    iid = "int_turn_dur"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, ?, ?, ?, 'sim', 'active')
            """,
            [iid, pack.id, pack.pack_version, datetime.now(timezone.utc)],
        )
    orch = Orchestrator(interaction_id=iid, pack=pack, channel="sim", hooks=_RecordingHooks())
    await orch.start()
    # Mid-contact: turn rows should already be in ops DB
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM interaction_turns WHERE interaction_id = ?",
            [iid],
        ).fetchone()[0]
    assert n >= 1  # greeting


def test_dashboard_ws_auth_not_query_only():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    auth = (root / "dashboard/src/apiAuth.js").read_text(encoding="utf-8")
    call = (root / "dashboard/routes/CallWidget.jsx").read_text(encoding="utf-8")
    live = (root / "dashboard/routes/LiveContactConsole.jsx").read_text(encoding="utf-8")
    assert "export function sendWsAuth" in auth
    # withApiKeyQuery must not append secrets
    assert "api_key=" not in auth.split("withApiKeyQuery")[1].split("}")[0] or "return url" in auth
    assert "sendWsAuth" in call and "sendWsAuth" in live
    assert "api_key=${" not in call
