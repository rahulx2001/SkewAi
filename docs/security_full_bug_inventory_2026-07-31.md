# Exhaustive security & bug inventory (re-review)

**Product:** Skew AI (`v2_ai_rca_tool`)  
**Date:** 2026-07-31  
**Method:** Bandit SAST, npm audit, pattern greps, manual auth/RBAC/path/SSRF review, adversarial helper checks, live probe of `:8000`, security test suite (32 passed).  
**Scope:** Full codebase + running process behavior.  
**Note:** Includes **every** material issue found (Critical → Info). No claim of infinite completeness.

---

## Executive summary

| Area | Status |
|------|--------|
| Hardening **in source** (auth, DSR strict, path jail, session clamp, headers, audit log, packs gate, production fail-closed) | Present; **32 security tests pass** |
| **Live** `127.0.0.1:8000` process | Still **open mode** (`auth_required: false`); unauthenticated DSR delete returned success payload |
| Bandit | 0 High / 14 Medium / 74 Low (many B608 SQL style) |
| npm | esbuild/vite GHSA (dev server) |
| SOC 2 Type II | Still **not** certifiable from code alone |

**Risk if hardened env is used correctly:** Medium (single-tenant pilot).  
**Risk if open mode is network-exposed:** High / Critical.

### Counts (this inventory)

| Severity | Count |
|----------|------:|
| Critical | 1 (operational / default open if exposed) |
| High | 4 |
| Medium | 18 |
| Low | 22 |
| Info | 12 |
| **Total** | **~57** |

---

## Critical

### C1 — Live/open default exposes full ops API
- **Where:** `src/api/auth.py` open mode when no key; live process confirmed open  
- **Evidence:** Live `/health` → `auth_required: false`; `DELETE /api/frontline/dsr/x` → `{"ok":true}` without credentials  
- **Impact:** Anyone who can reach the port can read/modify data, drain service, edit packs, mint sessions (agent-only in new code, but full data access)  
- **Fix:** Restart with `FRONTLINE_AUTH_REQUIRED=1` + strong keys; use `make run-hardened` or Compose `--profile hardened`

---

## High

### H1 — Shared API key = full admin principal
- **Where:** `src/api/rbac.py` `role_from_headers` returns `"admin"` whenever auth is required and no session  
- **Impact:** One leaked key = DSR delete, pack disk edit, drain, marketplace, connector config, admin session mint  
- **Fix:** Scoped service tokens; OIDC roles; never map shared key to admin for all actions

### H2 — Pack editor can overwrite domain pack files on disk
- **Where:** `POST /api/frontline/packs/{pack_id}/edit` → `src/domains/editor.py` `apply_pack_edits(..., write_disk=True)`  
- **Impact:** Authenticated (or open-mode) caller can rewrite `pack.yaml` (safety lexicon, slots, advisory SQL) → logic/safety bypass  
- **Fix:** Admin-only; dry_run default; path-safe pack_id; audit log; disable write_disk in production unless explicit flag

### H3 — Ops drain can be triggered via API
- **Where:** `POST /api/frontline/ops/drain` (`platform56.py`)  
- **Impact:** Authenticated/open caller starts service drain (reject new contacts) → availability attack  
- **Fix:** Admin-only + confirm token; audit; protect with strict auth always

### H4 — Email / biometrics / job runner are privileged side effects
- **Where:** `POST .../channels/email/ingest`, `.../biometrics/match`, `.../jobs/run-next`  
- **Impact:** Create contacts, run jobs, fingerprint matching without extra authz beyond shared key/open mode  
- **Fix:** Strict auth always for ingest; rate limits; admin for job run-next

---

## Medium

### M1 — Default open mode when key unset
- **Where:** `auth_required()`  
- **Impact:** Misconfiguration = full open API  
- **Mitigation present:** `ENV=production` / `PILOT_HARDENED` fail-closed — only if set

### M2 — API key accepted via query string (when not AUTH_REQUIRED)
- **Where:** `require_api_key` still passes `api_key` query unless strict  
- **Impact:** Logs, Referer, browser history leaks  
- **Fix:** Always reject query keys outside hermetic tests

### M3 — Browser localStorage API key
- **Where:** `dashboard/src/apiAuth.js`  
- **Impact:** XSS / extension theft  
- **Fix:** httpOnly cookie + OIDC

### M4 — HMAC session signature truncated to 32 hex chars
- **Where:** `rbac.py` `hexdigest()[:32]`  
- **Impact:** 128-bit truncation is OK-ish; nonstandard; prefer full hex or JWT  
- **Fix:** Use full HMAC or signed JWT (PyJWT)

### M5 — Session body is unsigned JSON readable (only sig protected)
- **Where:** token format `json|sig`  
- **Impact:** Role/sub visible to holders; OK if transport is TLS only  
- **Fix:** Encrypt cookie or use opaque session store

### M6 — No multi-user authorization on cases/interactions (IDOR by design of single-tenant)
- **Where:** Any case_id / interaction_id with key  
- **Impact:** In multi-tenant claims, full cross-customer access  
- **Fix:** Tenant isolation on every query

### M7 — Client-controlled `author` on case notes/patch
- **Where:** `patch_case` / `post_case_note` use `body.author`  
- **Impact:** Audit trail spoofing (“author=CEO”)  
- **Fix:** Derive author from authenticated identity only

### M8 — Tenant ID spoofable in usage metering
- **Where:** `GET/POST /usage?tenant_id=`  
- **Impact:** Metering fraud / wrong tenant stats  
- **Fix:** Bind tenant to credential; ignore client tenant_id

### M9 — Pack edit lacks require_perm beyond shared key
- **Where:** `packs/{id}/edit`  
- **Impact:** See H2  
- **Fix:** Admin-only

### M10 — Prometheus metrics under API auth only when key set
- **Where:** `GET /api/frontline/metrics/prometheus`  
- **Impact:** In open mode, metrics public; with key, still any key holder  
- **Fix:** Separate scrape secret or network policy

### M11 — CORS `allow_credentials=True` with env-configurable origins
- **Where:** `src/api/main.py`  
- **Impact:** Mis-set origins enable credentialed cross-origin calls if cookies added later  
- **Fix:** Validate no `*`; allowlist only

### M12 — Docker Compose default binds `0.0.0.0:8000`
- **Where:** `docker-compose.yml` / entrypoint  
- **Impact:** LAN exposure of pilot  
- **Fix:** Default `127.0.0.1` or require hardened profile for publish

### M13 — Dynamic SQL identifiers (Bandit B608)
- **Where:** `dsr.py`, `ops.py`, `prune.py`, `analytics.py`, `insights.py`, `copilot.py`, `retrievers.py`, `warehouse.py`, `tenant.py`  
- **Impact:** Low if constants only; high if user input ever flows into table/column names  
- **Fix:** Identifier allowlist helper

### M14 — `urllib.request.urlopen` in AI provider (Bandit B310)
- **Where:** `src/ai/provider.py:127`  
- **Impact:** If base URL ever user-controlled → SSRF; currently env-based  
- **Fix:** Fixed scheme https + host allowlist

### M15 — Rate limiter in-memory only
- **Where:** `src/api/limiter.py`  
- **Impact:** Multi-worker / multi-instance bypass; restart resets limits  
- **Fix:** Redis backend

### M16 — SECURITY_AUDIT_LOG_PATH can point anywhere writable
- **Where:** `audit_log.py`  
- **Impact:** Log injection to unexpected path if env compromised; not remote RCE by itself  
- **Fix:** Jail log path under `data/` or `/var/log/skewai`

### M17 — Incomplete tenant enforcement
- **Where:** `src/ops/tenant.py` vs most routes  
- **Impact:** Multi-tenant not real  
- **Fix:** Enforce on all reads/writes

### M18 — No encryption at rest for DuckDB files
- **Where:** `data/*.duckdb`  
- **Impact:** Disk theft → full PII/ops dump  
- **Fix:** Encrypted volume / managed Postgres TDE

---

## Low

### L1 — HSTS only in production-like (fixed intentional); local HTTP OK
- Residual: if production-like without TLS, browser HSTS can confuse

### L2 — CSP allows `'unsafe-inline'` styles
- **Where:** `headers.py`  
- **Impact:** Weakens XSS mitigation for style-based attacks  
- **Fix:** Nonce/hash styles; self-host fonts

### L3 — Google Fonts CDN in CSP
- **Impact:** Third-party dependency / privacy  
- **Fix:** Self-host fonts

### L4 — npm esbuild/vite GHSA (dev server)
- **Impact:** `vite dev` only, not production static `/ui`  
- **Fix:** Upgrade Vite

### L5 — Information disclosure via `/` and `/health`
- Pack id, feature flags, auth mode, readiness  
- **Fix:** Minimal public health; details behind auth

### L6 — Error messages may leak exception types
- **Where:** Various `detail=str(e)`  
- **Impact:** Recon  
- **Fix:** Generic client errors; log server-side

### L7 — Interaction/case IDs guessable (ULID-like)
- **Impact:** Enumeration if auth weak  
- **Fix:** Auth + rate limit (already partial)

### L8 — No account lockout / brute-force backoff on API key
- **Impact:** Online key guessing if weak key  
- **Fix:** Progressive delay + alerts on 401 spikes

### L9 — WebSocket auth after possible accept race
- **Where:** `authenticate_websocket` may accept then auth  
- **Impact:** Brief unauthenticated WS socket  
- **Fix:** Auth before accept where protocol allows

### L10 — Session TTL default 3600s; open mode 900s
- **Impact:** Stolen token window  
- **Fix:** Shorter TTL + refresh + revoke list

### L11 — No token revocation list
- **Impact:** Compromised session valid until exp  
- **Fix:** Server-side session store

### L12 — `FRONTLINE_BOOTSTRAP_ADMIN` can re-enable free admin mint
- **Where:** `rbac.py`  
- **Impact:** Mis-set env undoes FIND-002  
- **Fix:** One-shot bootstrap file; refuse if production without breakglass audit

### L13 — Open mode still allows registry marketplace install
- **Impact:** Low for local  
- **Fix:** Document only

### L14 — Audit log not integrity-protected / tamper-evident
- **Impact:** Local root can edit JSONL  
- **Fix:** Remote append-only log

### L15 — No CSRF tokens
- **Impact:** Low for pure API-key header auth; higher if cookies added  
- **Fix:** SameSite cookies + CSRF when moving to cookie sessions

### L16 — `permissions-policy` allows microphone self
- **Impact:** Intentional for voice; document  
- **Fix:** None for product need

### L17 — Debug/report paths under `reports/` may be on disk with weak FS perms
- **Impact:** Local user read  
- **Fix:** umask / volume ACLs

### L18 — Subscriptions `target` (email) not deeply validated
- **Where:** subscriptions create  
- **Impact:** Spam/abuse if open  
- **Fix:** Email validation + rate limit

### L19 — Job queue `job_type` free string
- **Impact:** Unexpected job execution if handlers expand  
- **Fix:** Allowlist job types

### L20 — Biometrics endpoint accepts free-form features
- **Impact:** Low integrity of “fingerprint”  
- **Fix:** Document as pilot-only; not identity proof

### L21 — YAML `safe_load` used (good); disk write of arbitrary YAML structure still risky
- **Where:** pack editor  
- **Impact:** See H2  

### L22 — `random` used in simulator (not crypto)
- **Where:** `simulator.py`  
- **Impact:** Fine for sim; do not use for tokens  

---

## Info / positive / residual design notes

### I1 — Constant-time compare for API keys (good)
### I2 — SSRF guards on alerts/connectors (good)
### I3 — DSR strict auth in **new** code (good; live process may lag)
### I4 — Path jail for marketplace source_path (good)
### I5 — Production fail-closed startup (good)
### I6 — Security headers baseline (good)
### I7 — Compliance templates under `docs/compliance/` (process starters)
### I8 — Single-worker honesty in health (good)
### I9 — No dangerousSetInnerHTML found (good)
### I10 — No pickle/eval/shell=True in app src (good)
### I11 — Test suite covers harden/SOC baseline (32 passed)
### I12 — Bandit B104 on url_guard listing `0.0.0.0` is **false positive** (blocklist entry)

---

## SOC 2 Type II — still not “done” by code

Even with all engineering baselines:

| Still required | Why |
|----------------|-----|
| Approved policies + org ownership | CC1 |
| SSO + MFA unique users | CC6 |
| SIEM + monitoring reviews | CC4 |
| HA DB + backups + drills | Availability |
| Vendor SOC reports | CC9 |
| Pen test | CC9 |
| CPA + 3–12 month observation | Type II definition |

---

## Priority fix list (actionable)

1. **Restart live process hardened** (C1)  
2. **Admin-only** pack edit, drain, job run-next (H2–H4)  
3. **Stop mapping shared key → admin** for all routes (H1)  
4. **Reject query API keys always** outside tests (M2)  
5. **Identifier allowlists** for SQL f-strings (M13)  
6. **Bind Docker to localhost** by default (M12)  
7. **Jail audit log path** (M16)  
8. **Author from identity**, not body (M7)  
9. **Upgrade Vite** (L4)  
10. **OIDC + httpOnly sessions** for real multi-user (SOC2 Phase B)

---

## Verification commands

```bash
make security-test
# expect 32 passed

# After hardened restart:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/frontline/cases
# expect 401
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE http://127.0.0.1:8000/api/frontline/dsr/x
# expect 401
```

---

## Conclusion

You have a **credible single-tenant hardened pilot** in **source**. The inventory above is the residual surface: **operational open mode**, **shared-key-as-admin**, **dangerous admin APIs** (pack disk edit, drain), **IDOR-style single-tenant access**, **localStorage keys**, **SQL style issues**, and **full SOC 2 org work**.

Nothing in this list is “you’re done with SOC 2 Type II.” Everything High/Critical for a **network-facing** deploy should be treated as fix-before-expose.
