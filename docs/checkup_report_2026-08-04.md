# Skew AI thorough checkup report (re-verify)

**Date (UTC):** 2026-08-04T14:32Z  
**Scope:** Live process, API, UI shell, domain data, security tests, residual risks  
**Mode observed at probe time:** **Open local pilot** (`FRONTLINE_OPEN_MODE=1`, `auth_required: false`, `enterprise_readiness: single_tenant_pilot_open`)

**Evidence:** `checkup-live.log`, `checkup-security-tests.log`, `checkup-data.log` (same directory)

---

## Working now

| Surface | Evidence |
|---------|----------|
| Live process `127.0.0.1:8000` | Python PID listening (TCP localhost:irdmi / 8000) |
| Health | HTTP **200**, `status: ok`, `db_ok: true`, `pack_ok: true`, pack `automotive_nhtsa` |
| Auth mode | `auth_required: false`, `production_like: false`, root `auth.required: false` |
| Cases / packs (no API key) | HTTP **200**; cases JSON includes real rows |
| UI shell | `GET /ui/` HTTP **200**, size 873 bytes |
| Live API simulate | `POST /simulate?count=1` → `completed:1`, `cases_created:1`, HTTP 200 |
| Finance seed | first `record_id` = `CFPB-400001`, n=10 |
| Automotive seed | first `NHTSA-100001`, n=10 |
| DSR without key (open mode) | HTTP **401** (strict privacy route; no key configured) |
| Drain without key | HTTP **401** (strict / privileged) |
| No app HTTP 402 | No `status_code=402` in `src/` or dashboard app code (only third-party status phrase tables in node_modules) |
| Security suite | **50 passed**, 0 failed, 0 errors (this run, with live server up) |

---

## Problems (what is wrong / what still bites)

### P1 — Prior “402” user reports were **401 Unauthorized** (operational)

| Field | Detail |
|-------|--------|
| **Severity** | **High** when process is hardened; **not active** for ops GETs under current open mode |
| **What** | App does not emit payment **402**. Hardened mode returns **401** if Settings has no/wrong `frontline_api_key`. |
| **Evidence** | Live open mode: cases 200 without key. DSR still 401. Historical: hardened cases without key → 401. |
| **Class** | **Operational** (env + localStorage key) |
| **Current** | Open mode → main dashboard APIs work unauthenticated |

### P2 — Open mode is unsafe off localhost (operational)

| Field | Detail |
|-------|--------|
| **Severity** | **High** if port reachable beyond this machine; **acceptable** for local demo |
| **What** | Full ops read/write surface (cases, packs, simulate) without API key |
| **Evidence** | `auth_required: false`; unauthenticated cases/packs 200; env `FRONTLINE_OPEN_MODE=1` |
| **Class** | **Operational / intentional local default** |

### P3 — DuckDB single-writer lock (architecture / ops)

| Field | Detail |
|-------|--------|
| **Severity** | **Medium** |
| **What** | One writer on `data/frontline.duckdb`. Live uvicorn + parallel pytest/CLI can conflict |
| **Evidence** | Prior session: security setup ERROR + CLI simulate `Could not set lock`. **This re-verify:** security suite fully green (50 passed) with server up — lock risk remains intermittent |
| **Class** | **Architecture / ops** (`single_worker: true` in health) |
| **Impact** | Flaky local tests/CLI when concurrent; in-process API simulate OK |

### P4 — Security suite can flake with live server (ops)

| Field | Detail |
|-------|--------|
| **Severity** | **Medium** (hygiene) |
| **What** | Prior probe: 49 pass + 1 DuckDB setup error; this probe: **50 pass** |
| **Evidence** | `checkup-security-tests.log` this run: 50 passed |
| **Class** | **Operational** — stop uvicorn for clean CI, or isolate test DB paths |

### P5 — Stale browser API key UX (low–medium)

| Field | Detail |
|-------|--------|
| **Severity** | **Low–Medium** |
| **What** | `localStorage` key `frontline_api_key` persists across restarts; wrong key under hardened mode → 401 panels |
| **Evidence** | `dashboard/src/apiAuth.js` `API_KEY_STORAGE = "frontline_api_key"` |
| **Class** | **Operational / UX** |

### P6 — Empty queue before traffic (info)

| Field | Detail |
|-------|--------|
| **Severity** | **Info** |
| **What** | Zero cases is normal until simulate/contacts; not a crash |
| **Evidence** | After live simulate, cases present |
| **Class** | **Expected empty state** |

### P7 — Possible orphan active interactions (low)

| Field | Detail |
|-------|--------|
| **Severity** | **Low** |
| **What** | Wallboard may show active sessions without completion (abandoned voice/text) |
| **Class** | **Runtime state** |

---

## Residual deferred (non-goals / not certified)

| Item | Honest status |
|------|----------------|
| SOC 2 Type II | **Not certified** — engineering baseline only |
| OIDC + MFA multi-user | **Not implemented** as product SSO |
| Multi-tenant isolation | **Incomplete** — single-tenant pilot |
| HA / encryption at rest | DuckDB single file, single worker |
| npm/vite GHSA | Dev server dependency; not production static `/ui` |

**Not claimed:** SOC 2 Type II report, complete multi-tenant OIDC, full HA.

---

## Working vs broken (this probe)

| Path | Status |
|------|--------|
| Live API open mode | **Working** |
| `/ui/` shell | **Working** (HTTP 200) |
| 401 class for normal ops GETs | **Not broken now** (open mode) |
| 401 class for DSR/drain without key | **Expected / working as designed** |
| Hardened UX without key | **Would break** if mode flipped again |
| Security tests this run | **Working** (50/50) |

---

## If symptoms return

1. `GET /health` → read `auth_required`  
2. If `true`: paste matching `FRONTLINE_API_KEY` in Settings, or use open mode for local only  
3. Clear `localStorage.frontline_api_key` on mismatch  
4. Stop uvicorn before full security-test if DuckDB lock errors appear  

## URLs

- Dashboard: http://127.0.0.1:8000/ui/  
- Health: http://127.0.0.1:8000/health  
