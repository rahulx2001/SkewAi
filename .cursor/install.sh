#!/usr/bin/env bash
# Idempotent Cloud Agent setup for Skew AI (Python API + Vite dashboard + DuckDB fixtures).
# Safe to re-run: venv creation, pip, npm ci, and fixture seeding all converge.
set -euo pipefail

cd "$(dirname "$0")/.."

# --- System package: python venv support is missing on the default base image ---
if ! dpkg -s python3.12-venv >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3.12-venv
fi

# --- Python backend (FastAPI + agents + DuckDB) ---
python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip -q
pip install -r requirements.txt -c requirements-lock.txt

# --- Dashboard (Vite production build; served by the API at /ui/) ---
(
  cd dashboard
  npm ci
  npm run build
  test -f dist/index.html
)

# --- Seed fixture warehouses: ops DuckDB + both demo domain packs ---
# Deterministic offline fixtures (10 records / 2 advisories / 3 clusters each).
make frontline-db

echo "✓ Skew AI environment ready (venv + dashboard/dist + seeded DuckDB fixtures)."
