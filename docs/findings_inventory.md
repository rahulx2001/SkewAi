# Skew AI — findings inventory (2026-08-16)

Scope: current `v2_ai_rca_tool` tree. Each item is checkable in a shipped file
or a live/TestClient response. Suite run: **528 passed**, 1 Starlette/httpx
deprecation warning (`tests/frontline`, 86s).

Not counted as defects (product non-goals): paid Stripe, SOC 2 Type II
attestation, bit-identical replay, Axion clone.

---

## High

### H1. `/health` lies about worker count
- **Path:** `src/jobs/registry.py` (`register_worker`, `list_workers`); `src/api/main.py` lifespan calls `register_worker` on every start.
- **Problem:** DuckDB `worker_registry` never expires rows. Each API restart inserts another `status=up` worker. Live `GET /health` returned `worker_count: 6` then 7 rows in the table, and `single_worker: false`, while a single uvicorn process is listening. README says run one worker; the health field cannot be trusted.
- severity: high

### H2. Browser session lives in `localStorage`
- **Path:** `dashboard/src/apiAuth.js` (`SESSION_STORAGE`, `completeGoogleHandoff`, `signIn`)
- **Problem:** The Google/OIDC handoff and the leftover name-mint both write the signed session token to `localStorage` and send `X-Frontline-Session`. Any XSS reads the session. The file itself says prefer httpOnly cookies.
- severity: high

### H3. Open-mode name mint still issues a real session
- **Path:** `POST /api/frontline/auth/session` (`src/api/routes/platform56.py`); `signIn()` in `dashboard/src/apiAuth.js`
- **Problem:** Live POST with `{"subject":"auditor","role":"admin"}` returned `200` and a signed token (`role` clamped to `agent`). The UI now points at Google, but the API still mints identity from a JSON body with no IdP. Anyone who can reach the open server is “signed in.”
- severity: high (open-mode / local bind; still a real auth hole if the port is exposed)

### H4. OIDC handoff has no time-to-live
- **Path:** `src/frontline/oidc.py` `consume_handoff`
- **Problem:** `created_at` is selected and never checked. An unused `handoff_id` in a URL remains redeemable until first use. Combined with the token in the hash (`#signin?handoff=`), browser history is a login credential.
- severity: high

---

## Medium

### M1. Schema contract never rejects extra fields
- **Path:** `src/data/trust.py` `schema_contract_ok`
- **Problem:** The loop sets `extra_ok = True` when a key is *not* in `CANONICAL_RECORD_FIELDS`. Unknown columns never fail the contract. Completeness/freshness still run; this check is dead.
- severity: medium

### M2. Google OIDC is unwired in this environment
- **Path:** `src/frontline/oidc.py` `provider_status`; live `GET /api/frontline/auth/oidc/status`
- **Problem:** Response is JSON `{configured: false, provider: "google", client_id: ""}`. No `.env` with `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. The sign-in page (`dashboard/routes/SignIn.jsx`) correctly disables **Continue with Google**.
- severity: medium — **configuration gap**, not a code bug (see non-goals).

### M3. OIDC finish mints with a hardcoded admin issuer
- **Path:** `src/frontline/oidc.py` `finish_callback` → `issue_session(subject, "agent", issuer_role="admin")`
- **Problem:** After Google verifies, the server impersonates an admin issuer to mint. Role is `agent`, but the issuer argument bypasses the “need an admin session” rule by construction. Fine if Google is the only caller; dangerous if `finish_callback` is ever invoked from a looser path.
- severity: medium

### M4. FastAPI `/ui` dist can lag Vite
- **Path:** `dashboard/dist/` vs `dashboard/` source; `src/api/main.py` mounts `/ui` from dist
- **Problem:** Local operators on `:8787` see Vite; `:8000/ui` serves a built dist. Dist `index.html` exists (2026-08-16 16:19) and contains “Continue with Google”, but any later src edit is invisible on the one-box URL until `npm run build`. Easy to demo the wrong chrome.
- severity: medium

### M5. `except Exception: pass` is widespread
- **Path:** 84 sites under `src/` (ledger writer, orchestrator, case_agent, mapping_ingest ALTER, `src/api/main.py` lifespan register_worker, outreach `record_action`, etc.)
- **Problem:** Failed ledger pins, worker registration, and outreach alerts disappear. Not all are bugs, but several hide production failures.
- severity: medium (class); individual sites vary

### M6. Trust ingest still has an `enforce_trust=False` backdoor
- **Path:** `src/domains/mapping_ingest.py` `ingest_mapped_csv`; `scripts/ingest_nhtsa.py`
- **Problem:** Historical NHTSA load writes untrusted rows by design. Live default is trusted-only. A caller that forgets the flag (or copies the script) bypasses freshness/dedup.
- severity: medium (documented backfill; foot-gun)

### M7. In-process WS registry is empty after process restart
- **Path:** `src/api/routes/interactions.py` `_attach_customer_ws`, `_active`; `dashboard/src/voiceHelpers.js` `isFatalWsError`
- **Problem:** A second concurrent customer socket is already rejected (HTTP 409 / `interaction_busy`). CallWidget stops retrying on `isFatalWsError`. Restart clears in-memory `_active`, so leftover tabs reconnect into 404s. uvicorn `[accepted]` is the handshake, not a missing lock. The id `int_01m0528apsk5rbc2k4t0s121q0` is a helper-test fixture (`tests/frontline/test_voice_reconnect_helpers.py`), not a live storm.
- severity: medium

---

## Low

### L1. Leftover passwordless `signIn({subject})` helper
- **Path:** `dashboard/src/apiAuth.js` `signIn`
- **Problem:** UI no longer uses it; the function still mints via `/auth/session`. Dead API surface in the browser bundle.
- severity: low

### L2. Health advertises `soc2_engineering_baseline: true`
- **Path:** `src/api/main.py` `/health`
- **Problem:** Same payload notes this is not a Type II attestation. The boolean is easy to screenshot out of context.
- severity: low (labeled; not a Type II claim)

### L3. Outreach ledger write is swallowed
- **Path:** `src/frontline/outreach.py` `notify_affected_owners` `except Exception: pass` around `record_action`
- **Problem:** Owners can be selected and still leave no `alert_sent` ledger row.
- severity: low

---

## Suite and live entry

| Check | Result |
| --- | --- |
| `pytest tests/frontline` | **528 passed**, 1 warning, 86.08s |
| `GET /health` | `status=ok`, `db_ok=true`, `pack_ok=true`, `auth_required=false`, `worker_count=6` |
| `GET /api/frontline/auth/oidc/status` | JSON, `configured=false`, `provider=google` |
| `GET /api/frontline/auth/me` | JSON, `signed_in=false` |

Evidence: `{SCRATCH}/pytest.log`, `{SCRATCH}/entry.log`, `{SCRATCH}/scan.log`.
