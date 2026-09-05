"""Pack marketplace / registry (feature #41).

Versioned, shareable pack manifests with semver + changelog. Install copies
or registers a pack path without network (local registry under domains/).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from src.config import REPO_ROOT


def registry_path() -> Path:
    """Pack registry JSON. ``PACK_REGISTRY_PATH`` isolates pytest from git."""
    import os

    raw = (os.getenv("PACK_REGISTRY_PATH") or "").strip()
    if not raw:
        return REPO_ROOT / "domains" / "registry.json"
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()


# Default on-disk path (tests should use registry_path() / PACK_REGISTRY_PATH).
REGISTRY_PATH = REPO_ROOT / "domains" / "registry.json"


def _semver_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in (v or "0.0.0").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def load_registry() -> dict[str, Any]:
    path = registry_path()
    if path.is_file():
        return json.loads(path.read_text())
    # Bootstrap from on-disk packs
    packs = []
    domains = REPO_ROOT / "domains"
    for d in sorted(domains.iterdir() if domains.is_dir() else []):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        py = d / "pack.yaml"
        if not py.is_file():
            continue
        packs.append(
            {
                "pack_id": d.name,
                "version": "1.0.0",
                "path": str(d.relative_to(REPO_ROOT)),
                "changelog": [f"1.0.0 — registered from {d.name}"],
            }
        )
    reg = {"schema": 1, "packs": packs}
    save_registry(reg)
    return reg


def save_registry(reg: dict[str, Any]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reg, indent=2) + "\n")


def list_marketplace() -> list[dict[str, Any]]:
    return list(load_registry().get("packs") or [])


def publish_pack(
    pack_id: str,
    *,
    version: str = "1.0.0",
    changelog_entry: str | None = None,
) -> dict[str, Any]:
    reg = load_registry()
    packs = reg.setdefault("packs", [])
    entry = None
    for p in packs:
        if p["pack_id"] == pack_id:
            entry = p
            break
    path = f"domains/{pack_id}"
    if entry is None:
        entry = {
            "pack_id": pack_id,
            "version": version,
            "path": path,
            "changelog": [],
        }
        packs.append(entry)
    else:
        if _semver_tuple(version) < _semver_tuple(entry.get("version") or "0.0.0"):
            raise ValueError(f"version {version} is older than {entry['version']}")
        entry["version"] = version
    note = changelog_entry or f"{version} — published"
    entry.setdefault("changelog", []).append(note)
    entry["path"] = path
    save_registry(reg)
    return entry


def pack_install_allow_root() -> Path:
    """Root under which ``source_path`` may live (FIND-005 jail)."""
    import os

    raw = (os.getenv("PACK_INSTALL_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (REPO_ROOT / "domains").resolve()


def assert_source_path_allowed(source_path: str) -> Path:
    """Resolve and jail ``source_path`` under the pack install allow-root.

    Raises ValueError if the path escapes the allow root or is not a directory.
    """
    import os

    # Hardened / production: disable filesystem copy entirely
    if (os.getenv("FRONTLINE_AUTH_REQUIRED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } or (os.getenv("PILOT_HARDENED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        if (os.getenv("PACK_INSTALL_ALLOW_SOURCE") or "").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise ValueError(
                "source_path install disabled when auth is required "
                "(set PACK_INSTALL_ALLOW_SOURCE=1 only with PACK_INSTALL_ROOT jail)"
            )

    root = pack_install_allow_root()
    try:
        src = Path(source_path).expanduser().resolve(strict=False)
    except OSError as e:
        raise ValueError(f"invalid source_path: {e}") from e
    try:
        src.relative_to(root)
    except ValueError as e:
        raise ValueError(
            f"source_path outside allow root {root}: {source_path!r}"
        ) from e
    if not src.is_dir():
        raise FileNotFoundError(source_path)
    return src


def pack_install(pack_id: str, *, source_path: str | None = None) -> dict[str, Any]:
    """Install/register a pack. If source_path given, copy into domains/ (jailed)."""
    # Reject path traversal in pack_id
    safe_id = Path(pack_id).name
    if safe_id != pack_id or not safe_id or safe_id in {".", ".."}:
        raise ValueError(f"invalid pack_id: {pack_id!r}")
    dest = REPO_ROOT / "domains" / safe_id
    if source_path:
        src = assert_source_path_allowed(source_path)
        if dest.exists() and dest.resolve() != src.resolve():
            if not (dest / "pack.yaml").exists():
                shutil.copytree(src, dest, dirs_exist_ok=True)
        elif not dest.exists():
            shutil.copytree(src, dest)
    if not (dest / "pack.yaml").is_file():
        raise FileNotFoundError(f"pack.yaml missing for {safe_id}")
    reg = load_registry()
    existing = next((p for p in reg.get("packs") or [] if p.get("pack_id") == safe_id), None)
    ver = (existing or {}).get("version") or "1.0.0"
    entry = publish_pack(safe_id, version=ver, changelog_entry=f"{ver} — pack-install")
    return {"installed": True, "pack_id": safe_id, "entry": entry}


VERTICALS = ("consumer_cpsc", "medical_maude")


def install_vertical(pack_id: str) -> dict[str, Any]:
    """Install a named vertical and prove the pack loads."""
    if pack_id not in VERTICALS and pack_id not in {
        p["pack_id"] for p in list_marketplace()
    }:
        # still try if the directory exists
        dest = REPO_ROOT / "domains" / pack_id
        if not (dest / "pack.yaml").is_file():
            raise FileNotFoundError(pack_id)
    installed = pack_install(pack_id)
    from src.domains.loader import load_pack

    pack = load_pack(pack_id, reload=True)
    return {
        "installed": True,
        "pack_id": pack_id,
        "loadable": bool(pack and pack.id == pack_id),
        "entry": installed.get("entry"),
        "display_name": getattr(pack, "display_name", None) or pack_id,
    }
