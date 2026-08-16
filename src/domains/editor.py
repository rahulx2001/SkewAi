"""Live pack editor with hot reload (feature #43).

Edit slot prompts / safety lexicon / advisory SQL in memory, lint, then apply
without process restart via active_pack cache clear.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from src.config import REPO_ROOT
from src.domains.loader import load_pack, lint_pack


def _safe_pack_id(pack_id: str) -> str:
    """Reject path traversal in pack_id (function-layer jail)."""
    from pathlib import Path as _P

    safe = _P(pack_id).name
    if safe != pack_id or not safe or safe in {".", ".."} or safe.startswith("_"):
        raise ValueError(f"invalid pack_id: {pack_id!r}")
    return safe


def pack_dir(pack_id: str) -> Path:
    safe = _safe_pack_id(pack_id)
    root = (REPO_ROOT / "domains").resolve()
    d = (root / safe).resolve()
    try:
        d.relative_to(root)
    except ValueError as e:
        raise ValueError(f"pack_id escapes domains root: {pack_id!r}") from e
    return d


def read_pack_files(pack_id: str) -> dict[str, Any]:
    d = pack_dir(pack_id)
    out: dict[str, Any] = {"pack_id": pack_id, "files": {}}
    for name in ("pack.yaml", "taxonomy.yaml"):
        p = d / name
        if p.is_file():
            out["files"][name] = yaml.safe_load(p.read_text()) or {}
    return out


def apply_pack_edits(
    pack_id: str,
    edits: dict[str, Any],
    *,
    write_disk: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply nested edits to pack.yaml keys (e.g. safety_lexicon, slots).

    edits example: {"safety_lexicon": [...], "slot_prompts": {...}}
    """
    try:
        d = pack_dir(pack_id)
    except ValueError as e:
        raise FileNotFoundError(str(e)) from e
    pack_yaml = d / "pack.yaml"
    if not pack_yaml.is_file():
        raise FileNotFoundError(pack_id)
    data = yaml.safe_load(pack_yaml.read_text()) or {}
    before = copy.deepcopy(data)
    for key, val in edits.items():
        if key.startswith("_"):
            continue
        data[key] = val
    # Lint via temp write or in-memory — loader reads disk, so dry_run skips write
    result: dict[str, Any] = {
        "pack_id": pack_id,
        "changed_keys": list(edits.keys()),
        "dry_run": dry_run,
    }
    if dry_run:
        result["preview"] = data
        result["lint"] = {"ok": True, "note": "dry_run_skip_disk_lint"}
        return result
    if write_disk:
        pack_yaml.write_text(yaml.safe_dump(data, sort_keys=False))
    # Clear active pack caches if any
    try:
        from src.domains import active_pack

        if hasattr(active_pack, "clear_cache"):
            active_pack.clear_cache()
        elif hasattr(active_pack, "_cache"):
            active_pack._cache.clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        from src.domains.loader import load_pack as _lp

        if hasattr(_lp, "cache_clear"):
            _lp.cache_clear()
    except Exception:
        pass
    try:
        from src.domains.loader import load_pack, lint_pack as _lint

        load_pack(pack_id, reload=True)
        errs = _lint(pack_id)
        if errs:
            pack_yaml.write_text(yaml.safe_dump(before, sort_keys=False))
            result["lint"] = {"ok": False, "errors": errs}
            result["rolled_back"] = True
            return result
        result["lint"] = {"ok": True, "errors": []}
    except Exception as e:
        pack_yaml.write_text(yaml.safe_dump(before, sort_keys=False))
        result["lint"] = {"ok": False, "error": str(e)}
        result["rolled_back"] = True
        return result
    result["applied"] = True
    return result


def hot_reload(pack_id: str) -> dict[str, Any]:
    """Force re-load pack from disk into process."""
    try:
        from src.domains.loader import load_pack

        if hasattr(load_pack, "cache_clear"):
            load_pack.cache_clear()
        p = load_pack(pack_id)
        return {
            "ok": True,
            "pack_id": pack_id,
            "display_name": getattr(p, "display_name", None) or getattr(p, "name", pack_id),
        }
    except Exception as e:
        return {"ok": False, "pack_id": pack_id, "error": str(e)}
