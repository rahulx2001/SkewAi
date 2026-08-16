"""Structural checks for Compose profiles, lockfile pins, and Docker docs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_requirements_lock_pins_required_transitives():
    lock = (REPO / "requirements-lock.txt").read_text(encoding="utf-8")
    lower = lock.lower()
    for name in ("pydantic-core", "typing-extensions", "httptools", "uvloop"):
        assert re.search(rf"(?m)^{re.escape(name)}==", lower), f"missing pin: {name}"


def test_dockerfile_and_ci_install_use_lock_constraints():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements-lock.txt" in dockerfile
    assert "-c requirements-lock.txt" in dockerfile or "-c requirements-lock.txt" in dockerfile.replace(
        "\\\n", " "
    )
    assert "docker compose --profile open up --build" in dockerfile
    assert "docker compose up --build" not in dockerfile or "--profile" in dockerfile

    # Primary run instructions must not be bare `docker compose up --build`
    run_lines = [
        ln.strip()
        for ln in dockerfile.splitlines()
        if ln.strip().startswith("#") and "docker compose" in ln
    ]
    bare = [ln for ln in run_lines if re.search(r"docker compose up --build\s*$", ln)]
    assert not bare, f"bare compose still documented: {bare}"

    workflow = (REPO / ".github/workflows/frontline.yml").read_text(encoding="utf-8")
    assert "requirements-lock.txt" in workflow
    assert "-c requirements-lock.txt" in workflow


def test_readme_documents_profile_based_compose():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "docker compose --profile open up --build" in readme
    assert "docker compose --profile hardened up --build" in readme
    # Bare default instruction without profile must not be the recommended path
    # inside a code fence as the sole compose command.
    fences = re.findall(r"```(?:bash)?\n(.*?)```", readme, flags=re.DOTALL)
    for block in fences:
        if "docker compose" not in block:
            continue
        # Every docker compose up line in quick-start fences must include --profile
        for line in block.splitlines():
            if "docker compose" in line and "up" in line and not line.strip().startswith("#"):
                assert "--profile" in line, f"compose up without profile: {line}"


def test_compose_open_and_hardened_use_distinct_host_ports():
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "FRONTLINE_PUBLISH_OPEN" in compose
    assert "FRONTLINE_PUBLISH_HARDENED" in compose
    open_m = re.search(
        r"FRONTLINE_PUBLISH_OPEN:-\$\{?[^}]*\}?|FRONTLINE_PUBLISH_OPEN:-([^}]+)\}",
        compose,
    )
    # Defaults appear as ${FRONTLINE_PUBLISH_OPEN:-127.0.0.1:8000:8000}
    open_def = re.search(r"FRONTLINE_PUBLISH_OPEN:-([^}]+)\}", compose)
    hard_def = re.search(r"FRONTLINE_PUBLISH_HARDENED:-([^}]+)\}", compose)
    assert open_def and hard_def
    open_port = open_def.group(1)
    hard_port = hard_def.group(1)
    assert open_port != hard_port
    assert "8000:8000" in open_port
    assert "8001:8000" in hard_port


def test_makefile_has_seed_domains_target():
    mk = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"(?m)^seed-domains:", mk)
    assert "scripts.seed_domains" in mk
    doc = (REPO / "scripts/seed_domains.py").read_text(encoding="utf-8")
    assert "make seed-domains" in doc
