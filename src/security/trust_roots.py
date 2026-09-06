"""Pinned trust root store and verification keys for evidence lockers and Merkle logs.

Addresses F-001: Verifiers must pin the trusted public key rather than accepting
an attacker-supplied public key embedded in the verified artifact.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.config import REPO_ROOT

TRUST_ROOTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trust_roots (
    key_id         TEXT PRIMARY KEY,
    public_key_pem TEXT NOT NULL,
    created_at     TIMESTAMP NOT NULL,
    revoked_at     TIMESTAMP NULL,
    created_by     TEXT NOT NULL
);
"""


class TrustRootNotFound(Exception):
    """Raised when no active or matching trust root is configured."""


@dataclass
class TrustRoot:
    key_id: str
    public_key_pem: str
    created_at: datetime
    revoked_at: Optional[datetime] = None
    created_by: str = "platform-admin"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def raw_public_bytes(self) -> bytes:
        """Return raw 32 bytes for Ed25519."""
        pub = serialization.load_pem_public_key(self.public_key_pem.encode("ascii"))
        if isinstance(pub, Ed25519PublicKey):
            return pub.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        return pub.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )


def _default_json_path() -> Path:
    raw = os.getenv("FRONTLINE_TRUST_ROOT_PATH")
    if raw:
        p = Path(raw).expanduser()
        return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()
    return REPO_ROOT / "data" / "trust_roots.json"


def _parse_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


class TrustRootStore:
    def __init__(
        self,
        db_con: Any | None = None,
        json_path: Path | str | None = None,
    ) -> None:
        self._con = db_con
        if json_path is not None:
            self._json_path = Path(json_path)
        else:
            self._json_path = _default_json_path()

    def _ensure_table(self, con: Any) -> None:
        try:
            con.execute(TRUST_ROOTS_SCHEMA_SQL)
        except Exception:
            pass

    def _auto_import_initial_key(self, con: Any) -> dict[str, TrustRoot]:
        if os.getenv("FRONTLINE_TRUST_ROOT_PATH") is not None:
            return {}
        pem: str | None = None
        key_id = (os.getenv("FRONTLINE_TRUST_ROOT_KEY_ID") or "default-locker-key").strip()

        env_key = (os.getenv("FRONTLINE_SIGNING_KEY") or "").strip()
        if env_key:
            if "-----BEGIN" in env_key:
                pem = env_key
            elif Path(env_key).is_file():
                try:
                    pem = Path(env_key).read_text(encoding="utf-8")
                except Exception:
                    pem = None
        if not pem:
            pub_path = REPO_ROOT / "data" / "locker_keys" / "locker_ed25519.pub.pem"
            if pub_path.is_file():
                try:
                    pem = pub_path.read_text(encoding="utf-8")
                except Exception:
                    pem = None

        if pem:
            cat = datetime(2024, 1, 1, tzinfo=timezone.utc)
            try:
                con.execute(
                    """
                    INSERT INTO trust_roots (key_id, public_key_pem, created_at, revoked_at, created_by)
                    VALUES (?, ?, ?, NULL, ?)
                    ON CONFLICT (key_id) DO NOTHING
                    """,
                    [key_id, pem.strip() + "\n", cat.isoformat(), "system-initial-import"],
                )
            except Exception:
                pass
            return {
                key_id: TrustRoot(
                    key_id=key_id,
                    public_key_pem=pem.strip() + "\n",
                    created_at=cat,
                    created_by="system-initial-import",
                )
            }
        return {}

    def _load_from_db(self) -> dict[str, TrustRoot]:
        roots: dict[str, TrustRoot] = {}
        try:
            from src.data.warehouse import ops_con

            con_cm = ops_con() if self._con is None else None
            con = self._con or con_cm.__enter__()
            try:
                self._ensure_table(con)
                cur = con.execute(
                    "SELECT key_id, public_key_pem, created_at, revoked_at, created_by FROM trust_roots"
                )
                for row in cur.fetchall():
                    kid, pem, cat, rat, cby = row
                    roots[kid] = TrustRoot(
                        key_id=str(kid),
                        public_key_pem=str(pem),
                        created_at=_parse_dt(cat) or datetime.now(timezone.utc),
                        revoked_at=_parse_dt(rat),
                        created_by=str(cby or "admin"),
                    )
                if not roots:
                    imported = self._auto_import_initial_key(con)
                    roots.update(imported)
            finally:
                if con_cm:
                    con_cm.__exit__(None, None, None)
        except Exception:
            pass
        return roots

    def _load_from_json(self) -> dict[str, TrustRoot]:
        roots: dict[str, TrustRoot] = {}
        p = self._json_path
        if p and p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for k in data.get("keys", []):
                    kid = k.get("key_id")
                    pem = k.get("public_key_pem")
                    if kid and pem:
                        roots[kid] = TrustRoot(
                            key_id=str(kid),
                            public_key_pem=str(pem),
                            created_at=_parse_dt(k.get("created_at")) or datetime.now(timezone.utc),
                            revoked_at=_parse_dt(k.get("revoked_at")),
                            created_by=str(k.get("created_by") or "platform-admin"),
                        )
            except Exception:
                pass
        return roots

    def _load_from_default_key(self) -> dict[str, TrustRoot]:
        if os.getenv("FRONTLINE_TRUST_ROOT_PATH") is not None:
            return {}
        pub_path = REPO_ROOT / "data" / "locker_keys" / "locker_ed25519.pub.pem"
        if pub_path.is_file():
            try:
                pem = pub_path.read_text(encoding="utf-8")
                return {
                    "default-locker-key": TrustRoot(
                        key_id="default-locker-key",
                        public_key_pem=pem,
                        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        revoked_at=None,
                        created_by="system-default",
                    )
                }
            except Exception:
                pass
        return {}

    def load_all_roots(self) -> dict[str, TrustRoot]:
        if os.getenv("FRONTLINE_TRUST_ROOT_PATH") is not None:
            return self._load_from_json()
        db_roots = self._load_from_db()
        if db_roots:
            return db_roots
        json_roots = self._load_from_json()
        if json_roots:
            return json_roots
        return self._load_from_default_key()

    def get_root(self, key_id: str) -> TrustRoot | None:
        roots = self.load_all_roots()
        return roots.get(key_id)

    def is_revoked(self, key_id: str) -> bool:
        r = self.get_root(key_id)
        if not r:
            return False
        return r.is_revoked

    def get_public_key(self, key_id: str) -> bytes | None:
        r = self.get_root(key_id)
        if not r or r.is_revoked:
            return None
        return r.raw_public_bytes()

    def get_active_key_id(self) -> str | None:
        env_id = (os.getenv("FRONTLINE_TRUST_ROOT_KEY_ID") or "").strip()
        if env_id:
            return env_id
        roots = self.load_all_roots()
        valid = [r for r in roots.values() if not r.is_revoked]
        if not valid:
            return None
        # Pick latest created_at
        valid.sort(key=lambda r: r.created_at, reverse=True)
        return valid[0].key_id

    def get_active_public_key(self) -> bytes:
        active_id = self.get_active_key_id()
        if not active_id:
            raise TrustRootNotFound("No active trust root key ID configured or found")
        pk = self.get_public_key(active_id)
        if not pk:
            raise TrustRootNotFound(f"Active trust root key {active_id!r} is not found or revoked")
        return pk

    def get_all_valid_public_keys(self) -> list[bytes]:
        """All unrevoked public keys suitable for Ed25519 ring verification."""
        roots = self.load_all_roots()
        keys: list[bytes] = []
        for r in roots.values():
            if not r.is_revoked:
                keys.append(r.raw_public_bytes())
        return keys

    def get_all_valid_pems(self) -> list[str]:
        roots = self.load_all_roots()
        return [r.public_key_pem.strip() for r in roots.values() if not r.is_revoked]

    def register_root(
        self,
        *,
        key_id: str,
        public_key_pem: str,
        created_by: str = "platform-admin",
        created_at: datetime | None = None,
    ) -> TrustRoot:
        cat = created_at or datetime.now(timezone.utc)
        root = TrustRoot(
            key_id=key_id,
            public_key_pem=public_key_pem.strip() + "\n",
            created_at=cat,
            created_by=created_by,
        )
        # 1. Update DB if available
        try:
            from src.data.warehouse import ops_con

            con_cm = ops_con() if self._con is None else None
            con = self._con or con_cm.__enter__()
            try:
                self._ensure_table(con)
                con.execute(
                    """
                    INSERT INTO trust_roots (key_id, public_key_pem, created_at, revoked_at, created_by)
                    VALUES (?, ?, ?, NULL, ?)
                    ON CONFLICT (key_id) DO UPDATE SET
                        public_key_pem = excluded.public_key_pem,
                        created_by = excluded.created_by
                    """,
                    [key_id, root.public_key_pem, cat.isoformat(), created_by],
                )
            finally:
                if con_cm:
                    con_cm.__exit__(None, None, None)
        except Exception:
            pass

        # 2. Update JSON path if it exists or was specified
        p = self._json_path
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"keys": []}
        except Exception:
            data = {"keys": []}
        keys = [k for k in data.get("keys", []) if k.get("key_id") != key_id]
        keys.append({
            "key_id": key_id,
            "public_key_pem": root.public_key_pem,
            "created_at": cat.isoformat(),
            "revoked_at": None,
            "created_by": created_by,
        })
        data["keys"] = keys
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return root

    def revoke_root(self, key_id: str, revoked_at: datetime | None = None) -> None:
        rat = revoked_at or datetime.now(timezone.utc)
        try:
            from src.data.warehouse import ops_con

            con_cm = ops_con() if self._con is None else None
            con = self._con or con_cm.__enter__()
            try:
                self._ensure_table(con)
                con.execute(
                    "UPDATE trust_roots SET revoked_at = ? WHERE key_id = ?",
                    [rat.isoformat(), key_id],
                )
            finally:
                if con_cm:
                    con_cm.__exit__(None, None, None)
        except Exception:
            pass

        p = self._json_path
        if p and p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for k in data.get("keys", []):
                    if k.get("key_id") == key_id:
                        k["revoked_at"] = rat.isoformat()
                p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass


def get_default_trust_store() -> TrustRootStore:
    return TrustRootStore()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trust Roots Management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import")
    imp.add_argument("--key-id", required=True, help="Unique key identifier")
    imp.add_argument("--key-file", required=True, help="Path to public key PEM file")
    imp.add_argument("--created-by", default="cli", help="Creator identifier")

    args = parser.parse_args(argv)
    if args.cmd == "import":
        pem_path = Path(args.key_file)
        if not pem_path.is_file():
            print(f"Error: key file {pem_path} not found")
            return 1
        pem = pem_path.read_text(encoding="utf-8")
        store = get_default_trust_store()
        root = store.register_root(
            key_id=args.key_id,
            public_key_pem=pem,
            created_by=args.created_by,
        )
        print(f"Registered trust root {root.key_id}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
