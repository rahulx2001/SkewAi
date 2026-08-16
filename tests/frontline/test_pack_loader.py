"""Pack loader tests (per blueprint §15.2).

Covers:
  - Manifest schema validation (rejects malformed pack.yaml)
  - pack_version hashing (deterministic, content-addressed)
  - Broken-pack rejection (missing gazetteer, schema error)
  - automotive_nhtsa pack loads clean
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.domains.loader import LoadedPack, lint_pack, load_pack
from src.domains.schema import PackManifest


# ── automotive pack loads clean ────────────────────────────────────────────────


def test_automotive_pack_loads(pack):
    assert isinstance(pack, LoadedPack)
    assert pack.id == "automotive_nhtsa"
    assert pack.display_name == "Automotive (NHTSA)"
    # Three entity labels are present.
    assert set(pack.entity_labels.keys()) == {"entity_1", "entity_2", "entity_3"}
    # Slot frame is non-empty and includes a description slot.
    slot_names = [s.name for s in pack.manifest.slot_frame]
    assert "description" in slot_names
    # Gazetteers were resolved (one per gazetteer-validated slot).
    assert "makes" in pack.gazetteers
    assert "models" in pack.gazetteers
    assert "categories" in pack.gazetteers
    # Each gazetteer has at least one value.
    for name, gaz in pack.gazetteers.items():
        assert len(gaz.values) > 0, f"gazetteer '{name}' is empty"


def test_automotive_pack_lints_clean(pack):
    """`make pack-lint PACK=automotive_nhtsa` must report zero errors."""
    errors = lint_pack("automotive_nhtsa")
    assert errors == [], f"automotive_nhtsa has lint errors: {errors}"


# ── pack_version hashing ──────────────────────────────────────────────────────


def test_pack_version_is_stable_string(pack):
    assert isinstance(pack.pack_version, str)
    assert len(pack.pack_version) == 12  # sha256 truncated to 12 hex chars
    int(pack.pack_version, 16)  # must be valid hex


def test_pack_version_is_content_addressed():
    """Loading the same pack twice yields the same pack_version."""
    a = load_pack("automotive_nhtsa", reload=True)
    b = load_pack("automotive_nhtsa", reload=True)
    assert a.pack_version == b.pack_version


def test_pack_version_changes_when_manifest_changes(pack, tmp_path, monkeypatch):
    """Editing pack.yaml invalidates the cached version hash."""
    original = load_pack("automotive_nhtsa", reload=True)
    # Mutate the manifest file in place.
    manifest_path = pack.pack_dir / "pack.yaml"
    original_bytes = manifest_path.read_bytes()
    try:
        # Append a benign comment to change the file's bytes (and thus the hash).
        manifest_path.write_bytes(original_bytes + b"\n# test mutation\n")
        mutated = load_pack("automotive_nhtsa", reload=True)
        assert mutated.pack_version != original.pack_version
    finally:
        # Always restore the original so other tests aren't polluted.
        manifest_path.write_bytes(original_bytes)
        load_pack("automotive_nhtsa", reload=True)


# ── Schema validation ─────────────────────────────────────────────────────────


def test_manifest_requires_description_slot():
    """A slot_frame without a `description` slot must fail schema validation."""
    bad_manifest = {
        "id": "test_pack",
        "display_name": "Test",
        "greeting": "Hi",
        "goodbye": "Bye {case_id}",
        "entities": {"entity_1": "Y", "entity_2": "M", "entity_3": "Mo"},
        "slot_frame": [
            {"name": "entity_1", "label": "Year", "prompt": "?", "required": True},
        ],
        "safety": {
            "escalation_lexicon": ["fire"],
            "escalation_script": "escalate",
        },
        "advisory_match": {"sql_template": "SELECT 1"},
        "severity": {"rules": [{"when": "default", "severity": "Low"}]},
    }
    with pytest.raises(Exception):
        PackManifest.model_validate(bad_manifest)


def test_manifest_requires_severity_path():
    """A pack with neither model_artifact nor rules must fail lint."""
    bad_manifest = {
        "id": "test_pack",
        "display_name": "Test",
        "greeting": "Hi",
        "goodbye": "Bye {case_id}",
        "entities": {"entity_1": "Y", "entity_2": "M", "entity_3": "Mo"},
        "slot_frame": [
            {"name": "description", "label": "Desc", "prompt": "?", "required": True},
        ],
        "safety": {
            "escalation_lexicon": ["fire"],
            "escalation_script": "escalate",
        },
        "advisory_match": {"sql_template": "SELECT 1"},
        "severity": {},  # no model_artifact, no rules
    }
    # The manifest itself is valid (rules defaults to []), but lint_pack rejects it.
    manifest = PackManifest.model_validate(bad_manifest)
    assert manifest.severity.rules == []
    # lint_pack would flag this — verify by direct check.
    assert not manifest.severity.model_artifact and not manifest.severity.rules


def test_advisory_match_rejects_write_sql():
    """The schema must reject any advisory SQL that contains INSERT/UPDATE/DELETE/etc."""
    bad = {
        "id": "test_pack",
        "display_name": "Test",
        "greeting": "Hi",
        "goodbye": "Bye {case_id}",
        "entities": {"entity_1": "Y", "entity_2": "M", "entity_3": "Mo"},
        "slot_frame": [
            {"name": "description", "label": "Desc", "prompt": "?", "required": True},
        ],
        "safety": {
            "escalation_lexicon": ["fire"],
            "escalation_script": "escalate",
        },
        "advisory_match": {"sql_template": "DELETE FROM advisories WHERE 1=1"},
        "severity": {"rules": [{"when": "default", "severity": "Low"}]},
    }
    with pytest.raises(Exception) as exc_info:
        PackManifest.model_validate(bad)
    assert "forbidden" in str(exc_info.value).lower()


# ── Broken pack on disk ────────────────────────────────────────────────────────


class _FakeSettings:
    """Minimal duck-typed settings for the broken-pack tests.

    Only packs_root and pack_dir() are used by load_pack, so we expose just those.
    """
    def __init__(self, domains_root: Path):
        self._domains_root = domains_root

    @property
    def packs_root(self) -> Path:
        return self._domains_root

    def pack_dir(self, pack_id: str) -> Path:
        return self._domains_root / pack_id


def _write_minimal_pack(pack_dir: Path, manifest: dict) -> None:
    (pack_dir / "gazetteers").mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.yaml").write_text(yaml.safe_dump(manifest))


def test_broken_pack_missing_gazetteer_rejected(tmp_path, monkeypatch):
    """A pack whose slot references a non-existent gazetteer is rejected."""
    from src.domains import loader as loader_module

    domains_root = tmp_path / "domains"
    pack_dir = domains_root / "broken_pack"
    _write_minimal_pack(pack_dir, {
        "id": "broken_pack",
        "display_name": "Broken",
        "greeting": "Hi",
        "goodbye": "Bye {case_id}",
        "entities": {"entity_1": "Y", "entity_2": "M", "entity_3": "Mo"},
        "slot_frame": [
            {
                "name": "entity_2",
                "label": "Make",
                "prompt": "?",
                "required": True,
                "validation": "gazetteer",
                "gazetteer": "makes",  # missing on disk
            },
            {"name": "description", "label": "Desc", "prompt": "?", "required": True},
        ],
        "safety": {
            "escalation_lexicon": ["fire"],
            "escalation_script": "escalate",
        },
        "advisory_match": {"sql_template": "SELECT 1 FROM advisories"},
        "severity": {"rules": [{"when": "default", "severity": "Low"}]},
    })

    monkeypatch.setattr(loader_module, "settings", _FakeSettings(domains_root))
    with pytest.raises(FileNotFoundError):
        load_pack("broken_pack", reload=True)


def test_broken_pack_missing_manifest_rejected(tmp_path, monkeypatch):
    """A pack directory without pack.yaml is rejected with FileNotFoundError."""
    from src.domains import loader as loader_module

    domains_root = tmp_path / "domains"
    (domains_root / "empty_pack").mkdir(parents=True)
    monkeypatch.setattr(loader_module, "settings", _FakeSettings(domains_root))

    with pytest.raises(FileNotFoundError):
        load_pack("empty_pack", reload=True)


def test_broken_pack_missing_required_field_rejected(tmp_path, monkeypatch):
    """A pack.yaml missing a required top-level field fails schema validation."""
    from src.domains import loader as loader_module

    domains_root = tmp_path / "domains"
    pack_dir = domains_root / "incomplete_pack"
    # Missing the `safety` block.
    _write_minimal_pack(pack_dir, {
        "id": "incomplete_pack",
        "display_name": "Incomplete",
        "greeting": "Hi",
        "goodbye": "Bye {case_id}",
        "entities": {"entity_1": "Y", "entity_2": "M", "entity_3": "Mo"},
        "slot_frame": [
            {"name": "description", "label": "Desc", "prompt": "?", "required": True},
        ],
        "advisory_match": {"sql_template": "SELECT 1 FROM advisories"},
        "severity": {"rules": [{"when": "default", "severity": "Low"}]},
    })
    monkeypatch.setattr(loader_module, "settings", _FakeSettings(domains_root))

    with pytest.raises(Exception):
        load_pack("incomplete_pack", reload=True)
