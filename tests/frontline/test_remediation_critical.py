"""Remediation regression tests — CRITICAL items 1-10.

Each test pins the corrected behavior (and the vulnerable behavior it
replaces). These run against the real app/DB stack, not re-implementations.
"""

from __future__ import annotations

import pytest


# ── ITEM 1: fail-closed open mode ────────────────────────────────────────────


STRONG_KEY = "item1-test-key-32-bytes-long!!!!!!"


def _clear_security_env(monkeypatch):
    for var in (
        "ENV", "APP_ENV", "PILOT_HARDENED", "SOC2_MODE", "FRONTLINE_OPEN_MODE",
        "FRONTLINE_AUTH_REQUIRED", "FRONTLINE_API_KEY", "SESSION_SECRET",
        "API_HOST", "FRONTLINE_OPEN_BIND_ACK",
    ):
        monkeypatch.delenv(var, raising=False)


def test_item1_wildcard_bind_without_auth_refuses_startup(monkeypatch):
    from src.security.harden import validate_startup_security

    _clear_security_env(monkeypatch)
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    with pytest.raises(RuntimeError, match="beyond loopback"):
        validate_startup_security()


def test_item1_wildcard_bind_missing_key_refuses_startup(monkeypatch):
    from src.security.harden import validate_startup_security

    _clear_security_env(monkeypatch)
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="beyond loopback"):
        validate_startup_security()


def test_item1_wildcard_bind_short_key_refuses_startup(monkeypatch):
    from src.security.harden import validate_startup_security

    _clear_security_env(monkeypatch)
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", "short-key")
    with pytest.raises(RuntimeError, match="beyond loopback"):
        validate_startup_security()


def test_item1_valid_production_config_starts(monkeypatch):
    from src.security.harden import validate_startup_security

    _clear_security_env(monkeypatch)
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", STRONG_KEY)
    monkeypatch.setenv("SESSION_SECRET", STRONG_KEY + "-session!!")
    status = validate_startup_security()
    assert status["ok"] is True
    assert status["wildcard_bind"] is True


def test_item1_loopback_open_mode_is_explicit_dev_hatch(monkeypatch):
    from src.security.harden import validate_startup_security

    _clear_security_env(monkeypatch)
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    status = validate_startup_security()
    assert status["ok"] is True
    assert status["open_mode"] is True


def test_item1_placeholder_key_rejected_when_hardened(monkeypatch):
    from src.security.harden import validate_startup_security

    _clear_security_env(monkeypatch)
    monkeypatch.setenv("PILOT_HARDENED", "1")
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", "dev-only")
    with pytest.raises(RuntimeError, match="placeholder|32 bytes"):
        validate_startup_security()


def test_item1_protected_route_rejects_and_accepts(reset_ops_db, seed_automotive_pack, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("FRONTLINE_API_KEY", "route-test-key")
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    with TestClient(app) as c:
        assert c.post("/api/interactions/start").status_code == 401
        ok = c.post(
            "/api/interactions/start", headers={"X-API-Key": "route-test-key"}
        )
        assert ok.status_code == 200


# ── ITEM 2: backtest entity-overlap gate ─────────────────────────────────────


def _make_backtest_pack(tmp_path, monkeypatch, pack_id="bt_gate_pack"):
    """Minimal warehouse: one HONDA cluster, one mismatched + one matched advisory."""
    from datetime import datetime, timedelta

    from src.data.warehouse import apply_domain_schema, domain_con

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    now = datetime(2025, 1, 15)
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        con.execute(
            """INSERT INTO records (record_id, occurred_at, received_at, entity_1,
               entity_2, entity_3, category, text, source)
               VALUES ('NHTSA-900001', ?, ?, '2019', 'HONDA', 'CR-V',
                       'SERVICE BRAKES', 'grinding brakes', 'NHTSA')""",
            [now - timedelta(days=100), now - timedelta(days=100)],
        )
        con.execute(
            """INSERT INTO clusters (cluster_id, pack_id, top_terms, category,
               record_count, first_seen, last_seen)
               VALUES (1000, ?, '["grinding"]', 'SERVICE BRAKES', 1, ?, ?)""",
            [pack_id, now - timedelta(days=100), now - timedelta(days=90)],
        )
        con.execute(
            "INSERT INTO cluster_assignments (record_id, cluster_id, distance)"
            " VALUES ('NHTSA-900001', 1000, 0.2)"
        )
        # Same category, DIFFERENT entity (FORD) — must not match.
        con.execute(
            """INSERT INTO advisories (advisory_id, issued_at, scope_entity_2,
               scope_entity_3, scope_category, summary)
               VALUES ('25V-00001', ?, 'FORD', 'F-150', 'SERVICE BRAKES', 'ford brakes')""",
            [now - timedelta(days=10)],
        )
        # Same category, OVERLAPPING entity (HONDA/CR-V) — potential match.
        con.execute(
            """INSERT INTO advisories (advisory_id, issued_at, scope_entity_2,
               scope_entity_3, scope_category, summary)
               VALUES ('25V-00002', ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', 'honda brakes')""",
            [now - timedelta(days=10)],
        )
        # Advisory BEFORE the signal — missed signal, must be matched=False.
        con.execute(
            """INSERT INTO advisories (advisory_id, issued_at, scope_entity_2,
               scope_entity_3, scope_category, summary)
               VALUES ('25V-00003', ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', 'early')""",
            [now - timedelta(days=200)],
        )
    return pack_id


def test_item2_same_category_different_entity_no_match(tmp_path, monkeypatch):
    from src.backtest.engine import run_backtest

    pack = _make_backtest_pack(tmp_path, monkeypatch)
    rows = run_backtest(pack)
    by_adv = {r["advisory_id"]: r for r in rows}
    assert by_adv["25V-00001"]["matched"] is False
    assert by_adv["25V-00001"]["match_basis"] == "entity-mismatch"


def test_item2_same_category_overlapping_entity_potential_match(tmp_path, monkeypatch):
    from src.backtest.engine import run_backtest

    pack = _make_backtest_pack(tmp_path, monkeypatch)
    rows = run_backtest(pack)
    by_adv = {r["advisory_id"]: r for r in rows}
    assert by_adv["25V-00002"]["matched"] is True
    assert by_adv["25V-00002"]["lead_time_weeks"] > 0
    assert "entity_2" in (by_adv["25V-00002"]["match_basis"] or "")


def test_item2_missed_signal_matched_false(tmp_path, monkeypatch):
    from src.backtest.engine import run_backtest

    pack = _make_backtest_pack(tmp_path, monkeypatch)
    rows = run_backtest(pack)
    by_adv = {r["advisory_id"]: r for r in rows}
    assert by_adv["25V-00003"]["matched"] is False
    assert by_adv["25V-00003"]["lead_time_weeks"] == 0


def test_item2_synthetic_fixture_distinguishable(seed_automotive_pack):
    from src.data.warehouse import domain_con

    with domain_con("automotive_nhtsa") as con:
        rows = con.execute(
            "SELECT provenance FROM backtest_results WHERE cluster_id = 14"
        ).fetchall()
    assert rows, "seed fixture must still pin cluster 14 (eval compat)"
    assert all(r[0] == "fixture" for r in rows)
    from src.backtest.engine import run_backtest

    run_backtest("automotive_nhtsa")
    with domain_con("automotive_nhtsa") as con:
        rows2 = con.execute(
            "SELECT DISTINCT provenance FROM backtest_results WHERE cluster_id = 14"
        ).fetchall()
    assert rows2 == [("computed",)], "recompute must replace fixture fiction"


# ── ITEM 3: auditor as_of snapshots ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_item3_historical_audit_reproducible_after_db_change(
    orchestrator_factory,
):
    """Later DB edits must not rewrite a historical audit verdict."""
    from src.data.warehouse import domain_con, ops_con
    from src.ledger import AgentAction, record_action
    from src.ledger.writer import remember_interaction_pack
    from src.qubot.auditor import audit_interaction

    orch, _ = orchestrator_factory()
    iid = orch.ctx.interaction_id
    remember_interaction_pack(iid, "automotive_nhtsa")
    record_action(AgentAction(
        interaction_id=iid, agent="investigator", action_type="similar_search",
        input_summary="probe", output_summary="probe",
        evidence_ids=["NHTSA-100001", "19V-12345", "14"],
    ))
    entities_note = "customer: 2019 HONDA CR-V SERVICE BRAKES"
    with ops_con() as con:
        con.execute(
            "UPDATE interactions SET entity_1='2019', entity_2='HONDA',"
            " entity_3='CR-V', category='SERVICE BRAKES' WHERE interaction_id = ?",
            [iid],
        )
    first = await audit_interaction(iid, write_report=False)
    by_action = {v.action_id: v for v in first.action_verdicts}
    target = next(v for v in first.action_verdicts if v.evidence_checked)
    assert target.verdict == "grounded", f"setup must be grounded first: {target}"
    assert target.evidence_confirmed_snapshot == 3
    as_of = first.as_of
    assert as_of, "audit must stamp as_of"

    # Mutate the live warehouse AFTER the audit: rename the cited record's
    # category AND delete the cited advisory — live checks would now mismatch.
    with domain_con("automotive_nhtsa", read_only=False) as con:
        con.execute(
            "UPDATE records SET category = 'ELECTRICAL SYSTEM' WHERE record_id = 'NHTSA-100001'"
        )
        con.execute("DELETE FROM advisories WHERE advisory_id = '19V-12345'")
    try:
        second = await audit_interaction(iid, write_report=False, as_of=as_of)
        assert second.as_of == as_of
        again = next(
            v for v in second.action_verdicts if v.action_id == target.action_id
        )
        # Historical verdict reproduces from the snapshot even though live
        # state drifted (drift is flagged separately, not as a rewrite).
        assert again.verdict in ("grounded", "source-drifted"), (
            f"historical verdict changed after DB edit: "
            f"{target.verdict} -> {again.verdict}"
        )
        assert again.source_drifted_ids, "live-vs-pin drift must be reported"
    finally:
        # Restore the exact advisory row removed above.
        from scripts.seed_domains import _ADVISORIES

        with domain_con("automotive_nhtsa", read_only=False) as con:
            con.execute(
                "UPDATE records SET category = 'SERVICE BRAKES'"
                " WHERE record_id = 'NHTSA-100001'"
            )
            exists = con.execute(
                "SELECT 1 FROM advisories WHERE advisory_id = '19V-12345'"
            ).fetchone()
            if not exists:
                a = next(x for x in _ADVISORIES if x["advisory_id"] == "19V-12345")
                con.execute(
                    """INSERT INTO advisories (advisory_id, issued_at, scope_entity_1,
                       scope_entity_2, scope_entity_3, scope_category, summary,
                       remedy, url, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [a["advisory_id"], a["issued_at"], a["scope_entity_1"],
                     a["scope_entity_2"], a["scope_entity_3"], a["scope_category"],
                     a["summary"], a["remedy"], a["url"], a["source"]],
                )


def test_item3_snapshot_used_over_live(reset_ops_db, seed_automotive_pack, pack):
    """Pinned snapshots take precedence; provenance is labeled snapshot:."""
    from src.data.warehouse import ops_con
    from src.ledger import AgentAction, record_action
    from src.ledger.writer import remember_interaction_pack
    from src.qubot.auditor import _audit_single_action

    iid = "int_snapshot_probe"
    with ops_con() as con:
        con.execute(
            """INSERT INTO interactions (interaction_id, pack_id, pack_version,
               started_at, channel, status) VALUES (?, 'automotive_nhtsa', '1',
               CURRENT_TIMESTAMP, 'web_text', 'active')""",
            [iid],
        )
    remember_interaction_pack(iid, "automotive_nhtsa")
    record_action(AgentAction(
        interaction_id=iid, agent="investigator", action_type="similar_search",
        input_summary="probe", output_summary="probe",
        evidence_ids=["NHTSA-100001"],
    ))
    entities = {"entity_1": "2019", "entity_2": "HONDA", "entity_3": "CR-V",
                "category": "SERVICE BRAKES"}
    with ops_con(read_only=True) as con:
        action = con.execute(
            "SELECT * FROM agent_actions WHERE interaction_id = ?", [iid]
        ).fetchone()
        cols = [d[0] for d in con.description]
    verdict = _audit_single_action("automotive_nhtsa", dict(zip(cols, action)), entities)
    assert verdict.evidence_confirmed_snapshot == 1
    assert verdict.evidence_confirmed_live == 0


# ── ITEM 4: cluster identity ─────────────────────────────────────────────────


def test_item4_rebuild_mints_unique_ids_and_versions(tmp_path, monkeypatch):
    from datetime import datetime

    from src.data.warehouse import apply_domain_schema, domain_con
    from src.ml_runtime.clustering import rebuild_clusters, resolve_cluster_version

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack = "clu_identity_pack"
    with domain_con(pack, read_only=False) as con:
        apply_domain_schema(con)
        for i in range(4):
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at,
                   entity_2, category, text, source)
                   VALUES (?, ?, ?, 'HONDA', 'SERVICE BRAKES', ?, 'NHTSA')""",
                [f"CLU-{i}", datetime(2024, 1, 1), datetime(2024, 1, 2),
                 f"brake grinding noise variant {i}"],
            )
    first = rebuild_clusters(pack, k=2)
    second = rebuild_clusters(pack, k=2)
    assert set(first["cluster_uids"]) == set(second["cluster_uids"])
    # UIDs are never reused across rebuilds…
    assert set(first["cluster_uids"].values()).isdisjoint(
        set(second["cluster_uids"].values())
    )
    for uid in second["cluster_uids"].values():
        assert uid.startswith("clu_")
    # …legacy ids are explicit, never silent…
    assert second["legacy_ids_reused"], "expected explicit legacy-id reuse notice"
    # …and history versions increment.
    v = resolve_cluster_version(pack, 1000)
    assert v is not None and v["version"] >= 2
    assert v["supersedes_uid"], "version chain must link to the prior uid"


def test_item4_historical_case_resolves_original_version(tmp_path, monkeypatch):
    from datetime import datetime

    from src.data.warehouse import apply_domain_schema, domain_con
    from src.ml_runtime.clustering import rebuild_clusters, resolve_cluster_version

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    pack = "clu_history_pack"
    with domain_con(pack, read_only=False) as con:
        apply_domain_schema(con)
        for i in range(3):
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at,
                   entity_2, category, text, source)
                   VALUES (?, ?, ?, 'FORD', 'AIR BAGS', ?, 'NHTSA')""",
                [f"HIST-{i}", datetime(2024, 2, 1), datetime(2024, 2, 2),
                 f"airbag light issue number {i}"],
            )
    r1 = rebuild_clusters(pack, k=1)
    uid_v1 = r1["cluster_uids"][1000]
    with domain_con(pack, read_only=False) as con:
        v1_at = con.execute(
            "SELECT created_at FROM cluster_versions WHERE cluster_uid = ?",
            [uid_v1],
        ).fetchone()[0]
    r2 = rebuild_clusters(pack, k=1)
    assert r2["cluster_uids"][1000] != uid_v1
    historical = resolve_cluster_version(pack, 1000, as_of=v1_at)
    assert historical is not None
    assert historical["cluster_uid"] == uid_v1
    assert historical["version"] == 1


def test_item4_legacy_id_warns():
    from src.ml_runtime.clustering import warn_on_legacy_cluster_id

    with pytest.warns(DeprecationWarning, match="rebuild-local"):
        warn_on_legacy_cluster_id(1000)


# ── ITEM 5: real cluster distance ────────────────────────────────────────────


def test_item5_cosine_distance_known_vectors():
    from src.ml_runtime.clustering import (
        DISTANCE_IDENTICAL,
        DISTANCE_OPPOSITE,
        DISTANCE_ORTHOGONAL,
    )
    from src.ml_runtime.embeddings import cosine

    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert 1.0 - cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(DISTANCE_IDENTICAL)
    assert 1.0 - cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(DISTANCE_ORTHOGONAL)
    assert 1.0 - cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(DISTANCE_OPPOSITE)
    # Zero vectors are maximally dissimilar, never false-identical.
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_item5_rebuild_distances_are_real(seed_automotive_pack):
    from src.data.warehouse import domain_con
    from src.ml_runtime.clustering import rebuild_clusters

    rebuild_clusters("automotive_nhtsa", k=3)
    with domain_con("automotive_nhtsa") as con:
        dists = [r[0] for r in con.execute("SELECT distance FROM cluster_assignments").fetchall()]
    assert dists, "expected assignments"
    assert len(set(dists)) > 1, "distances must vary per row (not a constant)"
    assert all(0.0 <= d <= 2.0 for d in dists)


# ── ITEM 6: supervised safety turns ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_item6_emergency_during_takeover_processed(orchestrator_factory):
    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    n_customer_turns = len(hooks.turns)
    await orch.handle_customer_turn("I'M BLEEDING from the crash!")
    # No customer-facing generation…
    assert len(hooks.turns) == n_customer_turns
    # …but safety was fully processed.
    assert orch.ctx.state == "SUPERVISED"
    assert orch.ctx.severity == "Critical"
    assert orch.ctx.priority == 1
    assert orch.ctx.safety_flags.get("escalation") is True
    # …and ledgered + surfaced to the console.
    from src.ledger import list_actions

    types = [a["action_type"] for a in list_actions(orch.ctx.interaction_id)]
    assert "supervised_safety_raised" in types
    assert any(
        a.get("action_type") == "escalated" for a in hooks.activities
    ), "console must see the safety hit"


@pytest.mark.asyncio
async def test_item6_normal_supervised_turn_ledgered_no_generation(orchestrator_factory):
    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    n_turns = len(hooks.turns)
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    assert len(hooks.turns) == n_turns
    assert orch.ctx.state == "SUPERVISED"
    from src.ledger import list_actions

    types = [a["action_type"] for a in list_actions(orch.ctx.interaction_id)]
    assert "supervised_turn_observed" in types
    # Customer turn + sentiment scoring still recorded.
    assert any(t["speaker"] == "customer" for t in orch.ctx.turns)


# ── ITEM 7: hangup idempotency ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_item7_repeated_hangup_single_case(orchestrator_factory):
    from src.data.warehouse import ops_con

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    await orch.handle_customer_turn("It happens every morning, please help.")
    # Drive to close (slots complete -> enriching -> closing creates the case).
    for _ in range(14):
        if orch.ctx.state == "DONE":
            break
        await orch.handle_customer_turn("Additional detail for the record.")
    if orch.ctx.state != "DONE":
        await orch._move_to_closing()
    first_case = orch.ctx.case_id
    assert first_case, "first close must create a case"
    with ops_con(read_only=True) as con:
        n1 = con.execute(
            "SELECT COUNT(*) FROM cases WHERE interaction_id = ?",
            [orch.ctx.interaction_id],
        ).fetchone()[0]
    assert n1 == 1
    # Repeated hangup / close events must not create another case.
    await orch.hangup()
    await orch._move_to_closing()
    await orch.hangup()
    assert orch.ctx.case_id == first_case
    with ops_con(read_only=True) as con:
        n2 = con.execute(
            "SELECT COUNT(*) FROM cases WHERE interaction_id = ?",
            [orch.ctx.interaction_id],
        ).fetchone()[0]
    assert n2 == 1
    assert orch.ctx.state == "DONE"


# ── ITEM 8: enrichment isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_item8_single_enrichment_failure_does_not_strand(orchestrator_factory):
    from src.agents import orchestrator as orch_mod

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")

    async def _boom(**kwargs):
        raise RuntimeError("ml backend down")

    orig_inv = orch_mod.InvestigatorAgent
    try:
        class _FailingInv(orig_inv):
            async def run(self, **kwargs):
                raise RuntimeError("ml backend down")

        orch_mod.InvestigatorAgent = _FailingInv
        await orch._enter_enriching()
    finally:
        orch_mod.InvestigatorAgent = orig_inv
    # Contact reaches DONE with partial results — never stranded in ENRICHING.
    assert orch.ctx.state == "DONE"
    assert orch.ctx.case_id, "case must still be created from partial enrichment"
    assert orch.ctx.severity, "triage partial result must survive investigator failure"
    from src.ledger import list_actions

    failed = [
        a for a in list_actions(orch.ctx.interaction_id)
        if a["agent"] == "investigator" and not a["ok"]
    ]
    assert failed, "investigator failure must be ledgered, not swallowed"


@pytest.mark.asyncio
async def test_item8_all_enrichment_failures_still_close(orchestrator_factory):
    from src.agents import orchestrator as orch_mod

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    orig_s, orig_t, orig_i = (
        orch_mod.SentinelAgent, orch_mod.TriageAgent, orch_mod.InvestigatorAgent,
    )
    try:
        class _Fail(orig_s):
            async def run(self, **kwargs):
                raise ConnectionError("db down")

        class _Fail2(orig_t):
            async def run(self, **kwargs):
                raise ConnectionError("db down")

        class _Fail3(orig_i):
            async def run(self, **kwargs):
                raise ConnectionError("db down")

        orch_mod.SentinelAgent = _Fail
        orch_mod.TriageAgent = _Fail2
        orch_mod.InvestigatorAgent = _Fail3
        await orch._enter_enriching()
    finally:
        (orch_mod.SentinelAgent, orch_mod.TriageAgent,
         orch_mod.InvestigatorAgent) = (orig_s, orig_t, orig_i)
    assert orch.ctx.state == "DONE"
    assert orch.ctx.case_id


# ── ITEM 9: anchored merkle verification ─────────────────────────────────────


def test_item9_anchor_detects_leaf_deletion(reset_ops_db):
    from src.ledger.merkle import (
        anchor_tree_head,
        append_action_leaf,
        verify_against_anchor,
        verify_completeness,
    )

    append_action_leaf("int_anchor_1", "act_1", "hash-1")
    append_action_leaf("int_anchor_1", "act_2", "hash-2")
    anchor = anchor_tree_head(signer="test")
    assert verify_against_anchor(anchor)["ok"] is True
    # Attacker deletes a leaf (and its action) after anchoring.
    from src.data.warehouse import ops_con

    with ops_con() as con:
        con.execute("DELETE FROM global_log_leaves WHERE action_id = 'act_2'")
    after = verify_against_anchor(anchor)
    assert after["ok"] is False, "deletion after anchoring must fail verification"
    # Unanchored self-check must not claim tamper-evidence.
    plain = verify_completeness()
    assert plain["anchored"] is False
    assert plain["warning"], "must warn that unanchored check is self-consistency only"


def test_item9_anchor_detects_modification_and_reorder(reset_ops_db):
    from src.data.warehouse import ops_con
    from src.ledger.merkle import (
        anchor_tree_head,
        append_action_leaf,
        verify_against_anchor,
        verify_head_chain,
        verify_head_signature,
    )

    append_action_leaf("int_anchor_2", "act_1", "hash-a")
    anchor = anchor_tree_head(signer="test")
    assert verify_head_signature(anchor)["ok"] is True
    assert verify_head_chain()["ok"] is True
    with ops_con() as con:
        con.execute(
            "UPDATE global_log_leaves SET leaf = 'tampered' WHERE action_id = 'act_1'"
        )
    assert verify_against_anchor(anchor)["ok"] is False
    # Tampered anchor metadata must fail signature verification.
    bad = dict(anchor)
    bad["leaf_count"] = int(anchor["leaf_count"]) + 5
    assert verify_against_anchor(bad)["ok"] is False


def test_item9_locker_bundle_tamper_fails_offline(reset_ops_db, seed_automotive_pack, pack):
    import copy

    from src.qubot.locker import build_locker_bundle, sign_locker_bundle, verify_locker_bundle

    orch_iid = "int_locker_probe"
    from src.data.warehouse import ops_con
    from src.ledger import AgentAction, record_action

    with ops_con() as con:
        con.execute(
            """INSERT INTO interactions (interaction_id, pack_id, pack_version,
               started_at, channel, status) VALUES (?, 'automotive_nhtsa', '1',
               CURRENT_TIMESTAMP, 'web_text', 'completed')""",
            [orch_iid],
        )
    record_action(AgentAction(
        interaction_id=orch_iid, agent="orchestrator",
        action_type="interaction_started", output_summary="created",
    ))
    bundle = sign_locker_bundle(build_locker_bundle(orch_iid))
    assert verify_locker_bundle(bundle)["ok"] is True
    assert "anchor_head" in (bundle.get("merkle_proof") or {}), (
        "bundle must carry the external anchor root"
    )
    tampered = copy.deepcopy(bundle)
    if (tampered.get("merkle_proof") or {}).get("leaves"):
        tampered["merkle_proof"]["leaves"] = tampered["merkle_proof"]["leaves"][:-1]
        # Re-sign so the failure is attributed to the anchor, not the signature.
        tampered = sign_locker_bundle(
            {k: v for k, v in tampered.items() if k not in ("signature", "public_key_pem")}
        )
        assert verify_locker_bundle(tampered)["ok"] is False


# ── ITEM 10: anomaly statistics ──────────────────────────────────────────────


def test_item10_trivial_lift_not_flagged():
    from src.ml_runtime.anomalies import score_weekly_slices

    counts = {
        (f"2024-W{w:02d}", "CAT", "ENT"): 1000 + (w % 2)
        for w in range(10, 16)
    }
    counts[("2024-W15", "CAT", "ENT")] = 1002
    rows = score_weekly_slices(counts, pack_id="p")
    spike = next(r for r in rows if r["iso_week"] == "2024-W15")
    assert spike["is_anomaly"] is False, "1000 -> 1002 must not flag"


def test_item10_genuine_spike_detected_with_fdr():
    from src.ml_runtime.anomalies import score_weekly_slices

    counts = {}
    for w in range(10, 15):
        counts[(f"2024-W{w:02d}", "CAT", "ENT")] = 2
    counts[("2024-W15", "CAT", "ENT")] = 20
    rows = score_weekly_slices(counts, pack_id="p")
    spike = next(r for r in rows if r["iso_week"] == "2024-W15")
    assert spike["is_anomaly"] is True
    assert spike["z_score"] >= 2.0
    assert spike["p_bh"] <= 0.05
    assert spike["method"] == "quasi-poisson"


def test_item10_zero_baseline_and_missing_weeks():
    from src.ml_runtime.anomalies import score_weekly_slices

    # Sparse series with a gap (W12 missing -> zero-filled) then a real spike.
    counts = {
        ("2024-W10", "CAT", "ENT"): 0,
        ("2024-W11", "CAT", "ENT"): 0,
        ("2024-W13", "CAT", "ENT"): 0,
        ("2024-W14", "CAT", "ENT"): 0,
        ("2024-W15", "CAT", "ENT"): 9,
    }
    rows = score_weekly_slices(counts, pack_id="p")
    by_week = {r["iso_week"]: r for r in rows}
    assert "2024-W12" in by_week, "missing weeks must be zero-filled"
    assert by_week["2024-W12"]["record_count"] == 0
    spike = by_week["2024-W15"]
    assert spike["is_anomaly"] is True, "9 vs zero baseline must flag"
    assert spike["method"] == "zero-baseline"
    # A lone report on a zero baseline must not page.
    counts2 = {
        ("2024-W10", "CAT", "ENT"): 0,
        ("2024-W11", "CAT", "ENT"): 0,
        ("2024-W13", "CAT", "ENT"): 0,
        ("2024-W14", "CAT", "ENT"): 0,
        ("2024-W15", "CAT", "ENT"): 1,
    }
    rows2 = score_weekly_slices(counts2, pack_id="p")
    assert next(r for r in rows2 if r["iso_week"] == "2024-W15")["is_anomaly"] is False


def test_item10_fdr_across_categories_and_event_clock():
    from datetime import datetime

    from src.ml_runtime.anomalies import count_weekly_slices, score_weekly_slices

    # occurred_at (event clock) differs from received_at (ingestion).
    recs = [
        {"occurred_at": datetime(2024, 3, 4), "received_at": datetime(2024, 5, 1),
         "category": "CAT", "entity_2": "ENT"},
    ]
    counts = count_weekly_slices(recs)
    assert ("2024-W10", "CAT", "ENT") in counts, (
        "event clock must be occurred_at, not ingestion time"
    )
    # Many flat categories + one spike: FDR must keep the spike flagged
    # without flagging the flat ones.
    big: dict = {}
    for c in range(20):
        for w in range(10, 15):
            big[(f"2024-W{w:02d}", f"CAT{c}", "ENT")] = 3
    for w in range(10, 15):
        big[(f"2024-W{w:02d}", "SPIKE", "ENT")] = 3
    big[("2024-W15", "SPIKE", "ENT")] = 30
    rows = score_weekly_slices(big, pack_id="p")
    spike = next(r for r in rows if r["category"] == "SPIKE" and r["iso_week"] == "2024-W15")
    assert spike["is_anomaly"] is True
    flat_flags = [r for r in rows if r["category"] != "SPIKE" and r["is_anomaly"]]
    assert flat_flags == [], f"FDR must suppress flat-category flags: {flat_flags[:3]}"
