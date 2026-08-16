# Detailed security review — Skew AI (`v2_ai_rca_tool`)

**Date:** 2026-08-04  
**Reviewer method:** Security-reviewer workflow — SAST (Bandit), npm audit, secrets/pattern greps, manual auth/RBAC/path/SSRF review, hermetic TestClient adversarial probes, live process probe, security unit suite (50 tests).  
**Scope:** Application source (`src/`, `dashboard/` app code), live local process, Docker/env posture.  
**Authorization:** Local codebase owned by project operator; probes limited to `127.0.0.1` and TestClient (no external exploitation).  
**Completeness:** Exhaustive for this pass; not a formal third-party pen test.

---

## 1. Executive summary

| Assessment | Detail |
|------------|--------|
| **Product posture** | Single-tenant pilot with dual modes: **open local demo** vs **production-like harden** |
| **Live process at review** | **Open mode** (`auth_required: false`) — full ops API readable without credentials |
| **Hardened source controls** | Strong for a pilot: fail-closed startup, service≠admin, DSR strict, query-key reject, SSRF guards, SQL ident allowlist, job allowlist, docs off in prod-like |
| **Overall risk (hardened + secrets + localhost)** | **Medium** |
| **Overall risk (current open mode / network-exposed)** | **High / Critical** |
| **SOC 2 Type II** | **Not certifiable from code** — engineering baseline only |

### Severity counts (this review)

| Severity | Count | Notes |
|----------|------:|-------|
| Critical | 1 | Live open mode if reachable beyond trusted host |
| High | 4 | Shared secret model, open default, privilege surfaces, localStorage key |
| Medium | 12 | DuckDB lock, SSRF residual, B608 residual sites, rate limits, etc. |
| Low | 14 | CSP, fonts CDN, HSTS edge, info disclosure, session design |
| Info / positive | 12 | Controls verified working |
| **Total findings** | **~43** | Plus Bandit 88 automated (mostly Low try/except) |

---

## 2. Attack surface map

```
                    ┌─────────────────────────────────────┐
                    │  Browser / dashboard  /ui/          │
                    │  localStorage: frontline_api_key    │
                    └──────────────┬──────────────────────┘
                                   │ X-API-Key / open mode
┌──────────────────────────────────▼──────────────────────────────────┐
│ FastAPI :8000                                                       │
│  Public: /, /health, /ui, /docs (open only), /ws/*                  │
│  Gated:  /api/frontline/*, /api/packs/*, /api/interactions/*, /api/v3/* │
│  Strict: DSR, drain, pack edit write, jobs run-next, email/biometrics │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
   data/frontline.duckdb    data/domains/*.duckdb    data/security_audit.jsonl
   (ops, cases, ledger)     (corpus)                 (append audit)
          │
          ▼
   Outbound: connectors / alerts (url_guard) · optional LLM urlopen
```

**Trust boundaries:** browser ↔ API; API ↔ DuckDB file; API ↔ webhook URLs; env secrets ↔ process.

---

## 3. Live process snapshot (2026-08-04)

| Probe | Result |
|-------|--------|
| `GET /health` | 200, `auth_required: **false**`, `enterprise_readiness: single_tenant_pilot_open` |
| `GET /api/frontline/cases` (no key) | **200** |
| `DELETE /api/frontline/dsr/x` (no key) | **401** (strict) |
| Env | `FRONTLINE_OPEN_MODE=1` |

**Implication:** Anyone who can reach the port can read/modify most ops data. DSR/drain remain blocked without a configured key even in open mode.

---

## 4. Automated scan results

### Bandit (SAST)

| Severity | Count |
|----------|------:|
| High | 0 |
| Medium | 14 |
| Low | 74 |
| **Total** | **88** |

| Test ID | Count | Interpretation |
|---------|------:|----------------|
| B110 try/except pass | 63 | Noise / error swallowing |
| B608 SQL f-string | 12 | Residual; many use allowlisted constants after `safe_table`/`safe_column` |
| B310 urlopen | 1 | `src/ai/provider.py` LLM HTTP |
| B104 bind all interfaces | 1 | **False positive** — blocklist entry `0.0.0.0` in url_guard |
| B101 assert / B112 / B105 / B311 | misc | Low |

### npm audit (`dashboard/`)

| Severity | Count |
|----------|------:|
| high | 1 |
| moderate | 2 |
| critical | 0 |

**Primary issue:** esbuild/vite GHSA (dev server request forgery) — impacts `vite dev`, **not** production static assets under `/ui/`.

### Secrets / dangerous patterns

| Check | Result |
|-------|--------|
| Hardcoded live API keys in source | Not found as committed secrets; env-based |
| `pickle` / `eval` / `shell=True` | Not in app `src` for remote attack paths |
| `dangerouslySetInnerHTML` | Not in dashboard app routes |
| `yaml.load` (unsafe) | Packs use `safe_load` |

---

## 5. Control inventory (verified)

| Control | Status | Location / evidence |
|---------|--------|---------------------|
| Production fail-closed startup | Pass | `src/security/harden.py` `validate_startup_security` |
| Open mode opt-in / prod-like forces auth | Pass | `auth.auth_required()` + `is_production_like()` |
| Constant-time API key compare | Pass | `secrets.compare_digest` |
| Query API keys rejected by default | Pass | `require_api_key` + TestClient 401 |
| DSR always strict | Pass | `require_api_key_strict`; open + no key → 401 |
| Service principal ≠ admin | Pass | `role_from_headers` → `service`; drain/jobs/pack write/DSR delete/activate → 403 |
| Admin via session + bootstrap | Pass | Mint admin + drain/DSR 200 |
| Open mode session never elevates | Pass | `issue_session(..., admin)` → role `agent` |
| Bare role header cannot elevate | Pass | FIND-003 |
| Pack disk write default off + admin | Pass | `write_disk` default false; `pack:edit` |
| Job type allowlist | Pass | unknown type → 400 |
| SSRF on connectors | Pass | metadata URL → 400 |
| Cohort `group_field` inject | Pass | bad field → 400 |
| Path jail marketplace | Pass | prior tests + `assert_source_path_allowed` |
| Security headers | Pass | CSP, XFO DENY, nosniff, Referrer-Policy |
| HSTS only production-like | Pass | intentional |
| Docs/OpenAPI off production-like | Pass | `/docs` `/openapi.json` → 404 when PILOT_HARDENED |
| CORS `*` stripped | Pass | `_cors_origins` |
| Audit log path jail | Pass | under `data/` or `/var/log/skewai` |
| Security unit suite | Pass | **50 passed** |

---

## 6. Detailed findings

### Critical

#### FIND-C01 — Live open mode exposes ops API without authentication  
**Severity:** Critical (if network-reachable) / Info (if truly localhost-only trusted)  
**CVSS (network exposed):** ~9.1 (AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:L)  
**File / config:** Process env `FRONTLINE_OPEN_MODE=1`; `src/api/auth.py`  
**Description:** With open mode, `require_api_key` no-ops. Cases, packs, simulate, wallboard, enterprise, v3 read/write surfaces accept unauthenticated callers.  
**Evidence:** Live `GET /api/frontline/cases` → 200 without credentials; health `auth_required: false`.  
**Impact:** Full pilot data disclosure and mutation; privacy/ops compromise.  
**Remediation:** Never set open mode on shared hosts. Production: `ENV=production` or `PILOT_HARDENED=1` + strong `FRONTLINE_API_KEY` + `SESSION_SECRET`. Prefer bind `127.0.0.1` only.  
**CWE:** CWE-306, CWE-1188  
**Class:** Operational / configuration  

---

### High

#### FIND-H01 — Single shared API key is the entire trust boundary  
**Severity:** High  
**File:** `src/api/auth.py`, `src/api/rbac.py`  
**Description:** Authentication is one shared secret (or open). Service role reduces admin blast but still grants broad case/contact/audit access. No per-user MFA/OIDC.  
**Impact:** Key leak (localStorage, logs, phishing) = broad access; no user attribution beyond spoofable fields historically mitigated for author.  
**Remediation:** OIDC + MFA; short-lived scoped tokens; rotate keys; never put long-lived keys in JS storage for production.  
**CWE:** CWE-287, CWE-522  

#### FIND-H02 — Default/legacy open when no key and not production-like  
**Severity:** High (misconfiguration)  
**File:** `src/api/auth.py` `auth_required()`  
**Description:** If neither production-like flags nor `FRONTLINE_AUTH_REQUIRED` nor key is set, API is open. Mitigated only when operators set harden flags.  
**Impact:** Accidental deploy without env = open API.  
**Remediation:** Fail-closed default for non-dev; require explicit `FRONTLINE_OPEN_MODE=1` for demos only (partially already: production-like forces auth).  
**CWE:** CWE-1188  

#### FIND-H03 — Open mode still allows pack activation without credentials  
**Severity:** High (open mode) / N/A (hardened — 403 for service without admin)  
**File:** `src/api/routes/packs.py` `set_active_pack`  
**Description:** In open mode, `require_perm` for `pack:activate` is skipped; unauthenticated `PUT /api/packs/active` returns 200.  
**Evidence:** TestClient open mode activate → 200.  
**Impact:** Switch domain pack for all new contacts without auth in open mode.  
**Remediation:** Always require strict auth for pack activate, or gate open-mode activate behind a confirm flag.  
**CWE:** CWE-862  

#### FIND-H04 — Browser stores API key in localStorage  
**Severity:** High (when hardened + XSS or malicious extension)  
**File:** `dashboard/src/apiAuth.js`  
**Description:** Key stored as `frontline_api_key` in localStorage; any XSS/extension can exfiltrate.  
**Impact:** Full service-role (or worse if bootstrap admin path used) compromise.  
**Remediation:** httpOnly Secure cookies + OIDC; treat pilot browser as trusted device only.  
**CWE:** CWE-922  

---

### Medium

#### FIND-M01 — DuckDB single-writer lock / concurrency  
**Severity:** Medium  
**File:** `data/frontline.duckdb`, `src/data/warehouse.py`  
**Description:** One process holds write lock. Live uvicorn + pytest/CLI can fail with lock errors; health declares `single_worker: true`.  
**Impact:** Availability of tests/tools; potential confusing 500s under contention.  
**Remediation:** Isolate test DBs; eventual Postgres for multi-process; never multi-uvicorn workers on same DuckDB.  
**CWE:** CWE-662  

#### FIND-M02 — Residual Bandit B608 SQL f-strings  
**Severity:** Medium (mostly mitigated)  
**Files:** `dsr.py`, `ops.py`, `prune.py`, `analytics.py`, `insights.py`, `copilot.py`, `retrievers.py`  
**Description:** Dynamic SQL still uses f-strings for identifiers. Several paths now call `safe_table`/`safe_column` first; values remain parameterized. Bandit still flags f-string shape.  
**Impact:** Low if only allowlisted constants; high if future user input skips allowlist.  
**Remediation:** Keep allowlist; ban raw f-string table names in code review; extend allowlist helper coverage in insights/retrievers if any dynamic user fields remain.  
**CWE:** CWE-89  

#### FIND-M03 — LLM provider `urllib.request.urlopen`  
**Severity:** Medium  
**File:** `src/ai/provider.py:127` (Bandit B310)  
**Description:** HTTP client for OpenAI-compatible chat; base URL from env `OPENAI_BASE_URL`.  
**Impact:** If env compromised → SSRF with API key bearer; currently not end-user controlled.  
**Remediation:** HTTPS-only + host allowlist for base URL.  
**CWE:** CWE-918  

#### FIND-M04 — SSRF residual: DNS rebinding / TOCTOU  
**Severity:** Medium  
**File:** `src/security/url_guard.py`  
**Description:** DNS resolved at validate time; request may connect later to different IP.  
**Impact:** Classic webhook SSRF class against cloud metadata if attacker controls DNS.  
**Remediation:** Connect to pinned IP; re-resolve and compare; block redirects.  
**CWE:** CWE-918  

#### FIND-M05 — In-memory rate limiter  
**Severity:** Medium  
**File:** `src/api/limiter.py`  
**Description:** slowapi in-process counters; multi-worker bypass; reset on restart.  
**Impact:** DoS / brute-force API key guessing if weak key.  
**Remediation:** Redis backend or edge rate limit; lockout alerts.  
**CWE:** CWE-770  

#### FIND-M06 — Session token design (truncated HMAC, cleartext body)  
**Severity:** Medium  
**File:** `src/api/rbac.py` `hexdigest()[:32]`, format `json|sig`  
**Description:** 128-bit truncated HMAC; claims readable; no revocation list; TTL 3600s (900 open).  
**Impact:** Stolen token valid until exp; offline role inspection.  
**Remediation:** Full HMAC or JWT with server-side session store + revoke.  
**CWE:** CWE-613  

#### FIND-M07 — Service role still powerful  
**Severity:** Medium  
**File:** `src/api/rbac.py` PERMS for `service`  
**Description:** case write, contact write, dsr export, takeover, approvals, ingest.  
**Impact:** Shared key leak is not “read-only.”  
**Remediation:** Split keys by capability; least privilege service tokens.  
**CWE:** CWE-269  

#### FIND-M08 — No multi-tenant isolation  
**Severity:** Medium (design)  
**File:** `src/ops/tenant.py` partial; routes largely ignore  
**Description:** IDOR-style access to any case_id with any valid key.  
**Impact:** Fatal if sold as multi-tenant SaaS.  
**Remediation:** Bind tenant to credential on every query.  
**CWE:** CWE-639  

#### FIND-M09 — Four-eyes identities client-controlled  
**Severity:** Medium  
**File:** `src/frontline/four_eyes.py`, platform routes  
**Description:** `requested_by` / `reviewer` free strings; only inequality enforced.  
**Impact:** Audit spoof of dual-control narrative.  
**Remediation:** Bind to session subject only.  
**CWE:** CWE-345  

#### FIND-M10 — WebSocket auth accept-then-auth path  
**Severity:** Medium / Low  
**File:** `src/api/auth.py` `authenticate_websocket`  
**Description:** May accept socket then require first-message auth (browser path).  
**Impact:** Brief unauthenticated socket; must close 1008 on failure.  
**Remediation:** Prefer auth before accept where protocol allows.  
**CWE:** CWE-420  

#### FIND-M11 — npm esbuild/vite GHSA  
**Severity:** Medium (dev)  
**File:** `dashboard/package.json` vite/esbuild  
**Description:** Dev server vulnerability; production static `/ui` not the same surface.  
**Remediation:** Upgrade Vite when ready; do not expose vite dev on network.  
**CWE:** CWE-346  

#### FIND-M12 — DuckDB / reports no encryption at rest  
**Severity:** Medium  
**File:** `data/*.duckdb`, `reports/`  
**Description:** Disk theft = full dump.  
**Remediation:** Volume encryption / managed DB TDE.  
**CWE:** CWE-311  

---

### Low

| ID | Title | Location | Remediation |
|----|-------|----------|-------------|
| L01 | CSP `unsafe-inline` styles + Google Fonts CDN | `headers.py` | Nonce/hash styles; self-host fonts |
| L02 | HSTS only production-like | intentional | Ensure TLS before enabling |
| L03 | Public `/` and `/health` disclose pack, auth mode, readiness | `main.py` | Minimal public health |
| L04 | `detail=str(e)` error leakage | various routes | Generic client errors |
| L05 | ULID IDs enumerable if auth weak | design | Auth + rate limit |
| L06 | No progressive lockout on bad API keys | auth | Delay + alert |
| L07 | `FRONTLINE_BOOTSTRAP_ADMIN` re-enables free admin mint | `rbac.py` | One-shot file + audit |
| L08 | Audit log not tamper-evident | `audit_log.py` | Remote append-only / hash chain |
| L09 | No CSRF (OK for pure header key; needed for cookies) | — | CSRF when cookie sessions |
| L10 | Open mode public `/docs` | main | OK local; off when hardened |
| L11 | Incomplete PII redaction | `pii.py` | NER / more patterns |
| L12 | Prompt-injection filters incomplete | `input_validation.py` | Defense in depth only |
| L13 | Subscriptions rate/abuse residual | improved validation | Keep validating targets |
| L14 | Orphan active interactions | runtime | Reap / drain hygiene |

---

### Info / positive (verified)

| ID | Note |
|----|------|
| I01 | Constant-time key compare |
| I02 | SSRF blocks private/metadata (literal + DNS) |
| I03 | DSR strict in open mode without key |
| I04 | Path jail marketplace source_path |
| I05 | Startup fail-closed production-like |
| I06 | Security headers baseline |
| I07 | Service≠admin for drain/jobs/pack write/DSR/activate |
| I08 | Job type allowlist |
| I09 | Query keys rejected |
| I10 | Docs/OpenAPI disabled production-like |
| I11 | CORS wildcard stripped |
| I12 | Security suite 50 passed; no pickle/eval/shell=True remote RCE path found |

---

## 7. Hermetic adversarial results (source)

### Open mode

| Action | Status | Expected? |
|--------|-------:|-----------|
| GET cases | 200 | Yes (open) |
| POST drain | 401 | Yes (strict) |
| POST jobs/run-next | 401 | Yes |
| POST pack edit write | 401 | Yes |
| DELETE DSR | 401 | Yes |
| POST simulate | 200 | Yes (open) |
| PUT pack activate | 200 | **Risk** FIND-H03 |

### Hardened (service key)

| Action | Status | Expected? |
|--------|-------:|-----------|
| cases no key | 401 | Yes |
| cases query key only | 401 | Yes |
| drain / jobs / pack write / activate / DSR | 403 | Yes |
| unknown job | 400 | Yes |
| connector metadata URL | 400 | Yes |
| cohort inject field | 400 | Yes |
| admin session drain/DSR | 200 | Yes |
| open session elevates | blocked | Yes |
| docs/openapi | 404 | Yes |

---

## 8. Trust Services / SOC 2 (honest gap)

| Theme | Engineering | Still required for Type II |
|-------|-------------|----------------------------|
| CC6 Logical access | Partial (API key + RBAC) | SSO+MFA, unique users, access reviews |
| CC7 Ops | Partial (audit JSONL) | SIEM, IR program, evidence |
| CC8 Change | Partial (git) | PR review + deploy evidence |
| Availability | Single DuckDB | HA, backups drills, RTO/RPO |
| Confidentiality | DSR API, redaction helpers | DPAs, retention, encryption at rest |

**Code alone cannot produce a SOC 2 Type II report.**

---

## 9. Prioritized recommendations

### Immediate (ops)
1. Confirm open mode is **localhost-only** or switch to hardened with strong secrets.  
2. Clear browser `localStorage.frontline_api_key` when switching modes.  
3. Do not publish vite dev; use built `/ui` only.

### Short term (code)
1. Require auth for pack activate even in open mode (or explicit flag).  
2. Host allowlist for LLM base URL.  
3. Pin SSRF DNS / block redirects.  
4. Isolate test DuckDB from live process.  
5. Full session HMAC + revocation path.

### Medium term (product)
1. OIDC + MFA + httpOnly sessions.  
2. Scoped service tokens (not one key).  
3. Managed Postgres + encryption + backups.  
4. SIEM ship of `security_audit.jsonl`.  
5. Annual pen test + GRC for Type I → Type II.

---

## 10. Verification commands

```bash
# Live
curl -s http://127.0.0.1:8000/health | jq .auth_required,.enterprise_readiness
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/frontline/cases

# Suite
PYTHONPATH=. pytest tests/frontline/test_security_harden.py \
  tests/frontline/test_soc2_baseline.py tests/frontline/test_auth.py -q

# SAST
bandit -r src -ll
cd dashboard && npm audit
```

---

## 11. Conclusion

Skew AI has a **credible single-tenant hardened pilot control set in source**, with many prior findings closed (DSR, service≠admin, query keys, SSRF config-time, job allowlist, docs off in prod-like, SQL allowlist, CORS, etc.).

**Current live risk is dominated by open mode** (FIND-C01): unauthenticated ops access is intentional for local demo but must not be network-facing.

**Hardened residual risk** centers on shared-secret architecture (H01/H04), session design (M06), DuckDB single-node (M01/M12), and incomplete multi-user identity — not on missing basic authz for the highest-privilege routes (those correctly return 403 for service keys).

This review does **not** claim SOC 2 Type II certification or production multi-tenant readiness.
