import pytest
from src.data.warehouse import ops_con
from src.ledger.chain import verify_chain, GENESIS
from src.ledger import AgentAction, record_action
from src.security.pii import SubjectKeyStore, encrypt_subject_pii, decrypt_subject_pii
from src.frontline.dsr import delete_interaction, tombstone_interaction, export_interaction
from src.ids import new_ulid

pytestmark = pytest.mark.asyncio

from src.ledger.writer import list_actions

async def test_tombstone_preserves_hash_chain(reset_ops_db):
    iid = "int_" + new_ulid()
    # Create an interaction
    with ops_con() as con:
        con.execute("INSERT INTO interactions (interaction_id, pack_id, pack_version, started_at, channel, status, description, category, entity_1, entity_2, entity_3) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [iid, "p1", "v1", "2023-01-01", "web", "open", "desc", "cat", "e1", "e2", "e3"])
        con.execute("INSERT INTO interaction_turns (turn_id, interaction_id, seq, speaker, text, ts) VALUES (?, ?, ?, ?, ?, ?)", [new_ulid(), iid, 1, "customer", "turn1", "2023-01-01"])

    for i in range(5):
        record_action(AgentAction(interaction_id=iid, agent="orchestrator", action_type="state_transition", input_summary=f"in{i}", output_summary=f"out{i}"))
    
    actions_before = list_actions(iid)
    assert verify_chain(actions_before)["ok"] is True

    tombstone_interaction(iid)

    with ops_con() as con:
        actions = con.execute("SELECT input_summary, output_summary, erased FROM agent_actions WHERE interaction_id = ? ORDER BY ts ASC", [iid]).fetchall()
        for a in actions:
            assert a[2] is True or a[2] == 1
            assert "ERASED" in (a[0] or "")
            assert "ERASED" in (a[1] or "")

    actions_after = list_actions(iid)
    assert verify_chain(actions_after)["ok"] is True

async def test_erase_then_export_returns_empty(reset_ops_db):
    iid = new_ulid()
    with ops_con() as con:
        con.execute("INSERT INTO interactions (interaction_id, pack_id, pack_version, started_at, channel, status) VALUES (?, ?, ?, ?, ?, ?)", [iid, "p1", "v1", "2023-01-01", "web", "open"])
        con.execute("INSERT INTO interaction_turns (turn_id, interaction_id, seq, speaker, text, ts) VALUES (?, ?, ?, ?, ?, ?)", [new_ulid(), iid, 1, "customer", "turn1", "2023-01-01"])
    
    exp1 = export_interaction(iid)
    assert len(exp1["turns"]) > 0

    delete_interaction(iid, mode="erase")
    
    exp2 = export_interaction(iid)
    assert not exp2 or len(exp2.get("turns", [])) == 0

async def test_crypto_shred_then_decrypt_fails(reset_ops_db):
    iid = new_ulid()
    enc = encrypt_subject_pii(iid, 'sensitive data')
    assert decrypt_subject_pii(iid, enc) == 'sensitive data'
    
    delete_interaction(iid, mode="crypto_shred")
    
    with pytest.raises(KeyError):
        decrypt_subject_pii(iid, enc)
    
    store = SubjectKeyStore()
    assert store.has_dek(iid) is False

async def test_tombstone_clears_slot_copies(reset_ops_db):
    iid = new_ulid()
    with ops_con() as con:
        con.execute("INSERT INTO interactions (interaction_id, pack_id, pack_version, started_at, channel, status, description, category, entity_1, entity_2, entity_3) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [iid, "p1", "v1", "2023-01-01", "web", "open", "desc", "cat", "e1", "e2", "e3"])
    
    tombstone_interaction(iid)
    
    with ops_con() as con:
        row = con.execute("SELECT entity_1, entity_2, entity_3, description, category FROM interactions WHERE interaction_id = ?", [iid]).fetchone()
        assert all(x is None for x in row)

async def test_evidence_snapshots_erased_preserves_hash(reset_ops_db):
    iid = new_ulid()
    with ops_con() as con:
        from src.qubot.evidence_pin import _ensure_pin_table
        _ensure_pin_table(con)
        con.execute("INSERT INTO cited_evidence_snapshots (snapshot_id, action_id, interaction_id, pack_id, evidence_id, body_json, body_hash, pinned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [new_ulid(), new_ulid(), iid, "p1", new_ulid(), '{"a": 1}', "hash", "2023-01-01"])
    
    tombstone_interaction(iid)
    
    with ops_con() as con:
        row = con.execute("SELECT body_json, erased FROM cited_evidence_snapshots WHERE interaction_id = ?", [iid]).fetchone()
        import json
        assert json.loads(row[0]).get("erased") is True
        assert row[1] == 1

async def test_multiple_subjects_shred_isolation(reset_ops_db):
    iid1 = new_ulid()
    iid2 = new_ulid()
    
    enc1 = encrypt_subject_pii(iid1, 'data1')
    enc2 = encrypt_subject_pii(iid2, 'data2')
    
    delete_interaction(iid1, mode="crypto_shred")
    
    assert decrypt_subject_pii(iid2, enc2) == 'data2'
    with pytest.raises(KeyError):
        decrypt_subject_pii(iid1, enc1)
