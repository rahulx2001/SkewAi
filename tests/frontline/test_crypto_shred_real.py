"""Tests for F-008: real contact crypto-shredding, DEK persistence, and arbitrary plaintext length."""

from __future__ import annotations

import pytest

from src.agents.orchestrator import create_interaction
from src.frontline.dsr import delete_interaction
from src.ids import new_ulid
from src.security.pii import (
    SubjectKeyStore,
    decrypt_subject_pii,
    encrypt_subject_pii,
)


def test_f008_encrypt_text_over_64_bytes(reset_ops_db):
    """F-008: encrypt_subject_pii must support text > 64 bytes without digest_size crash."""
    SubjectKeyStore.clear()
    sub_id = "cust_" + new_ulid()
    long_text = (
        "The driver experienced severe brake failure while driving on the highway at 65 mph. "
        "There was a loud screeching noise followed by complete loss of pedal resistance, "
        "forcing emergency deceleration using the parking brake. Customer phone: 555-0199."
    )
    assert len(long_text.encode("utf-8")) > 64

    # Must not raise ValueError: digest_size must be between 1 and 64
    token = encrypt_subject_pii(sub_id, long_text)
    assert token.startswith("enc:v1:")
    assert long_text not in token

    decrypted = decrypt_subject_pii(sub_id, token)
    assert decrypted == long_text


@pytest.mark.asyncio
async def test_f008_real_interaction_has_dek_on_creation(reset_ops_db, seed_automotive_pack):
    """F-008: Real contacts created via create_interaction must have a DEK initialized."""
    SubjectKeyStore.clear()
    orch, _ = await create_interaction("web_text")
    iid = orch.ctx.interaction_id

    # The interaction must have a registered DEK
    assert SubjectKeyStore.has_dek(iid) is True

    # shred_dek must return True for this real interaction
    assert SubjectKeyStore.shred_dek(iid) is True
    assert SubjectKeyStore.has_dek(iid) is False


def test_f008_dek_persists_across_process_restart(reset_ops_db):
    """F-008: SubjectKeyStore must persist keys in DB so cache drops do not destroy DEKs."""
    SubjectKeyStore.clear()
    sub_id = "cust_persist_" + new_ulid()
    text = "Customer confidential information."
    token = encrypt_subject_pii(sub_id, text)

    # Simulate process restart or secondary replica: wipe in-memory cache only
    SubjectKeyStore._keys.clear()

    # has_dek and decrypt must still work via persisted storage
    assert SubjectKeyStore.has_dek(sub_id) is True
    decrypted = decrypt_subject_pii(sub_id, token)
    assert decrypted == text

    # Now shred from DB
    SubjectKeyStore._keys.clear()
    assert SubjectKeyStore.shred_dek(sub_id) is True
    assert SubjectKeyStore.has_dek(sub_id) is False
    with pytest.raises(KeyError, match="shredded"):
        decrypt_subject_pii(sub_id, token)


@pytest.mark.asyncio
async def test_f008_delete_interaction_crypto_shred_real_contact(reset_ops_db, seed_automotive_pack):
    """F-008: delete_interaction(mode='crypto_shred') reports crypto_shredded=True and destroys DEK."""
    SubjectKeyStore.clear()
    orch, _ = await create_interaction("web_text")
    iid = orch.ctx.interaction_id

    secret_note = "Caller provided secret PIN 1234 and address 123 Main St."
    token = encrypt_subject_pii(iid, secret_note)
    assert decrypt_subject_pii(iid, token) == secret_note

    # Execute DSR crypto_shred on real interaction
    res = delete_interaction(iid, mode="crypto_shred")
    assert res.get("crypto_shredded") is True
    assert res.get("mode") == "crypto_shred"

    # Decrypt must fail
    with pytest.raises(KeyError, match="shredded"):
        decrypt_subject_pii(iid, token)
