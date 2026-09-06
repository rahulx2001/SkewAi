"""Evidence Locker: Ed25519-signed JSON bundle + standalone verifier.

No PDF. A regulator re-runs ``python -m src.qubot.locker verify bundle.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from src.config import REPO_ROOT
from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.qubot.evidence_pin import snapshots_for_action

DEFAULT_KEY_DIR = REPO_ROOT / "data" / "locker_keys"


def locker_dir() -> Path:
    """Evidence-locker output dir. ``QUBOT_LOCKER_DIR`` isolates pytest from git."""
    import os

    raw = (os.getenv("QUBOT_LOCKER_DIR") or "").strip()
    if not raw:
        return REPO_ROOT / "reports" / "qubot" / "lockers"
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()


def _payload_bytes(bundle: dict[str, Any]) -> bytes:
    payload = {k: v for k, v in bundle.items() if k not in ("signature", "public_key_pem")}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def generate_keypair(dir_path: Path | None = None) -> tuple[Path, Path]:
    import os as _os

    d = dir_path or DEFAULT_KEY_DIR
    d.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    priv_path = d / "locker_ed25519.pem"
    pub_path = d / "locker_ed25519.pub.pem"
    # Owner-only from creation (item 50): no umask window with a readable key.
    _priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    _fd = _os.open(str(priv_path), _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
    try:
        with _os.fdopen(_fd, "wb") as f:
            f.write(_priv_bytes)
    except BaseException:
        try:
            _os.close(_fd)
        except OSError:
            pass
        raise
    _os.chmod(priv_path, 0o600)
    pub_path.write_bytes(
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    try:
        _os.chmod(pub_path, 0o644)
    except OSError:
        pass
    return priv_path, pub_path


def load_private_key(path: Path | None = None) -> Ed25519PrivateKey:
    p = path or (DEFAULT_KEY_DIR / "locker_ed25519.pem")
    if not p.exists():
        generate_keypair(p.parent)
    return serialization.load_pem_private_key(p.read_bytes(), password=None)


def load_public_key(path: Path | None = None) -> Ed25519PublicKey:
    p = path or (DEFAULT_KEY_DIR / "locker_ed25519.pub.pem")
    if not p.exists():
        generate_keypair(p.parent)
    return serialization.load_pem_public_key(p.read_bytes())


def build_locker_bundle(interaction_id: str) -> dict[str, Any]:
    """Collect actions + cited snapshots + chain + merkle proof for one contact."""
    with ops_con(read_only=True) as con:
        try:
            acts = con.execute(
                """
                SELECT action_id, interaction_id, case_id, agent, action_type,
                       input_summary, evidence_ids, output_summary, ok, error,
                       duration_ms, row_hash, prev_hash, ts, erased,
                       hash_version, content_hash, claims
                FROM agent_actions WHERE interaction_id = ? ORDER BY ts, action_id
                """,
                [interaction_id],
            ).fetchall()
        except Exception:
            try:
                acts = con.execute(
                    """
                    SELECT action_id, interaction_id, case_id, agent, action_type,
                           input_summary, evidence_ids, output_summary, ok, error,
                           duration_ms, row_hash, prev_hash, ts, erased
                    FROM agent_actions WHERE interaction_id = ? ORDER BY ts, action_id
                    """,
                    [interaction_id],
                ).fetchall()
            except Exception:
                # Pre-erasure schema: no erased column yet.
                acts = con.execute(
                    """
                    SELECT action_id, interaction_id, case_id, agent, action_type,
                           input_summary, evidence_ids, output_summary, ok, error,
                           duration_ms, row_hash, prev_hash, ts
                    FROM agent_actions WHERE interaction_id = ? ORDER BY ts, action_id
                    """,
                    [interaction_id],
                ).fetchall()
        cols = [d[0] for d in con.description]
        actions = [dict(zip(cols, r)) for r in acts]
        # Interaction header + version stamps (reproducibility)
        try:
            hcur = con.execute(
                "SELECT * FROM interactions WHERE interaction_id = ?", [interaction_id]
            )
            hcols = [d[0] for d in hcur.description]
            hrow = hcur.fetchone()
            header = dict(zip(hcols, hrow)) if hrow else {}
        except Exception:
            header = {}
        try:
            vcur = con.execute(
                "SELECT * FROM interaction_version_stamps WHERE interaction_id = ?",
                [interaction_id],
            )
            vcols = [d[0] for d in vcur.description]
            stamps = [dict(zip(vcols, r)) for r in vcur.fetchall()]
        except Exception:
            stamps = []
    pins: list[dict[str, Any]] = []
    for a in actions:
        pins.extend(snapshots_for_action(str(a["action_id"])))
    # Hash-chain verification (tamper-evidence) — full _canon fields
    try:
        from src.ledger.chain import verify_chain

        chain = verify_chain([
            {
                "action_id": a["action_id"],
                "interaction_id": a.get("interaction_id"),
                "case_id": a.get("case_id"),
                "agent": a.get("agent"),
                "action_type": a.get("action_type"),
                "input_summary": a.get("input_summary"),
                "output_summary": a.get("output_summary"),
                "evidence_ids": a.get("evidence_ids"),
                "ok": a.get("ok", True),
                "error": a.get("error"),
                "duration_ms": a.get("duration_ms"),
                "ts": a.get("ts"),
                "prev_hash": a.get("prev_hash"),
                "row_hash": a.get("row_hash"),
                "erased": a.get("erased"),
            }
            for a in actions
        ])
    except Exception as e:
        chain = {"ok": False, "error": f"{type(e).__name__}:{e}"}
    # Merkle inclusion proof (completeness — no dropped contact), anchored at
    # export time (item 9/38): the signed anchor_head is the external root the
    # offline verifier checks the bundled leaves against.
    try:
        from src.ledger.merkle import (
            anchor_tree_head,
            collect_leaves,
            merkle_root,
        )

        leaves = collect_leaves(interaction_ids=[interaction_id])
        proof = {
            "leaf_count": len(leaves),
            "root": merkle_root([str(r["leaf"]) for r in leaves]),
            "leaves": leaves,
        }
        try:
            proof["anchor_head"] = anchor_tree_head(
                signer="locker-export", interaction_ids=[interaction_id]
            )
        except Exception as e:
            proof["anchor_error"] = f"{type(e).__name__}:{e}"
    except Exception as e:
        proof = {"error": f"{type(e).__name__}:{e}", "leaf_count": 0}
    body = {
        "schema": "skew.evidence_locker.v1",
        "interaction_id": interaction_id,
        "exported_at": utc_now().isoformat() + "Z",
        "actions": [
            {k: (str(v) if k in {"ts"} else v) for k, v in a.items()} for a in actions
        ],
        "snapshots": pins,
        "interaction": {k: str(v) if hasattr(v, "isoformat") else v for k, v in header.items()},
        "version_stamps": stamps,
        "chain_verification": chain,
        "merkle_proof": proof,
        "content_sha256": "",
    }
    raw = json.dumps(
        {k: v for k, v in body.items() if k != "content_sha256"},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    body["content_sha256"] = hashlib.sha256(raw).hexdigest()
    return body


def sign_locker_bundle(bundle: dict[str, Any], *, private_key=None) -> dict[str, Any]:
    priv = private_key or load_private_key()
    pub = priv.public_key()
    out = dict(bundle)
    out.pop("signature", None)
    out.pop("public_key_pem", None)
    sig = priv.sign(_payload_bytes(out))
    out["signature"] = sig.hex()
    out["public_key_pem"] = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return out


REQUIRED_BUNDLE_SECTIONS = (
    "schema",
    "interaction_id",
    "exported_at",
    "actions",
    "snapshots",
    "interaction",
    "version_stamps",
    "chain_verification",
    "merkle_proof",
    "content_sha256",
)


def verify_bundle_completeness(bundle: dict[str, Any]) -> dict[str, Any]:
    """Offline completeness check against the external anchor (item 38).

    No network, no database. Verifies:
    - all required evidence sections are present (missing file/metadata fails);
    - the bundled leaves recompute to the EXTERNAL anchor root carried in the
      bundle (modified leaves/metadata fail);
    - the anchor signature itself is valid (invalid external root fails).
    """
    missing = [k for k in REQUIRED_BUNDLE_SECTIONS if k not in bundle]
    if missing:
        return {"ok": False, "error": f"missing_sections:{','.join(missing)}"}
    proof = bundle.get("merkle_proof") or {}
    anchor = proof.get("anchor_head")
    if not anchor:
        return {"ok": False, "error": "missing_anchor:bundle predates anchored export"}
    try:
        from src.ledger.merkle import merkle_root, verify_head_signature

        if not verify_head_signature(anchor):
            return {"ok": False, "error": "anchor_bad_signature:invalid external root"}
        leaves = proof.get("leaves") or []
        if not leaves and (bundle.get("actions") or []):
            return {"ok": False, "error": "missing_leaves:actions without merkle leaves"}
        mv = int(anchor.get("merkle_version") or 1)
        recomputed = merkle_root([str(r.get("leaf")) for r in leaves], merkle_version=mv)
        if recomputed != anchor.get("root"):
            return {"ok": False, "error": "anchor_root_mismatch:bundle modified"}
        expected_leaves = (
            int(anchor["leaf_count"])
            if anchor.get("leaf_count") is not None
            else -1
        )
        if len(leaves) != expected_leaves:
            return {"ok": False, "error": "anchor_count_mismatch:bundle incomplete"}
    except Exception as e:
        return {"ok": False, "error": f"completeness_check_failed:{type(e).__name__}"}
    return {
        "ok": True,
        "interaction_id": bundle.get("interaction_id"),
        "leaf_count": len(proof.get("leaves") or []),
        "anchor_head": anchor.get("head_id"),
    }


def verify_locker_bundle(
    bundle: dict[str, Any],
    *,
    _test_only_override: Any = None,
    public_key: Any = None,
) -> dict[str, Any]:
    """Standalone check: signature + content hash + chain + snapshots.

    Pins trusted keys from TrustRootStore and uses verify_with_ring.
    """
    if "signature" not in bundle:
        return {"ok": False, "error": "missing_signature"}

    from src.security.rotation import verify_with_ring
    from src.security.trust_roots import TrustRootNotFound, TrustRootStore

    override = _test_only_override if _test_only_override is not None else public_key
    store = TrustRootStore()

    if override is not None:
        trusted_keys = [override]
    else:
        try:
            store.get_active_public_key()
        except TrustRootNotFound:
            return {"ok": False, "error": "no_trust_root_configured"}

        trusted_keys = store.get_all_valid_public_keys()
        if not trusted_keys:
            return {"ok": False, "error": "no_trust_root_configured"}

    pem = bundle.get("public_key_pem")
    if pem and override is None:
        valid_pems = [p.strip() for p in store.get_all_valid_pems()]
        if pem.strip() not in valid_pems:
            return {"ok": False, "error": "untrusted_signing_key"}

    try:
        sig_bytes = bytes.fromhex(bundle["signature"])
    except Exception as e:
        return {"ok": False, "error": f"bad_signature:{type(e).__name__}"}

    payload = _payload_bytes(bundle)
    if not verify_with_ring(payload, sig_bytes, trusted_keys):
        return {"ok": False, "error": "signature_verification_failed"}
    expected = bundle.get("content_sha256")
    raw = json.dumps(
        {
            k: v
            for k, v in bundle.items()
            if k not in ("signature", "public_key_pem", "content_sha256")
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    got = hashlib.sha256(raw).hexdigest()
    if expected and expected != got:
        return {"ok": False, "error": "content_hash_mismatch"}
    # Reverify hash chain from bundled actions (needs full _canon fields)
    try:
        from src.ledger.chain import verify_chain

        acts = bundle.get("actions") or []
        chain = verify_chain([
            {
                "action_id": a.get("action_id"),
                "interaction_id": a.get("interaction_id"),
                "case_id": a.get("case_id"),
                "agent": a.get("agent"),
                "action_type": a.get("action_type"),
                "input_summary": a.get("input_summary"),
                "output_summary": a.get("output_summary"),
                "evidence_ids": a.get("evidence_ids"),
                "claims": a.get("claims"),
                "hash_version": a.get("hash_version", 1),
                "content_hash": a.get("content_hash"),
                "ok": a.get("ok", True),
                "error": a.get("error"),
                "duration_ms": a.get("duration_ms"),
                "ts": a.get("ts"),
                "prev_hash": a.get("prev_hash"),
                "row_hash": a.get("row_hash"),
                "erased": a.get("erased"),
            }
            for a in acts
        ])
        if not chain.get("ok"):
            return {"ok": False, "error": f"chain_broken:{chain}"}
    except Exception as e:
        return {"ok": False, "error": f"chain_verify_failed:{type(e).__name__}"}
    # Reverify snapshot hashes from bundled bodies
    try:
        from src.qubot.evidence_pin import canonical_row_hash

        for s in bundle.get("snapshots") or []:
            body = json.loads(s.get("body_json") or "{}")
            if canonical_row_hash(body) != s.get("body_hash"):
                return {"ok": False, "error": f"snapshot_hash_mismatch:{s.get('evidence_id')}"}
    except Exception as e:
        return {"ok": False, "error": f"snapshot_verify_failed:{type(e).__name__}"}
    # Reverify leaves against the anchored external root (items 9/38):
    # deleting, modifying, or reordering bundled leaves fails offline.
    if "schema" in bundle or "merkle_proof" in bundle:
        completeness = verify_bundle_completeness(bundle)
        if not completeness.get("ok"):
            return {"ok": False, "error": completeness.get("error")}
    return {"ok": True, "interaction_id": bundle.get("interaction_id")}


def export_locker(interaction_id: str, dest: Path | None = None) -> Path:
    bundle = sign_locker_bundle(build_locker_bundle(interaction_id))
    path = dest or (locker_dir() / f"{interaction_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Evidence Locker")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("bundle")
    args = p.parse_args(argv)
    if args.cmd == "verify":
        data = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        result = verify_locker_bundle(data)
        print(result)
        return 0 if result.get("ok") else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
