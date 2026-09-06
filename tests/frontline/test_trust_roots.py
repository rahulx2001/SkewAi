from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.qubot.locker import (
    _payload_bytes,
    build_locker_bundle,
    sign_locker_bundle,
    verify_locker_bundle,
)
from src.ledger.merkle import (
    anchor_tree_head,
    append_action_leaf,
    verify_head_signature,
)
from src.security.rotation import verify_with_ring


def _generate_keypair() -> tuple[Ed25519PrivateKey, str, bytes]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pem, raw


def test_forged_bundle_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An attacker generates their own keypair and signs a forged bundle with their public key embedded.
    from src.security.trust_roots import TrustRootStore, TrustRoot

    # Set up store with a legitimate root
    store = TrustRootStore(json_path=tmp_path / "trust_roots.json")
    legit_priv, legit_pem, _ = _generate_keypair()
    store.register_root(key_id="legit-root", public_key_pem=legit_pem, created_by="admin")

    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_PATH", str(tmp_path / "trust_roots.json"))
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_KEY_ID", "legit-root")

    attacker_priv, attacker_pem, _ = _generate_keypair()
    forged_bundle: dict[str, Any] = {
        "interaction_id": "int_forged_999",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "public_key_pem": attacker_pem,
        "actions": [],
        "snapshots": [],
        "content_sha256": "",
    }
    sig = attacker_priv.sign(_payload_bytes(forged_bundle))
    forged_bundle["signature"] = sig.hex()

    res = verify_locker_bundle(forged_bundle)
    assert res["ok"] is False
    assert res.get("error") in ("untrusted_signing_key", "signature_verification_failed")


def _content_hash(d: dict[str, Any]) -> str:
    import hashlib
    raw = json.dumps(
        {k: v for k, v in d.items() if k not in ("signature", "public_key_pem", "content_sha256")},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_legitimate_bundle_with_pinned_key_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.security.trust_roots import TrustRootStore

    store = TrustRootStore(json_path=tmp_path / "trust_roots.json")
    legit_priv, legit_pem, _ = _generate_keypair()
    store.register_root(key_id="legit-root", public_key_pem=legit_pem, created_by="admin")

    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_PATH", str(tmp_path / "trust_roots.json"))
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_KEY_ID", "legit-root")

    bundle: dict[str, Any] = {
        "interaction_id": "int_legit_123",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "public_key_pem": legit_pem,
        "actions": [],
        "snapshots": [],
    }
    bundle["content_sha256"] = _content_hash(bundle)
    sig = legit_priv.sign(_payload_bytes(bundle))
    bundle["signature"] = sig.hex()

    res = verify_locker_bundle(bundle)
    assert res["ok"] is True, f"Failed: {res}"


def test_bundle_with_rotated_key_verifies_if_not_revoked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.security.trust_roots import TrustRootStore

    store = TrustRootStore(json_path=tmp_path / "trust_roots.json")
    old_priv, old_pem, _ = _generate_keypair()
    new_priv, new_pem, _ = _generate_keypair()

    store.register_root(key_id="key-old", public_key_pem=old_pem, created_by="admin")
    store.register_root(key_id="key-new", public_key_pem=new_pem, created_by="admin")

    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_PATH", str(tmp_path / "trust_roots.json"))
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_KEY_ID", "key-new")

    # Bundle signed with old key (still valid, not revoked)
    bundle_old: dict[str, Any] = {
        "interaction_id": "int_old_1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "public_key_pem": old_pem,
        "actions": [],
        "snapshots": [],
    }
    bundle_old["content_sha256"] = _content_hash(bundle_old)
    bundle_old["signature"] = old_priv.sign(_payload_bytes(bundle_old)).hex()

    res_old = verify_locker_bundle(bundle_old)
    assert res_old["ok"] is True, f"Old bundle verification failed: {res_old}"

    # Bundle signed with new active key
    bundle_new: dict[str, Any] = {
        "interaction_id": "int_new_2",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "public_key_pem": new_pem,
        "actions": [],
        "snapshots": [],
    }
    bundle_new["content_sha256"] = _content_hash(bundle_new)
    bundle_new["signature"] = new_priv.sign(_payload_bytes(bundle_new)).hex()

    res_new = verify_locker_bundle(bundle_new)
    assert res_new["ok"] is True, f"New bundle verification failed: {res_new}"


def test_bundle_with_revoked_key_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.security.trust_roots import TrustRootStore

    store = TrustRootStore(json_path=tmp_path / "trust_roots.json")
    priv, pem, _ = _generate_keypair()
    store.register_root(key_id="revoked-key", public_key_pem=pem, created_by="admin")
    store.revoke_root("revoked-key")

    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_PATH", str(tmp_path / "trust_roots.json"))
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_KEY_ID", "revoked-key")

    bundle: dict[str, Any] = {
        "interaction_id": "int_revoked_1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "public_key_pem": pem,
        "actions": [],
        "snapshots": [],
    }
    sig = priv.sign(_payload_bytes(bundle))
    bundle["signature"] = sig.hex()

    res = verify_locker_bundle(bundle)
    assert res["ok"] is False


def test_verify_head_signature_rejects_artifact_supplied_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.security.trust_roots import TrustRootStore

    store = TrustRootStore(json_path=tmp_path / "trust_roots.json")
    legit_priv, legit_pem, _ = _generate_keypair()
    attacker_priv, attacker_pem, _ = _generate_keypair()

    store.register_root(key_id="legit-head-key", public_key_pem=legit_pem, created_by="admin")
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_PATH", str(tmp_path / "trust_roots.json"))
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_KEY_ID", "legit-head-key")

    head: dict[str, Any] = {
        "head_id": "head_forged_1",
        "root": "abcd" * 16,
        "leaf_count": 10,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prev_head": "genesis",
        "scope": "global",
        "public_key_pem": attacker_pem,
    }
    from src.ledger.merkle import _head_bytes
    head_bytes = _head_bytes(
        head["head_id"], head["root"], head["leaf_count"],
        head["created_at"], head["prev_head"], head["scope"]
    )
    head["signature"] = attacker_priv.sign(head_bytes).hex()

    res = verify_head_signature(head)
    # Must fail because attacker key is untrusted
    if isinstance(res, dict):
        assert res["ok"] is False
        assert res.get("error") in ("untrusted_signing_key", "signature_verification_failed")
    else:
        assert res is False


def test_no_trust_root_configured_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty_json = tmp_path / "empty_roots.json"
    empty_json.write_text(json.dumps({"keys": []}))
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_PATH", str(empty_json))
    monkeypatch.delenv("FRONTLINE_TRUST_ROOT_KEY_ID", raising=False)

    bundle: dict[str, Any] = {
        "interaction_id": "int_test_none",
        "signature": "1234",
    }
    res = verify_locker_bundle(bundle)
    assert res["ok"] is False
    assert res.get("error") == "no_trust_root_configured"


def test_verify_with_ring_is_called_in_production_path() -> None:
    import inspect
    from src.qubot.locker import verify_locker_bundle
    from src.ledger.merkle import verify_head_signature

    # Statically assert verify_with_ring is referenced in verify_locker_bundle or verify_head_signature
    src_locker = inspect.getsource(verify_locker_bundle)
    src_merkle = inspect.getsource(verify_head_signature)
    assert "verify_with_ring" in src_locker or "verify_with_ring" in src_merkle


def test_startup_refuses_when_trust_root_required_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.security.harden import validate_startup_security

    empty_json = tmp_path / "empty_roots.json"
    empty_json.write_text(json.dumps({"keys": []}))
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_PATH", str(empty_json))
    monkeypatch.delenv("FRONTLINE_TRUST_ROOT_KEY_ID", raising=False)
    monkeypatch.setenv("FRONTLINE_TRUST_ROOT_REQUIRED", "1")

    with pytest.raises(RuntimeError, match="no trust root configured"):
        validate_startup_security()
