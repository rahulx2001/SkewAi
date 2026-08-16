# Security re-review (pass 2) — every residual flaw

**Product:** Skew AI (`v2_ai_rca_tool`)  
**Date:** 2026-07-31  
**Method:** Manual auth/RBAC/path/SSRF review, adversarial TestClient probes, Bandit (88 findings), npm audit, live `:8000` probe, security test suite (24 harden/soc2 tests green in source).  
**Scope:** Current **source tree** + **running process** behavior.  
**Honesty:** Exhaustive for this pass; not a formal pen test. No claim of infinite completeness.

---

## Executive summary

| Area | Status |
|------|--------|
| Hardening **in source** (DSR strict, fail-closed startup, session clamp, marketplace path jail, headers, audit log, query-key reject when `AUTH_REQUIRED`) | Present; **24** harden/SOC baseline tests pass |
| **Live** `127.0.0.1:8000` | Still **open mode**, **stale process** (health lacks `security.soc2_engineering_baseline`; unauthenticated DSR delete returns 200) |
| Residual High (in hardened source) | Shared key = admin; pack disk edit; ops drain; privileged side-effect APIs |
| Bandit | 0 High / 14 Medium / 74 Low |
| npm | esbuild/vite GHSA (dev server) |
| SOC 2 Type II | **Still not** certifiable from code alone |

**Risk if source is run with hardened env and process restarted:** Medium (single-tenant pilot).  
**Risk of current live process or default open Docker on a shared network:** Critical / High.

### Counts (this pass)

| Severity | Count |
|----------|------:|
| Critical | 1 (operational: live/open exposure) |
| High | 6 |
| Medium | 22 |
| Low | 28 |
| Info | 14 |
| **Total** | **~71** |

---

## What improved since inventory v1 (source only)

| Item | Source status |
|------|----------------|
| DSR always `require_api_key_strict` | Fixed — open mode returns **401** under TestClient |
| Query API key rejected when `FRONTLINE_AUTH_REQUIRED=1` | Fixed on HTTP `require_api_key` |
| Open-mode session never elevates | Fixed (role forced to `agent`) |
| Bare `X-Frontline-Role` cannot elevate | Fixed |
| `dev-only` session secret refused when auth required | Fixed |
| Marketplace `source_path` jail + disabled under auth unless `PACK_INSTALL_ALLOW_SOURCE` | Fixed |
| Production-like startup fail-closed | Fixed (`harden.validate_startup_security`) |
| Security headers + conditional HSTS | Fixed |
| SSRF guards on connectors/alerts (literal private IPs + DNS check) | Mostly fixed; edge cases remain |
| Packs router auth-gated | Fixed |
| Security audit JSONL | Present |

**Not fixed (still open in source):** H1–H4 class issues, author spoofing, tenant spoofing, pack edit default `write_disk=True`, drain without admin gate, Docker bind `0.0.0.0`, connector 500 on bad URL, cohort `group_field` interpolation, localStorage key, OIDC stub only, etc.

---

## Critical

### C1 — Live process is open + stale (operational)
- **Where:** Running `uvicorn` on `127.0.0.1:8000` (not reloaded after harden)
- **Evidence (2026-07-31 re-probe):**
  - `GET /health` → `auth_required: false`, no `security.soc2_engineering_baseline` block (old shape)
  - `DELETE /api/frontline/dsr/x` → **200** `{"ok":true,...}` **without credentials**
  - `GET /api/frontline/cases` → **200** without credentials
- **Impact:** Full unauthenticated ops surface on whatever network can reach the port
- **Remediation:** Kill and restart with hardened env (`make run-hardened` or `ENV=production FRONTLINE_AUTH_REQUIRED=1 FRONTLINE_API_KEY=… SESSION_SECRET=…`). Verify: cases/DSR return 401 without key.
- **CWE:** CWE-306 / CWE-1188

---

## High

### H1 — Shared API key maps to full admin principal
- **Where:** `src/api/rbac.py` `role_from_headers` — when auth required and no session, returns `"admin"`
- **Evidence:** With only `X-API-Key`, `POST /auth/session` mints **admin** token; DSR delete permitted; marketplace install with source_path permitted if allow flag set
- **Impact:** One leaked key = every privileged action (DSR delete, pack edit, drain, connectors, jobs, activate pack)
- **Remediation:** Default service key to `agent` or scoped `service` role; require signed admin session (or OIDC) for elevated perms; split keys by capability
- **CWE:** CWE-269

### H2 — Pack editor writes domain pack files by default
- **Where:** `POST /api/frontline/packs/{pack_id}/edit` → `apply_pack_edits(..., write_disk=True)` default; no `require_perm`
- **Impact:** Authenticated (or open-mode) caller rewrites `pack.yaml` (safety lexicon, slots, advisory SQL) → logic/safety bypass
- **Remediation:** Admin-only; default `dry_run=True` / `write_disk=False`; path-safe `pack_id`; audit every write; disable disk write unless `PACK_EDIT_WRITE_DISK=1`
- **CWE:** CWE-732

### H3 — Ops drain is any-auth (or open) callable
- **Where:** `POST /api/frontline/ops/drain` — no extra perm
- **Evidence:** TestClient open mode and hardened key both return `{"draining":true,...}`
- **Impact:** Availability attack — reject new contacts
- **Remediation:** Admin-only + confirm token + audit; optional strict auth always
- **CWE:** CWE-862

### H4 — Privileged side-effect APIs under shared key / open mode
- **Where:**  
  - `POST .../channels/email/ingest`  
  - `POST .../biometrics/match`  
  - `POST .../jobs` + `.../jobs/run-next` (runs `rebuild_clusters` etc.)  
  - `PUT /api/packs/active`  
  - `PUT .../connectors/config`  
  - `POST .../connectors/export/{case_id}`  
  - `POST .../subscriptions/tick`  
  - `POST .../clusters/rebuild`  
  - `POST .../digest/run`
- **Impact:** Create contacts, mutate pack activation, fire jobs, change webhooks, export cases — no per-action RBAC
- **Remediation:** Map each to least privilege; admin for destructive; rate limits; audit
- **CWE:** CWE-862

### H5 — Default open mode if process not production-like
- **Where:** `auth_required()` when no key / no `AUTH_REQUIRED` / not production-like
- **Impact:** Misconfigured deploy = full open API (same class as C1 for any new process)
- **Mitigation present:** `ENV=production|staging` / `PILOT_HARDENED` / `SOC2_MODE` force auth + startup raise
- **Remediation:** Prefer fail-closed default in Docker image; require explicit `FRONTLINE_OPEN_MODE=1` for demos
- **CWE:** CWE-1188

### H6 — Connector config SSRF rejection crashes as 500 (and proves guard path)
- **Where:** `set_connector_config` → `validate_outbound_url` raises `ValueError`; route does not catch → **HTTP 500**
- **Evidence:** `PUT /connectors/config` with `https://169.254.169.254/` → 500 Internal Server Error
- **Impact:** DoS-ish error path; may leak stack in non-production; indicates incomplete error handling on security boundary
- **Remediation:** Catch `ValueError` → 400 with stable code `url_blocked`
- **CWE:** CWE-755 / CWE-209

---

## Medium

### M1 — API key still accepted via query when not `AUTH_REQUIRED`
- **Where:** `require_api_key` + WS query fallback
- **Impact:** Logs, Referer, browser history, proxy access logs
- **Remediation:** Always reject query keys outside hermetic tests (`FRONTLINE_ALLOW_QUERY_KEY=1` opt-in)

### M2 — Browser `localStorage` holds API key
- **Where:** `dashboard/src/apiAuth.js`, `Settings.jsx`
- **Impact:** Any XSS or malicious extension steals full admin key (under H1)
- **Remediation:** httpOnly Secure cookie + OIDC

### M3 — HMAC session sig truncated to 32 hex (128-bit)
- **Where:** `rbac.py` `hexdigest()[:32]`
- **Impact:** Nonstandard; adequate but weaker than full HMAC-SHA256
- **Remediation:** Full digest or JWT (PyJWT) with `kid` rotation

### M4 — Session body is cleartext JSON `|` signature
- **Where:** token format
- **Impact:** Role/sub visible; bearer theft = full role until exp
- **Remediation:** Opaque server-side sessions or encrypted cookie

### M5 — No multi-tenant authorization (IDOR by design)
- **Where:** All case/interaction IDs with one key
- **Impact:** If sold as multi-tenant SaaS, total cross-customer access
- **Remediation:** Tenant id bound to credential on every query

### M6 — Client-controlled `author` / `requested_by` / `reviewer`
- **Where:** case notes/patch, investigation patch, four-eyes approvals
- **Impact:** Audit trail spoofing; four-eyes identity is free-form strings (only “≠ requester” check)
- **Evidence:** Approval as `alice`, approve as `bob` both client-supplied with same API key
- **Remediation:** Derive identity from session/OIDC only

### M7 — Client-controlled `tenant_id` on usage metering
- **Where:** `GET/POST /usage?tenant_id=`
- **Impact:** Metering fraud / wrong billing stats
- **Remediation:** Bind tenant to credential; ignore client field

### M8 — User-controlled SQL identifier: `group_field`
- **Where:** `analytics.cohort_analysis` → `CAST({field} AS VARCHAR)` from query param
- **Evidence:** `group_field=1` executes; weird payloads fail soft to `[]` (exception swallowed)
- **Impact:** Identifier injection surface; today mostly DoS/empty results, high if DuckDB allows richer expressions later
- **Remediation:** Allowlist `entity_1|entity_2|entity_3|category|region` only

### M9 — Dynamic SQL table/column f-strings (Bandit B608 ×12)
- **Where:** `dsr.py`, `prune.py`, `ops.py`, `analytics.py`, `insights.py`, `copilot.py`, `retrievers.py`, `warehouse.py`, `tenant.py`
- **Impact:** Low if constants only; catastrophic if user input ever flows in
- **Remediation:** Central `safe_ident()` allowlist helper

### M10 — Prometheus metrics behind only shared API key
- **Where:** `GET /api/frontline/metrics/prometheus`
- **Impact:** Open mode = public; hardened = any key holder
- **Remediation:** Separate scrape secret or network policy

### M11 — CORS `allow_credentials=True` + env origins
- **Where:** `main.py`
- **Impact:** Mis-set `CORS_ALLOW_ORIGINS=*` or attacker origin if cookies added later
- **Remediation:** Reject `*`; validate absolute origins; no credentials with wildcard

### M12 — Docker Compose publishes `0.0.0.0:8000`
- **Where:** `docker-compose.yml` default + hardened profiles; entrypoint `API_HOST=0.0.0.0`
- **Impact:** LAN exposure of pilot
- **Remediation:** Default `127.0.0.1:8000:8000`; document host bind

### M13 — `urllib.request.urlopen` for LLM (Bandit B310)
- **Where:** `src/ai/provider.py:127` + `OPENAI_BASE_URL` env
- **Impact:** If base URL env compromised → SSRF to internal network with API key bearer
- **Remediation:** HTTPS + host allowlist for base URL

### M14 — Rate limiter in-memory only
- **Where:** `src/api/limiter.py`
- **Impact:** Multi-worker bypass; restart resets
- **Remediation:** Redis / edge limiter

### M15 — `SECURITY_AUDIT_LOG_PATH` unrestricted
- **Where:** `audit_log._path()`
- **Evidence:** Env `/tmp/evil_audit.jsonl` accepted
- **Impact:** Write JSONL outside intended tree if env compromised
- **Remediation:** Jail under `data/` or `/var/log/skewai`

### M16 — Incomplete tenant enforcement
- **Where:** `ops/tenant.py` vs most routes ignoring it
- **Impact:** Multi-tenant not real
- **Remediation:** Enforce on all reads/writes or delete pretence

### M17 — No encryption at rest for DuckDB
- **Where:** `data/*.duckdb`
- **Impact:** Disk theft → full dump
- **Remediation:** Volume encryption / managed Postgres TDE

### M18 — DNS rebinding / TOCTOU after URL validate
- **Where:** `url_guard` resolves once at config/dispatch; no pin of IP for request
- **Impact:** Classic webhook SSRF class if attacker controls DNS TTL
- **Remediation:** Connect to resolved IP with host header / use IP pin libraries

### M19 — OpenAPI `/docs` and `/openapi.json` public
- **Where:** FastAPI defaults
- **Impact:** Full attack surface map without auth
- **Remediation:** Disable in production or gate behind auth

### M20 — Root `/` auth flag can disagree with real policy
- **Where:** `root()` uses `bool(FRONTLINE_API_KEY)` not `auth_required()`
- **Impact:** Clients mis-detect auth when production-like forces auth without key (edge); or key set but open mode forced
- **Remediation:** Call `auth_required()` consistently

### M21 — Pack activate without elevated role
- **Where:** `PUT /api/packs/active`
- **Impact:** Flip active domain pack (behavior change for all new contacts)
- **Remediation:** Admin + audit (audit present; RBAC missing)

### M22 — Job queue free-form `job_type` + echo default handler
- **Where:** `jobs/queue.py` `_default_handler` returns `echo: payload` for unknown types
- **Impact:** Unexpected handlers if registry grows; storage of arbitrary payloads
- **Remediation:** Allowlist job types at enqueue

---

## Low

### L1 — HSTS only when production-like (intentional)
Residual: production-like over plain HTTP can confuse browsers after first HTTPS visit.

### L2 — CSP allows `'unsafe-inline'` styles + Google Fonts CDN
Weakens XSS mitigation; third-party font privacy.

### L3 — npm esbuild ≤0.24.2 / vite GHSA (dev server request forgery)
Production static `/ui` not affected; `vite dev` is.

### L4 — Information disclosure via `/` and `/health`
Pack id, feature flags, auth mode, readiness, db errors in `detail`.

### L5 — Error messages / exception strings to clients
Many `detail=str(e)`; audit 404 includes full report path; pack list errors include exception text.

### L6 — Interaction/case IDs are ULID-like (enumerable if auth weak)
Mitigated by auth + rate limits when hardened.

### L7 — No progressive backoff / lockout on failed API keys
Online guessing if weak key (16-char minimum only in production-like).

### L8 — WebSocket may accept then auth (first-message path)
Brief unauthenticated socket; failed auth should close 1008 (verify all paths).

### L9 — Session TTL 3600s (900s open); no revocation list
Stolen token valid until exp.

### L10 — `FRONTLINE_BOOTSTRAP_ADMIN` re-enables free admin mint
Mis-set env undoes session clamp for admin.

### L11 — Audit log not tamper-evident
Local root can edit JSONL; no hash chain / remote append-only.

### L12 — No CSRF tokens
OK for pure header API key; required when moving to cookies.

### L13 — Permissions-Policy allows microphone self
Intentional for voice.

### L14 — Reports/data dirs may have weak host FS perms
Local user read of DuckDB/reports.

### L15 — Subscriptions `target` not validated as email/URL
Spam/abuse sink if open or key leaked.

### L16 — Biometrics endpoint is pilot integrity theater
Free-form features; not real identity proof.

### L17 — `pack_dir(pack_id)` does not jail `pack_id`
Function allows `../` escape under `domains/`; HTTP path routing currently 404s encoded traversal — defense in depth missing at function layer.

### L18 — `random` in simulator (not CSPRNG)
Fine for sim; never reuse for tokens.

### L19 — Prompt-injection filters incomplete / false positives
- Bypass: `Ignore\nall instructions` (newline breaks pattern)
- False positive: normal text containing “system prompt”
- `DROP TABLE` without SQL pattern prefix allowed

### L20 — PII redaction incomplete
Unhyphenated SSN `123456789` not redacted; short phones; DOB not covered; `find_pii` misses cards already redacted by `redact_pii`.

### L21 — Four-eyes not enforced on actual high-impact mutations
Approvals table is advisory; case close / export do not check `is_approved()`.

### L22 — Soft-delete absent for DSR
Hard delete only; no legal-hold / retention window.

### L23 — No request signing / mTLS for webhooks outbound
Shared secret optional; replay of connector deliveries possible with key.

### L24 — In-process orchestrator / single worker
Documented; not HA; SIGTERM drain is best-effort.

### L25 — `compare_digest` requires equal length secrets
Short wrong keys may short-circuit differently (minor timing); still OK for fixed API keys.

### L26 — Authorization header without `Bearer` treated as raw key
Unusual clients may log full header oddly; low.

### L27 — Open mode marketplace registry install still allowed
Local risk only; document.

### L28 — Hardened Docker still binds host 8000 on all interfaces
Same as M12 for hardened profile.

---

## Info / positive controls verified

| ID | Note |
|----|------|
| I1 | Constant-time API key compare (`secrets.compare_digest`) |
| I2 | SSRF blocks private/link-local/metadata hostnames + resolved private IPs |
| I3 | Decimal/hex loopback hosts blocked when DNS resolves to 127.0.0.1 |
| I4 | DSR strict auth in **current source** (not live process) |
| I5 | Path jail for marketplace `source_path` |
| I6 | Production fail-closed startup |
| I7 | Security headers baseline |
| I8 | No `dangerouslySetInnerHTML` in dashboard app source |
| I9 | No `pickle` / `eval` / `shell=True` in app `src/` |
| I10 | `yaml.safe_load` for packs |
| I11 | Security tests (harden + soc2) green in tree |
| I12 | Bandit B104 on `0.0.0.0` in blocklist is false positive |
| I13 | Compliance templates under `docs/compliance/` (process starters only) |
| I14 | Health honesty: single_worker, no fake multi-tenant enterprise claim when open |

---

## Bandit summary

| Severity | Count | Dominant tests |
|----------|------:|----------------|
| High | 0 | — |
| Medium | 14 | B608 SQL f-strings (12), B310 urlopen (1), B104 (1 FP) |
| Low | 74 | B110 try/except pass, B101 assert, B112 try/except continue, B105, B311 |

---

## npm audit

| Package | Severity | Notes |
|---------|----------|--------|
| esbuild ≤0.24.2 via vite | moderate/high | Dev server only; upgrade Vite when ready |

---

## SOC 2 Type II — still outside this codebase

| Still required | Why |
|----------------|-----|
| Approved policies + ownership | CC1 |
| SSO + MFA unique users | CC6 |
| SIEM + management review of logs | CC4 |
| HA DB + backups + drills | Availability |
| Vendor SOC reports | CC9 |
| Annual pen test | CC9 |
| CPA + 3–12 month observation | Type II definition |

Engineering baseline ≠ certified report.

---

## Priority fix order

1. **Restart live process hardened** (C1) — immediate  
2. Catch connector URL errors → 400 (H6)  
3. Admin-only pack edit / drain / job run-next / pack activate (H2–H4)  
4. Stop mapping shared key → admin for all routes (H1)  
5. Allowlist `group_field` + SQL idents (M8/M9)  
6. Author/reviewer from session only (M6)  
7. Reject query API keys always (M1)  
8. Jail audit log path (M15); Docker localhost bind (M12)  
9. Gate `/docs` in production (M19)  
10. OIDC + httpOnly sessions (SOC2 Phase B)

---

## Verification commands

```bash
# Source gates
PYTHONPATH=. pytest tests/frontline/test_security_harden.py tests/frontline/test_soc2_baseline.py -q

# After hardened restart of :8000
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/frontline/cases
# expect 401
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE http://127.0.0.1:8000/api/frontline/dsr/x
# expect 401
curl -s http://127.0.0.1:8000/health | jq .security
# expect auth_required true when hardened
```

---

## Conclusion

**Source** has a credible single-tenant hardened pilot baseline for several earlier findings (DSR, session clamp, path jail, fail-closed startup, query-key reject under AUTH_REQUIRED).  

**This pass still finds ~71 items**, dominated by:

1. **Operational open/stale live server (C1)**  
2. **Shared-key-as-admin + privileged APIs without fine RBAC (H1–H4)**  
3. **Pack disk edit default, drain, jobs**  
4. **Identity spoofing on audit fields / four-eyes**  
5. **SQL identifier surfaces, connector 500, Docker bind, localStorage, full SOC 2 org work**

Nothing in this list means “SOC 2 Type II done.” For a network-facing pilot, treat C1 + H1–H4 as fix-before-expose.
