"""Prove tests never wipe the pilot ops warehouse under data/."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config import (
    DEFAULT_DOMAIN_DB_DIR,
    DEFAULT_OPS_DB,
    is_default_pilot_domain_path,
    is_default_pilot_ops_path,
    resolve_domain_db_dir,
    resolve_frontline_db_path,
)
from src.data.warehouse import reset_ops_db, unlink_domain_db


def test_pytest_isolation_redirects_ops_db_away_from_pilot():
    """Session isolation sets FRONTLINE_DB_PATH outside default pilot path."""
    path = resolve_frontline_db_path()
    assert not is_default_pilot_ops_path(path)
    assert path != DEFAULT_OPS_DB
    assert "skewai_pytest_data" in str(path) or os.getenv("FRONTLINE_TEST_ISOLATION") == "1"


def test_reset_ops_db_refuses_default_pilot_path(monkeypatch, tmp_path):
    """Driving real reset_ops_db against default path raises without allow flag."""
    monkeypatch.delenv("FRONTLINE_ALLOW_DEFAULT_DB_RESET", raising=False)
    monkeypatch.setenv("FRONTLINE_DB_PATH", str(DEFAULT_OPS_DB))
    # Marker must survive a refused reset
    DEFAULT_OPS_DB.parent.mkdir(parents=True, exist_ok=True)
    marker = DEFAULT_OPS_DB.parent / ".isolation_marker_probe"
    marker.write_text("do-not-delete\n", encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="refusing to reset pilot ops DB"):
            reset_ops_db()
        assert marker.is_file()
        assert marker.read_text(encoding="utf-8") == "do-not-delete\n"
    finally:
        marker.unlink(missing_ok=True)


def test_reset_ops_db_works_on_isolated_path(tmp_path, monkeypatch):
    isolated = tmp_path / "ops.duckdb"
    monkeypatch.setenv("FRONTLINE_DB_PATH", str(isolated))
    monkeypatch.delenv("FRONTLINE_ALLOW_DEFAULT_DB_RESET", raising=False)
    reset_ops_db()
    assert isolated.is_file()


def test_unlink_domain_db_refuses_default_pilot_path_without_force(monkeypatch):
    """Existing pilot domain DB under data/domains/ is not deleted without force/allow."""
    monkeypatch.delenv("FRONTLINE_ALLOW_DEFAULT_DB_RESET", raising=False)
    monkeypatch.delenv("FRONTLINE_ALLOW_DOMAIN_DB_RESET", raising=False)
    DEFAULT_DOMAIN_DB_DIR.mkdir(parents=True, exist_ok=True)
    probe = DEFAULT_DOMAIN_DB_DIR / "_isolation_domain_probe.duckdb"
    probe.write_bytes(b"keep-me")
    try:
        assert is_default_pilot_domain_path(probe)
        with pytest.raises(RuntimeError, match="refusing to delete pilot domain DB"):
            unlink_domain_db(probe, force=False)
        assert probe.is_file()
        assert probe.read_bytes() == b"keep-me"
    finally:
        probe.unlink(missing_ok=True)


def test_unlink_domain_db_force_deletes_pilot_path(monkeypatch):
    """force=True allows intentional rebuild of a pilot domain warehouse file."""
    monkeypatch.delenv("FRONTLINE_ALLOW_DEFAULT_DB_RESET", raising=False)
    monkeypatch.delenv("FRONTLINE_ALLOW_DOMAIN_DB_RESET", raising=False)
    DEFAULT_DOMAIN_DB_DIR.mkdir(parents=True, exist_ok=True)
    probe = DEFAULT_DOMAIN_DB_DIR / "_isolation_domain_force_probe.duckdb"
    probe.write_bytes(b"wipe-me")
    try:
        unlink_domain_db(probe, force=True)
        assert not probe.exists()
    finally:
        probe.unlink(missing_ok=True)


def test_seed_domains_build_refuses_existing_pilot_db_without_force(monkeypatch, tmp_path):
    """Real seed entrypoint does not unlink pilot domain DB when force is False."""
    from scripts.seed_domains import build as build_auto

    monkeypatch.delenv("FRONTLINE_ALLOW_DEFAULT_DB_RESET", raising=False)
    monkeypatch.delenv("FRONTLINE_ALLOW_DOMAIN_DB_RESET", raising=False)
    # Point domain dir at the real pilot tree for this probe only.
    monkeypatch.setenv("DOMAIN_DB_PATH", str(DEFAULT_DOMAIN_DB_DIR))
    DEFAULT_DOMAIN_DB_DIR.mkdir(parents=True, exist_ok=True)
    pack_path = DEFAULT_DOMAIN_DB_DIR / "automotive_nhtsa_probe_seed.duckdb"
    # Use a unique pack id so we never touch the real automotive_nhtsa.duckdb fixture.
    pack_id = "automotive_nhtsa_probe_seed"
    pack_path.write_bytes(b"existing-fixture")
    try:
        with pytest.raises(RuntimeError, match="refusing to delete pilot domain DB"):
            build_auto(pack_id, force=False)
        assert pack_path.is_file()
        assert pack_path.read_bytes() == b"existing-fixture"
    finally:
        pack_path.unlink(missing_ok=True)


def test_seed_domains_build_with_force_rebuilds_on_isolated_path(monkeypatch, tmp_path):
    """With force, seed rebuilds; on isolated DOMAIN_DB_PATH no allow env is required."""
    from scripts.seed_domains import build as build_auto

    domains = tmp_path / "domains"
    domains.mkdir()
    monkeypatch.setenv("DOMAIN_DB_PATH", str(domains))
    monkeypatch.delenv("FRONTLINE_ALLOW_DEFAULT_DB_RESET", raising=False)
    monkeypatch.delenv("FRONTLINE_ALLOW_DOMAIN_DB_RESET", raising=False)

    # First build creates the DB (no prior file).
    path = build_auto("automotive_nhtsa", force=False)
    assert path.is_file()
    assert path.parent == domains.resolve()
    # Second build without force still works because path is not under pilot dir.
    path2 = build_auto("automotive_nhtsa", force=False)
    assert path2.is_file()


def test_seed_finance_build_refuses_existing_pilot_db_without_force(monkeypatch):
    from scripts.seed_finance_cfpb import build as build_fin

    monkeypatch.delenv("FRONTLINE_ALLOW_DEFAULT_DB_RESET", raising=False)
    monkeypatch.delenv("FRONTLINE_ALLOW_DOMAIN_DB_RESET", raising=False)
    monkeypatch.setenv("DOMAIN_DB_PATH", str(DEFAULT_DOMAIN_DB_DIR))
    DEFAULT_DOMAIN_DB_DIR.mkdir(parents=True, exist_ok=True)
    pack_id = "finance_cfpb_probe_seed"
    pack_path = DEFAULT_DOMAIN_DB_DIR / f"{pack_id}.duckdb"
    pack_path.write_bytes(b"existing-finance")
    try:
        with pytest.raises(RuntimeError, match="refusing to delete pilot domain DB"):
            build_fin(pack_id, force=False)
        assert pack_path.is_file()
        assert pack_path.read_bytes() == b"existing-finance"
    finally:
        pack_path.unlink(missing_ok=True)


def test_pytest_isolation_redirects_domain_db_away_from_pilot():
    ddir = resolve_domain_db_dir()
    assert not is_default_pilot_domain_path(ddir)
    assert ddir != DEFAULT_DOMAIN_DB_DIR
