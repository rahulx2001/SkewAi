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


def _payload_bytes(bundle: dict[str, Any]) -> bytes:
    payload = {k: v for k, v in bundle.items() if k not in ("signature", "public_key_pem")}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def generate_keypair(dir_path: Path | None = None) -> tuple[Path, Path]:
    d = dir_path or DEFAULT_KEY_DIR
    d.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    priv_path = d / "locker_ed25519.pem"
    pub_path = d / "locker_ed25519.pub.pem"
    priv_path.write_bytes(
        priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_path.write_bytes(
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
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
    """Collect actions + cited snapshots for one contact."""
    with ops_con(read_only=True) as con:
        acts = con.execute(
            """
            SELECT action_id, interaction_id, agent, action_type,
                   evidence_ids, output_summary, row_hash, prev_hash, ts
            FROM agent_actions WHERE interaction_id = ? ORDER BY ts, action_id
            """,
            [interaction_id],
        ).fetchall()
        cols = [d[0] for d in con.description]
        actions = [dict(zip(cols, r)) for r in acts]
    pins: list[dict[str, Any]] = []
    for a in actions:
        pins.extend(snapshots_for_action(str(a["action_id"])))
    body = {
        "schema": "skew.evidence_locker.v1",
        "interaction_id": interaction_id,
        "exported_at": utc_now().isoformat() + "Z",
        "actions": [
            {k: (str(v) if k in {"ts"} else v) for k, v in a.items()} for a in actions
        ],
        "snapshots": pins,
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


def verify_locker_bundle(bundle: dict[str, Any], *, public_key=None) -> dict[str, Any]:
    """Standalone check: signature + content hash. Does not need DuckDB."""
    if "signature" not in bundle:
        return {"ok": False, "error": "missing_signature"}
    pem = bundle.get("public_key_pem")
    try:
        pub = public_key or serialization.load_pem_public_key(pem.encode("ascii"))
        pub.verify(bytes.fromhex(bundle["signature"]), _payload_bytes(bundle))
    except Exception as e:
        return {"ok": False, "error": f"bad_signature:{type(e).__name__}"}
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
    return {"ok": True, "interaction_id": bundle.get("interaction_id")}


def export_locker(interaction_id: str, dest: Path | None = None) -> Path:
    bundle = sign_locker_bundle(build_locker_bundle(interaction_id))
    path = dest or (
        REPO_ROOT / "reports" / "qubot" / "lockers" / f"{interaction_id}.json"
    )
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
