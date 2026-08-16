# Frontline v2 — Demo Script

> The 12-beat demo. Run on the automotive pack first, then switch to finance_cfpb
> to prove genericity. Total runtime: ~10 minutes.

## Product story (say this first)

**Frontline is data + analysis, not another voice bot.** Voice/chat is the
capture surface. Every contact becomes structured evidence in DuckDB; specialist
agents + Qubot turn that into cases, clusters, early warning, and audit trails.

**Shipped and honest (do not overclaim):**
- Browser voice (Web Speech) for demos — **not** Twilio/PSTN (stub only)
- Semantic similar-record rank via offline bag-of-hash embeddings + ILIKE fallback
  (not a hosted MiniLM service)
- Severity: pack rules + optional JSON rules overlay (not a live XGBoost binary)
- Backtest lead-time: recomputed by `make backtest` from domain warehouse data
- Optional LLM narration only when `FRONTLINE_LLM_ENABLED=1` + key; else deterministic
- Insights board: CSAT **friction proxy** (not survey NPS) + product-gap / severity drift
- Case status by number + entity memory slot skip for returning callers
- Consent disclosure is **opt-in** (`FRONTLINE_CONSENT_DISCLOSURE=1`)

**Demo path for “data utilization”:** after a few contacts, open **Insights**
(`#insights`) → top themes + rising product issues; open **Early Warning** for
clusters; open an audit report / `GET /api/frontline/explain/{id}` for evidence.

## Setup

```bash
# Terminal 1 — backend
cd v2_ai_rca_tool
source .venv/bin/activate
make frontline-db                    # build ops + domain warehouses
uvicorn src.api.main:app --reload --port 8000

# Terminal 2 — dashboard
cd v2_ai_rca_tool/dashboard
npm install && npm run dev            # http://127.0.0.1:8787
```

Open the dashboard in Chrome (recommended for Web Speech API). Click the
**CallWidget** page in the sidebar.

---

## Beat 1 — Open the call widget + greeting

**Click:** the mic button in the CallWidget.

**What happens:**
- `POST /api/interactions/start?channel=web_voice` creates an `interactions` row.
- WebSocket `/ws/interaction/{id}` opens.
- The orchestrator calls `start()` which emits the greeting from the active pack's
  `pack.yaml`:
  > "Thanks for calling support. What's going on with your vehicle?"
- Browser TTS (`speechSynthesis.speak()`) speaks the greeting.

**Backend ledger:** `interaction_started` + `state_transition` (→ COLLECTING) +
`greeting_emitted`.

---

## Beat 2 — Caller describes the problem

**Say:**
> "My 2019 Honda CR-V grinds when I brake."

**What happens:**
- Browser STT (`SpeechRecognition`) transcribes and sends `{"type":"user_turn","text":"...","final":true}`.
- The Sentiment Agent scores the turn (lexicon-based, deterministic).
- The Intake Agent runs gazetteer extraction:
  - `entity_1 = "2019"` (year-range validation)
  - `entity_2 = "HONDA"` (from `gazetteers/makes.csv`)
  - `entity_3 = "CR-V"` (from `gazetteers/models.csv`)
  - `category = "SERVICE BRAKES"` (from `gazetteers/categories.csv`)
  - `description = "My 2019 Honda CR-V grinds when I brake."`
- The agent asks the first safety question:
  > "Is anyone hurt?"

**Console:** the Live Contact Console shows the slots panel filling up
(pack-labeled: Year=2019, Make=HONDA, Model=CR-V, System=SERVICE BRAKES).

**Backend ledger:** `turn_scored` + `slot_extracted` + `question_asked`.

---

## Beat 3 — Safety question answer

**Say:**
> "Nobody is hurt and I'm pulled over safely."

**What happens:**
- The Intake Agent asks the second safety question:
  > "Are you in a safe location right now?"

---

## Beat 4 — Safety question answer + advisory match (Wow-moment #1)

**Say:**
> "Yes, I'm in a safe location right now."

**What happens:**
- All required slots are filled AND no question is pending → orchestrator
  transitions to ENRICHING.
- The Sentinel Agent runs the pack's `advisory_match.sql_template` against the
  `advisories` table. It matches advisory `19V-12345` (Honda CR-V brake recall).
- The agent speaks the advisory notice verbatim (from SQL, no LLM):
  > "There's a matching known issue. Advisory Id: 19V-12345 | Scope Summary: HONDA
  > CR-V SERVICE BRAKES | Remedy: Dealer will replace front brake pads and rotors
  > free of charge. | Url: https://www.nhtsa.gov/recalls/19V-12345."
- In parallel, Triage scores severity (`Medium`, P2) using the pack's severity rules.

**Console:** an `agent_activity` card appears from the Sentinel Agent with the
advisory evidence-id chip `19V-12345`. A Triage activity card shows `severity=Medium (P2)`.

**Backend ledger:** `advisory_check` + `advisory_notified` + `severity_scored` +
`priority_assigned`.

---

## Beat 5 — Investigator brief (Wow-moment #2)

**What happens (still during ENRICHING):**
- The Investigator Agent runs:
  1. Similar-record retrieval → ranks corpus hits (semantic bag-of-hash when
     scores clear threshold, else SQL `ILIKE`/entity filters). Ledger
     `output_summary` notes `mode=semantic` or `mode=ilike`.
  2. Cluster match → e.g. cluster #14 (fixture/rebuildable via `make cluster`).
  3. Spike check → weekly anomaly rows when present.
  4. Backtest lead time → from `backtest_results` (recompute with `make backtest`
     after scale ingest; fixture demo may show multi-week lead time).
- Console activity card shows narration + evidence IDs for similar records/cluster.

**Backend ledger:** `similar_search` + `cluster_matched` + `spike_checked` +
`brief_written`.

**Optional:** `GET /api/frontline/explain/{interaction_id}` shows the same
evidence chain as a structured payload.

---

## Beat 6 — Case creation + remedy loop + goodbye

**What happens:**
- The Case Agent creates a `cases` row (severity from rules/JSON overlay,
  cluster_match_id / advisory_match_id when present).
- Grounded **remedy/next-step** is ledgered from advisory `remedy`/`url` fields
  (no invented repairs). Multi-problem descriptions containing “also …” can open
  linked `contact_issues` / secondary cases.
- Investigation auto-open when min cases threshold is met on a cluster.
- Goodbye includes case number; when advisory matched, customer-facing remedy
  text is appended; investigation line when opened.

**Backend ledger:** `case_created` + `followup_drafted` (incl. remedy offer) +
`investigation_opened` / `investigation_linked` + `goodbye_emitted`.

**After a few contacts:** open **Insights** for themes / angry contacts / rising
issues (product-gap board).

---

## Beat 7 — Audit report (Wow-moment #3)

**What happens (after DONE):**
- The orchestrator enqueues the `post_contact_audit` playbook.
- Qubot v2's auditor:
  1. Pulls the full contact trace (header + turns + actions + case).
  2. For every `agent_actions` row, re-verifies every cited evidence ID against
     the domain warehouse (advisory `19V-12345` exists AND scopes to HONDA/CR-V/
     SERVICE BRAKES; record `NHTSA-100001` exists; cluster #14 exists).
  3. Extracts IDs from `output_summary` + `input_summary` to catch uncited claims.
  4. Verdict per action: `grounded | unverifiable | mismatch`.
- Writes the audit report to `reports/qubot/contacts/{interaction_id}.md`.

**Dashboard:** open the **Audit Reports** page. Click the new report. See:
- Summary (channel, started/ended, outcome, peak frustration, case id)
- Timeline table (every turn with latency, LLM flag, frustration score)
- Agent actions table with per-action verdict (all ✅ grounded)
- Frustration curve (ASCII bar chart)
- Flags + recommendations (empty if grounded)

**Backend ledger:** the audit reads `agent_actions`; no new rows (audit is read-only
over the ledger, except for the `alert_sent` row if a mismatch fires).

---

## Beat 8 — Frustration detection + handoff offer

**Start a new call.** Use a frustrated tone from the first turn:

**Say (turn 1):**
> "I am ABSOLUTELY FURIOUS about my 2019 Honda CR-V brakes grinding!!"

**Say (turn 2):**
> "This is RIDICULOUS and I'm calling my lawyer!!"

**What happens:**
- The Sentiment Agent scores each turn (lexicon: `furious`=1.0, `ridiculous`=0.8,
  `lawyer`=0.95, `absolutely`=1.2 intensifier, `!!`=exclamation bump, `ABSOLUTE
  FURIOUS`=ALL-CAPS bump).
- Rolling average of last 3 turns crosses `FRONTLINE_FRUSTRATION_THRESHOLD=0.65`.
- The orchestrator fires `frustration_flagged` + emits the handoff offer:
  > "I can flag this for a human specialist right away — meanwhile let me make sure
  > I have the details right."
- The widget receives `{"type":"handoff_offer"}`.
- The Live Contact Console sorts this interaction to the top with a red pulse.

**Backend ledger:** `frustration_flagged` + `handoff_offer_emitted`.

---

## Beat 9 — Supervisor takeover

**Click:** "Take over" on the frustrated interaction card in the Live Contact Console.

**What happens:**
- `POST /api/interactions/{id}/takeover` → orchestrator enters SUPERVISED.
- AI stops generating turns; enrichment agents keep running.
- The card grows a reply box.
- A `takeover_started` ops alert fires (deduped per interaction per day).

**Type a reply:**
> "Hi, this is Sarah from the escalation team. I've pulled up your case — let me
> get this sorted for you right now."

**Click:** Send.

**What happens:**
- `{"type":"human_turn","interaction_id":"...","text":"..."}` flows over `/ws/console`.
- The orchestrator ledgeres the supervisor turn (`agent='supervisor'`,
  `action_type='human_turn'`) BEFORE delivering it.
- The widget receives `{"type":"agent_turn","speaker":"supervisor","text":"...","speak":true}`
  and speaks it via TTS.

**Click:** "Release" → AI resumes (slot state intact).

**Backend ledger:** `takeover_started` + `human_turn` + `takeover_released`.

---

## Beat 10 — Simulate traffic

**Click:** "Simulate traffic (25 contacts)" on the Early-Warning Board header.

**What happens:**
- `POST /api/frontline/simulate?count=25&speed=instant` runs the Traffic Simulator.
- 25 corpus records are sampled from the automotive domain warehouse.
- Each record is templated into a scripted contact (entities + category from the
  record's columns; caller utterances templated from the record's narrative text).
- Each contact runs through the REAL orchestrator over the simulated channel
  adapter — same agents, same ledger, same audits.
- **LLM-free:** 0 LLM calls, $0 cost, finishes in seconds.
- All 25 interactions are marked `channel="simulated"` and visually badged.

**Dashboard:** the Early-Warning Board, Case Queue, and Investigations tab light
up with realistic activity. Existing clusters get more cases; new investigations
auto-open when the Nth case on a cluster crosses the threshold.

**Backend ledger:** 25 × ~22 agent_actions rows = ~550 ledger rows, all grounded.

---

## Beat 11 — Genericity: switch to finance_cfpb

**Open:** the Settings page in the dashboard.

**Click:** the `finance_cfpb` pack in the pack selector. Confirm.

**What happens:**
- `PUT /api/packs/active?pack_id=finance_cfpb` updates the active pack store.
- The next interaction uses the finance pack's manifest: different greeting,
  different entities (Product/Sub-product/Company), different slots, different
  advisories (CFPB enforcement actions).

**Reload:** the CallWidget page.

**Say:**
> "My checking account at Chase was charged twice for a transfer."

**What happens:**
- Same generic agents, different pack. Greeting: "Thanks for calling. What issue
  are you having with your account?"
- Slots: `entity_1=Checking account`, `entity_2=Transaction issue`,
  `entity_3=Chase`, `category=..., description=...`
- Same console, same audit, same early-warning board. **One platform, two
  industries, zero code changes.**

---

## Beat 12 — Audit a finance contact

After completing the finance call:

**Open:** the Audit Reports page.

**Click:** the new finance contact audit.

**What happens:**
- Same audit report structure, different pack_id (`finance_cfpb`), different
  pack_version.
- Groundedness verdict: ✅ grounded (every cited evidence ID verified against the
  finance domain warehouse).

---

## Tear-down

```bash
# Stop the servers (Ctrl+C in each terminal)
make clean                  # drop the DuckDB files
```

## See also

- [Frontline Architecture](frontline_architecture.md)
- [Domain Pack Guide](domain_pack_guide.md)
