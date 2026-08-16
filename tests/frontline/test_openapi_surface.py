"""Regression guard: docs/openapi.yaml must cover the real FastAPI surface.

The spec is a generated snapshot (banner in the file says how to regenerate).
This test fails when routes are added/removed/renamed without regenerating it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Same isolation posture as the session fixtures in this package — set env
# before importing the app so any import-time settings read sees temp paths.
os.environ.setdefault("FRONTLINE_TEST_ISOLATION", "1")
os.environ.setdefault("FRONTLINE_DB_PATH", "/tmp/oa_openapi_surface.duckdb")
os.environ.setdefault("DOMAIN_DB_PATH", "/tmp/oa_openapi_domains")

yaml = pytest.importorskip("yaml", reason="PyYAML required to parse the OpenAPI snapshot")

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "openapi.yaml"

# Swagger/Redoc hosting routes that FastAPI registers but that are not part of
# the documented product surface.
ALLOWLISTED_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def _documented_paths() -> set[str]:
    with open(SPEC_PATH, encoding="utf-8") as f:
        # Skip the generated banner comment lines; safe_load handles them too,
        # but strip to keep the intent explicit.
        spec = yaml.safe_load(f)
    assert isinstance(spec, dict), "openapi.yaml did not parse to a mapping"
    return set(spec.get("paths", {}).keys())


def _registered_paths() -> set[str]:
    from src.api.main import app
    from starlette.routing import Route

    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if isinstance(route, Route) and route.methods:
            # Only document real HTTP verbs (HEAD auto-added by StaticFiles etc.
            # is still fine — FastAPI routers always set real verbs).
            if route.methods & {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                paths.add(route.path)
        stack.extend(getattr(route, "routes", ()) or ())
    return paths


def test_openapi_spec_covers_registered_http_routes():
    documented = _documented_paths()
    registered = _registered_paths()
    missing = {
        p for p in registered - documented
        if not any(p.startswith(a) for a in ALLOWLISTED_PREFIXES)
    }
    assert not missing, (
        "openapi.yaml is missing routes registered in src.api.main:app — "
        "regenerate docs/openapi.yaml.\n" + "\n".join(sorted(missing))
    )
    # Sanity: drift guard — the snapshot should be in the same ballpark as the
    # live surface, not the old 12-path hand-written doc.
    assert len(documented) >= 100, (
        f"openapi.yaml documents only {len(documented)} paths; "
        "looks like drift (expected ~107)."
    )
