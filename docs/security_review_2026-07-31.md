# Skew AI (`v2_ai_rca_tool`) — End-to-End Security Review

**Date:** 2026-07-31  
**Scope:** Local pilot codebase + live process on `127.0.0.1:8000` (owner-operated; no production third-party target)  
**Stack:** FastAPI + DuckDB + Vite React dashboard (`/ui/`)  
**Methods:** Bandit SAST, dependency audit (`npm audit`), secrets/pattern greps, manual auth/SSRF/SQL review, live endpoint probes  
**Out of scope:** Full pen-test of external hosts, cloud IAM, SOC2 certification, exploit weaponization  

---

## 1. Executive summary

**Overall risk (as currently running on this host): High for any network-exposed deploy; Medium for strictly local single-user pilot.**

The API correctly *implements* shared-secret auth (`require_api_key` on major routers) and SSRF guards on outbound webhooks, and uses constant-time key compare. However:

1. **Default is open mode** when `FRONTLINE_API_KEY` is unset (`auth_required: false` on `/health`). All `Depends(require_api_key)` become no-ops.
2. Live probe confirmed **unauthenticated** access to cases, connector status, **DSR delete**, and **admin session minting**.
3. **RBAC is not enforced on routes** (`require_perm` / `get_role` are unused outside `rbac.py`). Client can request `role=admin` on session issue.
4. **Session HMAC falls back to `"dev-only"`** when no API key / `SESSION_SECRET` is set — forgeable sessions.
5. **Marketplace `source_path`** can copy arbitrary local directories into `domains/` when the install API is reachable.

This matches a **single-tenant pilot** design, not multi-tenant SaaS. Shipping to a shared network without locking auth is the primary risk.

| Severity | Count |
|----------|------:|
| Critical | 1 |
| High     | 4 |
| Medium   | 5 |
| Low / Info | 4 |

---

## 2. Attack surface map

| Surface | Path / mechanism | Auth dependency |
|---------|------------------|-----------------|
| REST ops | `/api/frontline/*`, `/api/v3/*`, enterprise, platform56 | `require_api_key` (no-op if open) |
| Interactions | `/api/interactions/*`, `/ws/*` | API key / WS auth frame |
| Packs | `GET /api/packs` **no** router-level key; `PUT active` has key | Partial |
| Static UI | `/ui/*` | Public static files |
| Health / root | `/`, `/health` | Public (by design) |
| Outbound | Alert + connector webhooks | `url_guard` |
| Browser | localStorage `frontline_api_key` | XSS → key theft |

---

## 3. Findings

### FIND-001 — Critical  
**Default open mode exposes full ops API without credentials**

- **Where:** `src/api/auth.py` (`auth_required` / `is_open_mode`); live `/health` → `"auth_required": false`
- **Evidence (live):**
  - `GET /api/frontline/cases?limit=1` → **200** (no key)
  - `GET /api/frontline/connectors/status` → **200**
  - `DELETE /api/frontline/dsr/{id}` → **200**
  - `POST /api/frontline/auth/session` with `{"role":"admin"}` → **200** + signed token
- **Impact:** Anyone who can reach the port can read/modify cases, run simulate/platform jobs, export/delete DSR data, reconfigure connector webhooks (SSRF constrained but still outbound), switch packs, mint admin sessions.
- **Remediation:**
  1. Production compose/docs: **require** `FRONTLINE_AUTH_REQUIRED=1` + strong `FRONTLINE_API_KEY`.
  2. Prefer **fail-closed default** when `ENV=production` / `PILOT_HARDENED=1`.
  3. Bind uvicorn to `127.0.0.1` only for demos; never `0.0.0.0` without auth + TLS.
- **CWE:** CWE-306 (Missing Authentication for Critical Function)  
- **CVSS (exposed network):** ~9.0  

---

### FIND-002 — High  
**Unauthenticated (open mode) admin session issuance + weak signing secret**

- **Where:**  
  - `src/api/routes/platform56.py` `POST /auth/session` → `issue_session(subject, role)`  
  - `src/api/rbac.py` `_secret()` → `FRONTLINE_API_KEY or SESSION_SECRET or "dev-only"`
- **Evidence:**  
  `POST /api/frontline/auth/session` body `{"subject":"att","role":"admin"}` returned a valid token with `"role":"admin"` while `auth_required` was false. Signature uses fallback `"dev-only"` when no secrets configured.
- **Impact:** Forged or freely minted “admin” sessions; any later code that trusts sessions inherits full role.
- **Remediation:**
  1. Never accept arbitrary `role` from body without authz (map roles server-side; only admin can mint elevated sessions).
  2. Require non-default `SESSION_SECRET` (≥32 bytes) in non-open mode; refuse to start if missing when hardened.
  3. Disable `/auth/session` in open mode or force open mode to issue only `agent` with short TTL.
- **CWE:** CWE-798, CWE-287  

---

### FIND-003 — High  
**RBAC is decorative — client role header / no route-level `require_perm`**

- **Where:** `src/api/rbac.py` (`role_from_headers` trusts `X-Frontline-Role`); **zero** call sites of `require_perm` / `get_role` under `src/api/routes/`
- **Impact:** Even with API key, a holder of the shared key can assert any role; permission matrix does not gate sensitive actions (DSR delete, pack edit, connector config, simulate).
- **Remediation:**
  1. Wire `Depends(get_role)` + `require_perm(...)` on write/delete/admin routes.
  2. Only accept roles from signed sessions (or IdP claims), not free `X-Frontline-Role` alone.
  3. Treat shared API key as **service** credential with fixed role, not multi-user RBAC.
- **CWE:** CWE-863  

---

### FIND-004 — High  
**DSR export/delete available whenever API is open**

- **Where:** `src/api/routes/frontline.py` `GET/DELETE /api/frontline/dsr/{interaction_id}`; `src/frontline/dsr.py`
- **Evidence:** `DELETE /api/frontline/dsr/nonexistent_id` → **200** without credentials (open mode).
- **Impact:** Privacy/regulatory failure: bulk personal/ops data export or hard-delete if interaction IDs are guessed/leaked (IDs are semi-predictable ULID-like).
- **Remediation:** Always require auth for DSR; add secondary confirmation token / admin role; rate-limit deletes; audit-log every DSR call; do not return generic 200 without auth.
- **CWE:** CWE-284, CWE-359  

---

### FIND-005 — High  
**Marketplace install accepts arbitrary local `source_path` (path copy)**

- **Where:** `src/domains/marketplace.py` `pack_install(..., source_path=...)`; exposed via `POST /api/frontline/marketplace/install` (`platform56.py`)
- **Description:** If `source_path` is a directory, `shutil.copytree` copies it into `domains/{pack_id}` with **no** root jail / allowlist.
- **Impact:** Authenticated (or open-mode) caller can read/copy sensitive local dirs the process can access into the app tree (information disclosure / supply-chain of malicious pack.yaml).
- **Remediation:** Allow only paths under a configured packages root; resolve + `relative_to(allow_root)`; reject `..`; disable `source_path` in production.
- **CWE:** CWE-22  

---

### FIND-006 — Medium  
**API key accepted via query string**

- **Where:** `src/api/auth.py` `require_api_key` reads `request.query_params.get("api_key")`; WS query fallback documented as deprecated
- **Impact:** Keys leak into access logs, browser history, Referer, reverse proxies.
- **Remediation:** Reject query `api_key` when `FRONTLINE_AUTH_REQUIRED=1`; headers/first-message only.
- **CWE:** CWE-598  

---

### FIND-007 — Medium  
**Browser stores API key in `localStorage`**

- **Where:** `dashboard/src/apiAuth.js` (`frontline_api_key`); Settings save path
- **Impact:** Any future XSS or malicious extension can exfiltrate the pilot key. No `dangerouslySetInnerHTML` found (good).
- **Remediation:** Prefer httpOnly session cookie set by backend after key exchange; or sessionStorage + short TTL; CSP headers on `/ui/`.
- **CWE:** CWE-922  

---

### FIND-008 — Medium  
**Rate limiting too loose for abuse-sensitive actions**

- **Where:** `src/api/limiter.py` default `1000 per hour`; some interaction routes `30/minute`
- **Impact:** In open or stolen-key scenarios, simulate/DSR/connector replay can flood DB, disk outbox, or outbound webhooks.
- **Remediation:** Tight limits on `/simulate`, `/dsr`, connector config/replay, marketplace install; per-key limits not only IP.
- **CWE:** CWE-770  

---

### FIND-009 — Medium  
**Dynamic SQL construction (Bandit B608) — currently low exploitability**

- **Where:** `src/frontline/dsr.py` (table/col from **fixed tuples**), `src/frontline/ops.py` (column names from fixed field list), warehouse prune/tenant helpers
- **Impact:** Values are parameterized (`?`); identifiers are mostly constants. Residual risk if future callers pass user-controlled table/column names into the same patterns.
- **Remediation:** Centralize identifier allowlists; assert identifiers with `^[a-z_]+$`; keep values bound.
- **CWE:** CWE-89 (latent)  

---

### FIND-010 — Medium  
**CORS allows credentials; origin list env-driven**

- **Where:** `src/api/main.py` `CORSMiddleware(allow_credentials=True, allow_origins=_cors_origins())`
- **Defaults:** localhost ports only (good).
- **Impact:** Mis-set `CORS_ALLOW_ORIGINS=*` is invalid with credentials in browsers, but a typo allowing attacker origin + credentials is risky if cookies are introduced later.
- **Remediation:** Validate origins; never allow `*` with credentials; document production origins explicitly.
- **CWE:** CWE-942  

---

### FIND-011 — Low  
**npm: esbuild/vite advisory (dev server)**

- **Where:** `dashboard` `npm audit` — esbuild ≤0.24.2 / vite ≤6.4.2 moderate/high (dev request smuggling to Vite server)
- **Impact:** Affects `vite dev` more than production static `/ui` served by FastAPI.
- **Remediation:** Upgrade Vite when ready; do not expose Vite dev server on untrusted networks.
- **References:** GHSA-67mh-4wv8-2f99  

---

### FIND-012 — Low  
**Information disclosure via public meta endpoints**

- **Where:** `/`, `/health` expose `auth_required`, `active_pack`, worker mode, feature flags
- **Impact:** Aids recon; acceptable for pilot; reduce in hardened deploys.
- **Remediation:** Strip detail when unauthenticated; keep minimal liveness only.

---

### FIND-013 — Info  
**Positive controls observed**

- Constant-time compare for API keys (`secrets.compare_digest`)
- Outbound webhook SSRF guard (`src/security/url_guard.py`) used by alerts + connectors
- Case status updates validate against allowlist
- DSR SQL **values** parameterized; table names from constants
- No `dangerouslySetInnerHTML` / `eval` / `pickle` / `shell=True` in app source
- No live cloud secrets found in repo (only test fixtures / `.env.example` empty placeholders)
- Router-level `Depends(require_api_key)` on frontline, enterprise, platform56, interactions (works when key configured)

---

## 4. End-to-end risk narrative

```
[Browser /ui] --open--> [FastAPI]
                          |
          open mode? --yes--> full API (FIND-001)
                          |
          POST /auth/session role=admin --> signed token (FIND-002)
                          |
          DELETE /dsr/{id} --> hard delete ops rows (FIND-004)
                          |
          PUT connectors/config --> webhook (SSRF-guarded) + outbox
                          |
          POST marketplace/install source_path=/... --> copy into domains/ (FIND-005)
```

With **`FRONTLINE_API_KEY` set and open mode off**, FIND-001 collapses to “shared secret = full power” (still single principal; FIND-003 RBAC remains weak).

---

## 5. Prioritized recommendations

| Priority | Action |
|----------|--------|
| P0 | Never expose port 8000 beyond localhost without `FRONTLINE_AUTH_REQUIRED=1` + strong key |
| P0 | Document/compose fail-closed production profile |
| P1 | Lock `/auth/session` role minting; remove `"dev-only"` secret fallback in hardened mode |
| P1 | Require auth always for DSR export/delete; admin-only |
| P1 | Jail/disable marketplace `source_path` |
| P2 | Enforce `require_perm` on write/delete routes or drop fake RBAC |
| P2 | Disable query-string API keys in production |
| P2 | Tighten rate limits on simulate/DSR/connector |
| P3 | CSP + move API key out of localStorage |
| P3 | Upgrade Vite/esbuild when convenient |

---

## 6. Hardened pilot checklist (minimum)

```bash
export FRONTLINE_AUTH_REQUIRED=1
export FRONTLINE_API_KEY="$(openssl rand -hex 32)"
export SESSION_SECRET="$(openssl rand -hex 32)"
export FRONTLINE_OPEN_MODE=0
# bind loopback unless behind TLS reverse proxy
uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Verify:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/frontline/cases
# expect 401
curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: $FRONTLINE_API_KEY" \
  http://127.0.0.1:8000/api/frontline/cases
# expect 200
```

---

## 7. Tooling notes

| Tool | Result |
|------|--------|
| Bandit | 0 High; 14 Medium (mostly B608 SQL strings + false-positive host lists) |
| npm audit | 2 issues (esbuild/vite dev-related) |
| Secrets grep | No production secrets committed |
| Live probes | Open-mode unauthenticated access **confirmed** |

---

## 8. Conclusion

The product’s security **design for a locked pilot is partially present** (API key dependency, SSRF guard, compare_digest). The **runtime default and RBAC gaps** make the current end-to-end posture unsafe for any shared or internet-facing host. Treat FIND-001–005 as release blockers before non-local deployment; the rest as hardening for enterprise readiness.

---

## Remediation status (implementer)

| Finding | Status |
|---------|--------|
| FIND-001 | Mitigated for DSR always-auth; hardened env fails closed for protected routers |
| FIND-002 | Fixed — open clamps agent; no free admin; no dev-only when auth required |
| FIND-003 | Partial — bare header cannot elevate; service key = admin; DSR/marketplace perms |
| FIND-004 | Fixed — DSR strict auth + delete perm |
| FIND-005 | Fixed — path jail + disable source_path when auth required |
| FIND-006 | Partial — query key rejected when AUTH_REQUIRED / on DSR strict routes |

See `tests/frontline/test_security_harden.py` and `.env.example`.
