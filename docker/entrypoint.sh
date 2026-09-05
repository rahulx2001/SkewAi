#!/bin/sh
set -e
cd /app

# Step 0.1b (audit 0.5): migrations BEFORE seeding/ingest. Ingest scripts
# refuse to run against a behind-HEAD schema, so ordering is enforced, not
# just documented.
echo "→ Applying database migrations…"
python -m scripts.migrate --db ops || echo "   (ops migrate deferred — app will apply idempotent DDL)"
for _pack in automotive_nhtsa finance_cfpb; do
  DOMAIN_PACK="$_pack" python -m scripts.migrate --db domain --pack "$_pack" || true
done

# Seed fixture warehouses if missing (idempotent enough for pilot demos).
# Also repair finance_cfpb when it was accidentally seeded with NHTSA rows
# (record_id prefix NHTSA- → all simulates abandon on the finance pack).
need_seed=0
if [ ! -f data/frontline.duckdb ] \
   || [ ! -f data/domains/automotive_nhtsa.duckdb ] \
   || [ ! -f data/domains/finance_cfpb.duckdb ]; then
  need_seed=1
fi
if [ -f data/domains/finance_cfpb.duckdb ]; then
  if ! python -c "
from src.data.warehouse import domain_con
with domain_con('finance_cfpb', read_only=True) as con:
    row = con.execute(\"SELECT record_id FROM records LIMIT 1\").fetchone()
    raise SystemExit(0 if row and str(row[0]).startswith('CFPB-') else 1)
" 2>/dev/null; then
    echo "→ finance_cfpb warehouse looks wrong or empty — re-seeding fixtures…"
    need_seed=1
  fi
fi
if [ "$need_seed" = "1" ]; then
  echo "→ Seeding fixture warehouses…"
  python -m scripts.seed_frontline_fixtures
fi

# Fail-closed when production-like (also enforced in app lifespan).
if [ "${ENV:-}" = "production" ] || [ "${ENV:-}" = "prod" ] \
   || [ "${ENV:-}" = "staging" ] || [ "${ENV:-}" = "stage" ] \
   || [ "${PILOT_HARDENED:-0}" = "1" ] || [ "${SOC2_MODE:-0}" = "1" ]; then
  if [ -z "${FRONTLINE_API_KEY:-}" ]; then
    echo "ERROR: FRONTLINE_API_KEY required when ENV=production/staging or PILOT_HARDENED/SOC2_MODE=1" >&2
    exit 1
  fi
  if [ "${#FRONTLINE_API_KEY}" -lt 32 ]; then
    echo "ERROR: FRONTLINE_API_KEY must be at least 32 bytes in hardened/production mode" >&2
    exit 1
  fi
  if [ -n "${SESSION_SECRET:-}" ] && [ "${#SESSION_SECRET}" -lt 32 ]; then
    echo "ERROR: SESSION_SECRET must be at least 32 bytes in hardened/production mode" >&2
    exit 1
  fi
  if [ "${FRONTLINE_OPEN_MODE:-0}" = "1" ]; then
    echo "ERROR: FRONTLINE_OPEN_MODE=1 is not allowed in hardened/production mode" >&2
    exit 1
  fi
  export FRONTLINE_AUTH_REQUIRED="${FRONTLINE_AUTH_REQUIRED:-1}"
  export FRONTLINE_OPEN_MODE=0
  echo "→ Hardened mode: auth required, open mode off"
fi

# Fail-closed wildcard bind (item 1): API_HOST=0.0.0.0 without explicit auth
# refuses to start, even outside hardened mode. Loopback-only dev keeps the
# intentional open escape hatch; acknowledged local pilots opt in explicitly.
case "${API_HOST:-0.0.0.0}" in
  0.0.0.0|::)
    if [ "${FRONTLINE_AUTH_REQUIRED:-0}" != "1" ] && [ "${FRONTLINE_OPEN_BIND_ACK:-0}" != "1" ]; then
      echo "ERROR: API_HOST=${API_HOST:-0.0.0.0} binds beyond loopback but FRONTLINE_AUTH_REQUIRED=1 is not set." >&2
      echo "Refusing to start open on a shared network. Set FRONTLINE_AUTH_REQUIRED=1 + a 32-byte FRONTLINE_API_KEY," >&2
      echo "bind API_HOST=127.0.0.1 for local dev, or set FRONTLINE_OPEN_BIND_ACK=1 for an acknowledged local pilot." >&2
      exit 1
    fi
    ;;
esac

echo "→ Starting Skew AI API on ${API_HOST:-0.0.0.0}:${API_PORT:-8000}"
echo "   Dashboard (if built): http://localhost:${API_PORT:-8000}/ui/"
echo "   Workers: 1 (in-process call registry — do not pass --workers / do not scale replicas)"
if [ -n "${FRONTLINE_API_KEY:-}" ]; then
  echo "   Auth: FRONTLINE_API_KEY is set"
else
  echo "   Auth: no FRONTLINE_API_KEY (open local / pilot mode — not for shared networks)"
fi

exec python -m uvicorn src.api.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
