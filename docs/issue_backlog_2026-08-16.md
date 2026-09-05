# Skew AI — issue backlog (audit 2026-08-16)

Scope: everything below is **verified against the code** (reproduced, or traced
line-by-line) — no speculative findings. Only **P0-1 (voice agent WS reconnect)
has been fixed**; everything else is left untouched and written up here so it can
be picked up independently.

Each item: what's wrong → evidence → why it matters → suggested direction.

---

## P0 — Fixed in this pass (reference only)

### P0-1 · Voice agent: every WebSocket reconnect 404'd — FIXED ✅

`src/api/routes/interactions.py`

The customer WS handler unregistered the orchestrator in its `finally` block on
*any* close, including an unintended drop. `CallWidget.jsx` reconnects with
backoff after an unintended close, so every retry hit
`_attach_customer_ws` → `active interaction not found: int_…`, and the live call
was unrecoverable. This is the banner in the reported screenshot.

Reproduced before the fix:

```
after drop, registry: []
reconnect frame: {'type': 'error', 'detail': 'active interaction not found: int_01m…'}
```

**Fix shipped:**
- `ActiveEntry.detached_at` + `FRONTLINE_WS_RECONNECT_GRACE_S` (default 120s):
  a drop without a `hangup` frame keeps the contact resumable.
- `_attach_customer_ws` returns `(entry, resumed)`; re-attach replays the
  server-side transcript in a new `resumed` frame plus a `slots_update`.
- `_detach_customer_ws` + grace-aware reaper + a background `reaper_loop()` in
  the app lifespan so a client that never returns is still finalized
  (`outcome='reconnect_timeout'`) instead of sitting `status='active'`.
- `_WSHooks` sends to the customer socket defensively — a dead customer channel
  no longer aborts the turn or kills the supervisor console fan-out.
- Client: handles `resumed`, stops retrying on `recoverable: false`, shows
  operator-safe copy instead of the raw interaction id, and releases the
  contact via `POST /end` when it gives up or the page unmounts.
- Tests: `tests/frontline/test_ws_reconnect.py`,
  `tests/frontline/test_voice_reconnect_helpers.py` (13 new; 541 + 13 pass).

---

## P0 — Not fixed

### P0-2 · Safety-question answers are never evaluated (safety-critical)

`src/agents/intake.py:265,487-504` · `domains/*/pack.yaml`

The pack asks safety questions, then **ignores the answers**. Escalation fires
only when a free-text turn matches `escalation_lexicon`. `_next_safety_question`
hands out the next question and does nothing else — no answer is ever read.

Reproduced (`automotive_nhtsa`):

```
AGENT: Is anyone hurt?
CUSTOMER: I have got hurt
AGENT: Are you in a safe location right now?      ← no escalation
CUSTOMER: yes
AGENT: What's the model year of your vehicle?
state: COLLECTING  safety_flags: {}  severity: Low
```

Same result for a bare `yes` to "Is anyone hurt?" and a bare `no` to "Are you in
a safe location right now?". Only the literal token `injury` escalates.

Two compounding defects:
1. **No answer binding.** The question index is tracked, the reply is not. There
   is no "the previous agent turn was safety question *i*, so interpret this
   turn as its answer" logic anywhere.
2. **Lexicon does not cover the vocabulary its own questions invite.**
   `escalation_lexicon` has `injury` but not `hurt`, `hurts`, `injured`,
   `bleeding`, `hospital`, `ambulance`, `burned`, `trapped` — while the pack's
   own question is literally *"Is anyone **hurt**?"*.

Consequence: a caller who says they are injured is triaged `Low` severity, no
P1 alert, no `escalated_safety` outcome. For a product whose pitch is safety
triage this is the most serious defect in the repo.

Direction: bind the pending safety question id into `ctx.slots` (same pattern as
`__diag_qid`), interpret affirmative/negative answers against a per-question
`escalate_on: yes|no`, and widen every pack's lexicon. Needs test coverage per
pack.

### P0-3 · `CLAUDE_API_KEY` is sent to OpenAI's servers

`src/ai/provider.py:89,106-113` · `.env.example:48` · `requirements.txt`

```python
api_key = (settings.openai_api_key or settings.claude_api_key).strip()
base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
url  = f"{base}/chat/completions"
...
headers={"Authorization": f"Bearer {api_key}"}
```

There is no Anthropic code path at all. `_http_chat` is OpenAI-shaped
(`/chat/completions`, `Authorization: Bearer`, default model `gpt-4o-mini`).
Anthropic's API is `POST https://api.anthropic.com/v1/messages` with an
`x-api-key` header, an `anthropic-version` header, and a different body/response
schema.

So if an operator sets only `CLAUDE_API_KEY` — which `.env.example` explicitly
invites — the app transmits their Anthropic secret to `api.openai.com` on every
call, and every call fails with 401. `anthropic>=0.40` is pinned in
`requirements.txt` but never imported: a dead dependency that makes the
Claude path look supported.

Direction: either drop `claude_api_key` from the OpenAI fallback chain and fail
loudly, or add a real Anthropic branch (`/v1/messages`, `x-api-key`,
`anthropic-version: 2023-06-01`, current model ids — `claude-opus-5`,
`claude-sonnet-5`, `claude-haiku-4-5-20251001`). Do not silently cross-send keys
between providers.

### P0-4 · 8 of 17 RBAC permissions are defined but never enforced

`src/api/rbac.py:31-76`

Machine-checked (defined in `PERMS` vs. reached by `require_perm`):

```
NEVER ENFORCED: approval:decide, audit:read, case:read, case:write,
                contact:write, ledger:read, session:mint, takeover
```

Most damaging: **`takeover`**. `POST /api/interactions/{id}/takeover`,
`/release`, `/end` (`src/api/routes/interactions.py`) and the console
`human_turn` frame carry no role check whatsoever. Any principal holding the
shared API key — role `service`, or *anyone* in open mode — can seize a live
customer conversation and speak to the customer in the agent's voice. The
`agent` and `auditor` roles are explicitly denied `takeover` in the matrix; the
matrix has no effect.

Similarly, `auditor` is denied `case:write` and can write cases anyway, and
`case:read` / `audit:read` / `ledger:read` gate nothing.

Direction: add `require_perm(get_role(request), …)` to every route whose
permission exists, and add a test that fails when a `PERMS` entry has no
enforcement site (the diff script above is a good starting point).

---

## P1 — Correctness and reliability

### P1-1 · 17 async handlers do blocking DuckDB I/O behind one process-global lock

`src/data/warehouse.py:26,53-63` + 17 call sites

`ops_con()` takes a **`threading.Lock` for the whole `with` body** and opens a
fresh `duckdb.connect()` per call. It is then called *directly* — not through
`asyncio.to_thread` — from 17 `async def` bodies:

```
src/agents/orchestrator.py    _finalize_interaction:697, create_interaction:833
src/agents/case_agent.py      run:99
src/api/routes/interactions.py  _reap_orphans_unlocked:199, _mark_failed:319,
                                list_interactions:424
src/api/routes/frontline.py   list_cases:209, get_case:246, list_audits:455,
                              early_warning:65
src/api/main.py               health:309
… + 6 more
```

Every DB touch therefore stalls the **entire event loop**, including WebSocket
frames for live calls, and all requests serialize process-wide. `_active_lock`
(asyncio) is additionally held across blocking DuckDB I/O inside
`_reap_orphans_unlocked`, so every `POST /interactions/start` blocks the loop.

This is very likely the *trigger* for the socket drop in the reported
screenshot: a slow query stalls the loop, the socket times out, the client
reconnects — into the P0-1 bug. Fixing P0-1 makes the drop survivable; this
makes it stop happening.

Direction: wrap DB access in `asyncio.to_thread` (as `console_ws` already does
for `fetch_agent_actions_since`), or move to a small connection pool and hold
the lock only around the connection handoff, not the query.

### P1-2 · Live console never shows what the customer is saying

`src/api/routes/interactions.py:_WSHooks` · `src/agents/orchestrator.py:178`

`_WSHooks.emit_customer_turn` broadcasts `agent_turn` to the console — that hook
fires for turns spoken **to** the customer (`speaker: agent|supervisor`).
`ctx.record_turn("customer", text)` has no hook and is never broadcast.

So a supervisor watching Live console sees only the agent half of the
conversation, then is expected to take over and reply. Grep confirms there is no
customer-side console broadcast anywhere.

Direction: emit a console frame from the customer-turn path in
`handle_customer_turn`, or broadcast from the WS handler on `user_turn`.

### P1-3 · Every live activity is rendered twice, once blank

`src/api/routes/interactions.py:107-125` (`fetch_agent_actions_since`),
`_WSHooks.emit_activity` · `dashboard/routes/LiveContactConsole.jsx:86-92,523`

The same `agent_activity` message type is emitted in **two incompatible
shapes**:

| source | summary field | extra |
|---|---|---|
| `_WSHooks.emit_activity` (live) | `summary` | — |
| `fetch_agent_actions_since` (200 ms DB poll) | `output_summary` | `action_id`, `ts` |

`LiveContactConsole` renders `a.output_summary || a.input_summary || "—"` and
appends with **no dedupe by `action_id`**. Result: each action shows up twice —
once as `—` (live frame), once with real text (poll). `CallWidget` reads
`msg.summary`, i.e. the opposite key.

Direction: pick one wire shape for `agent_activity`, always include
`action_id`, and dedupe on it client-side.

### P1-4 · Typing during the greeting permanently kills speech recognition

`dashboard/routes/CallWidget.jsx` — `submitTextFallback`, `recog.onend`

`speak(text, {phase:"greeting"})` sets `speakPhaseRef.current = "greeting"`.
`submitTextFallback` cancels TTS and clears `speakingRef`, but **never resets
`speakPhaseRef`**. `recog.onend` then early-returns forever:

```js
recog.onend = () => {
  if (speakingRef.current) return;
  if (speakPhaseRef.current === "greeting") return;   // ← stuck here
  …
  startRecognitionSafe();
};
```

Only `finishSpeaking` (the utterance `onend`/`onerror`) clears the phase — and
the file's own comment states `speechSynthesis.cancel()` often does not fire
`onend`. The UI also stays stuck on the "Greeting you" label/styling.

Direction: reset `speakPhaseRef`/`setSpeakPhase("normal")` in
`submitTextFallback` (and anywhere else TTS is cancelled out-of-band).

### P1-5 · Console WS: 5 DB polls/sec per connected console, on the global lock

`src/api/routes/interactions.py:757-783`

`console_ws` polls the ops DB every 200 ms per subscriber, each poll taking
`_ops_lock` (P1-1). N open console tabs = 5N lock acquisitions/sec competing
with live-call writes. `_broadcast_console` already pushes activity in real
time, so the poll is mostly redundant.

Also in the same loop: `last_ts` advances to the newest row's `ts` and the query
is `WHERE ts > ?`, so rows sharing an exact timestamp with the batch's last row
are silently dropped.

Direction: drop the poll to a slow catch-up (or remove it once P1-3 makes the
broadcast authoritative) and key the cursor on `(ts, action_id)`.

### P1-6 · Slot extraction matches stopwords out of running speech

`src/agents/intake.py:144-149` — gazetteer `match_substring`

From the reported session, `"I am facing my Indian is not working and also"`
extracted `entity_3 = "IS"` — the English word *is* matched the Lexus **IS**
gazetteer entry. That value is then shown in the Slot frame and written to the
interaction row (visible in the screenshot as `Model: IS`).

Reproduced verbatim:

```
slots: {'entity_3': 'IS', 'description': 'I am facing my Indian is not working…'}
```

Direction: require a minimum token length / case signal for short gazetteer
entries, or require an adjacent make match before accepting a 2-3 char model.

### P1-7 · Restart or resume re-asks every safety question

`src/agents/intake.py:497-502`

Asked-question state lives in `getattr(self.ctx, "_safety_asked", set())` — a
`setattr` on the context object, not in `ctx.slots` and not persisted. Any path
that rebuilds the orchestrator (process restart, future resume-from-DB) replays
the full safety script at the customer.

The adjacent `ctx.slots.setdefault("__safety_questions_asked__", "")` on line 494
is a **dead write** — carrying the code's own `# misuse; see note` comment — that
does nothing except pollute the slot dict (it appears in live slot dumps).

---

## P2 — Hygiene, dead code, and gaps

### P2-1 · No Python linter or type checker in the toolchain

No `pyproject.toml`, no `ruff`/`flake8`/`mypy` in `.venv` or the Makefile — only
`bandit`. Dead imports and unreachable code (P2-2) survive because nothing looks
for them.

### P2-2 · Dead code in the interactions router

`src/api/routes/interactions.py`
- `check_api_key` — imported, referenced exactly once (the import).
- `_get_active()` — defined, never called.
- `ingest_interaction` carries a 7-line no-op block that imports `Orchestrator`
  under `# noqa: F401` and then executes `pass`.

### P2-3 · Internal exception text is returned to clients

`src/api/routes/interactions.py` — `ingest_interaction`:

```python
raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
```

Any internal message (including DB paths or row contents) is echoed to the
caller. `get_interaction` also re-raises without `from e`, losing the cause in
logs while leaking the id outward.

### P2-4 · Rate limiting is per-process and in-memory

`src/api/limiter.py` — slowapi with the default in-memory store, keyed on
`get_remote_address`. Behind the vite dev proxy or any reverse proxy every
request shares one source IP, so a single client consumes the global budget and
the `30/minute` cap on `/interactions/start` is effectively a global cap. The
module docstring acknowledges the Redis gap; nothing enforces it.

### P2-5 · Single-worker ceiling is structural, not configured

`_active`, `_console_subscribers`, `_ops_lock`, and the rate-limit counters are
all per-process. `docker/entrypoint.sh:55` runs one uvicorn worker with no
`--workers`, and `/health` reports `"orchestrator_registry": "in_process"`.
Honest, but it means the pilot cannot scale horizontally at all — worth stating
in the deploy docs rather than leaving it to be discovered.

### P2-6 · `ws.onerror` spams the error banner during reconnect

`dashboard/routes/CallWidget.jsx` — `ws.onerror` sets
`"WebSocket connection error"` on *every* failed attempt while the widget is
mid-retry, overwriting the friendlier "reconnecting…" info line.

### P2-7 · `startCall()` does not reset all call state

`wsStatus`, `micGranted`, and `speakPhase` survive from the previous call into a
new one, so a second call can open showing stale capability/status text.

### P2-8 · `pytest` mutates tracked repo files

A plain `pytest tests/` run appends to **`domains/registry.json`** (3 duplicate
`"1.0.1 — pack-install"` history entries per run, unbounded growth) and rewrites
**`reports/qubot/lockers/int_recall_2.json`**. It also writes real interactions
into the pilot DB at `data/frontline.duckdb` for any test path that does not set
`FRONTLINE_DB_PATH`.

So `git status` is dirty after every test run and CI diffs are noisy. Verified
by running the suite and diffing (reverted afterwards).

Direction: point the registry and locker paths at a tmp dir via fixture, the
same way `reset_ops_db` already isolates the ops DB.

### P2-9 · Bandit findings are false positives — but unreviewed

17 medium findings, all checked: the `B608` hits (`prune.py`, `analytics.py`,
`copilot.py`, `dsr.py`, `ops.py`, `insights.py`, `merkle.py`, `evidence_pin.py`,
`retrievers.py`) build SQL from allowlisted identifiers or hardcoded column
names with `?` placeholders — none are injectable. Worth adding a bandit
baseline/`# nosec` with justification so real findings are not lost in noise.

---

## Suggested order

1. **P0-2** safety answers — the product's core promise is wrong today.
2. **P0-3** provider key cross-send — one-line risk, credential exposure.
3. **P0-4** enforce `takeover` and the other 7 dead permissions.
4. **P1-1** get DB I/O off the event loop — removes the WS-drop trigger.
5. **P1-2 / P1-3** make Live console actually usable for takeover.
6. P1-4 … P1-7, then P2.
