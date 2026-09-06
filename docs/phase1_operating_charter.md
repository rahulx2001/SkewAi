# Phase 1 Live Pilot Operating Charter, Incident Classification & Stop Rules

```
========================================================================================
STATUS: 🔒 LIVE INGRESS LOCKED (Awaiting 14-Day Listen-Only SIP Fork Empirical Run)
TARGET DEPLOYMENT: automotive_nhtsa | Ingress Cap: 5% (≤50 calls/day) | Window: 13:00–21:00 UTC
========================================================================================
```

---

## 1. Five Honest Baselines (Pre-Flight Integrity Audit)

| Gate Question | Empirical Answer | File Path / Evidence |
|---|---|---|
| **1. Were the 100 contacts real recorded calls with human wrap-up tickets?** | **NO** (Generated via synthetic cohort generator) | [`src/frontline/shadow_pilot.py#L42-L210`](file:///Users/rahulkumarsinghj/DeveloperFolder/Code/v2_ai_rca_tool/src/frontline/shadow_pilot.py#L42-L210) |
| **2. Did the latency benchmark make real vendor calls over a real Twilio stream?** | **NO** (DSP/transcoding measured locally; network delays simulated) | [`src/voice/benchmark_latency.py#L125-L250`](file:///Users/rahulkumarsinghj/DeveloperFolder/Code/v2_ai_rca_tool/src/voice/benchmark_latency.py#L125-L250) |
| **3. How many true safety-positive calls were in the kill-switch evaluation?** | **8 positive cases** ($n=8$, insufficient to prove $R \ge 0.98$) | [`reports/shadow_baseline_01.json#L44-L62`](file:///Users/rahulkumarsinghj/DeveloperFolder/Code/v2_ai_rca_tool/reports/shadow_baseline_01.json#L44-L62) |
| **4. Is the cost number derived from vendor billing exports?** | **NO** (Derived from mathematical unit price formula) | [`src/frontline/shadow_pilot.py#L198-L203`](file:///Users/rahulkumarsinghj/DeveloperFolder/Code/v2_ai_rca_tool/src/frontline/shadow_pilot.py#L198-L203) |
| **5. Have external non-project human agents & QEs signed the agreement?** | **NO** (No external sign-off completed) | *Pending Listen-Only Blind Dual-Review* |

> [!CAUTION]
> **RTM Gate Status**: 🟡 **Harness Built, 🔴 Real-World Shadow Pilot Not Run**.
> Live PSTN ingress remains **HARD LOCKED** until the 14-day listen-only fork data is captured and independently evaluated.

---

## 2. Formal Incident Classification

Ambiguity during a live pilot breaks failsafes. All operational incidents are strictly categorized into four classes with deterministic circuit breaker bindings:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              INCIDENT SEVERITY TAXONOMY                                │
├──────────────────────────┬─────────────────────────────────────────────────────────────┤
│ INCIDENT TYPE            │ DEFINITION & TRIGGER BOUNDARY                               │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Class 1: Missed Safety   │ Customer mentions a verified hazard (smoke, fire, crash,    │
│ Escaped (CRITICAL)       │ brake loss, injury) and STAGE 2.3 fails to trip within 1    │
│                          │ conversational turn.                                        │
│                          │ Action: Immediate fleet-wide circuit breaker TRIP within 1s.│
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Class 2: Consecutive P1  │ AI triggers safety escalation on non-hazard utterances       │
│ False Alarms (HIGH)      │ (hedged/idiomatic turns, e.g. "gas prices are killing me")  │
│                          │ for 3 consecutive calls.                                    │
│                          │ Action: Circuit breaker TRIPS after 3rd consecutive event.  │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Class 3: Acoustic Spike  │ Rolling 10-call Time-To-First-Audio (TTFA) p95 exceeds      │
│ & Dropout (DEGRADED)     │ 1,000ms, or audio packet loss > 3.0% over 60 seconds.       │
│                          │ Action: Automatic failsafe TRIP; all calls revert to human. │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Class 4: Out-of-Scope    │ Caller indicates out-of-scope inquiry (finance, fleet sales,│
│ Domain Leak (OPERATIONAL)│ billing) and AI fails to execute SIP REFER within 2 turns.  │
│                          │ Action: Daily supervisor debrief defect; >3/day pauses gate.│
└──────────────────────────┴─────────────────────────────────────────────────────────────┘
```

---

## 3. Pre-Registered Stop Rules & Expansion Gates

The pilot split must **never** expand based on calendar time. Growth is gated strictly by empirical statistical thresholds across verified human wrap-up records:

```
      Phase 0 (Listen-Only Fork) ──► Phase 1 (5% Split) ──► Phase 2 (20% Split) ──► General Production
             (14 Days, ≥500 calls)          (500 Calls)           (2,500 Calls)
```

### Stop Rules (Instant Reversion to 100% Human Queue)
1. **Single Missed Safety Event**: Any Class 1 incident instantly halts the pilot.
2. **Breaker Trip Frequency**: More than **2 circuit breaker trips in a single 8-hour shift**.
3. **Severe CSAT Divergence**: Customer satisfaction dropping $> 5.0\text{ points}$ below contact center human baseline over any 50-call slice.
4. **Supervisor Takeover Spike**: Manual human takeover rate exceeding **15% of admitted calls**.

### Expansion Gates (Advancing 5% $\rightarrow$ 20%)
To graduate from Phase 1 (5%) to Phase 2 (20%), the system must satisfy all criteria over **500 consecutive live calls**:
* **Safety Recall**: $R = 1.0$ (Zero missed safety events).
* **Safety False Positive Rate**: $P \ge 0.85$ (Less than 15% non-hazard escalations).
* **Critical Slot Accuracy**: $\ge 90.0\%$ per entity (`Year`, `Make`, `Model`, `Category`) verified against human tickets.
* **Acoustic Latency**: $p95\text{ TTFA} \le 550\text{ms}$ with carrier-edge network variance included ($p99 \le 800\text{ms}$).
* **Blended Cost**: Actual invoiced telephony + ASR + TTS + LLM cost $\le \$0.45\text{ / call}$.
* **Cryptographic Integrity**: 100% Merkle ledger verification pass rate without a single hash discontinuity.

---

## 4. Real Step 0: Listen-Only SIP Fork Architecture

Before exposing callers to interactive AI responses, the telecom team provisions a **listen-only media tap** on the customer trunk:

```
[Inbound Caller] ───────(Carrier SIP Trunk)───────► [Customer SBC / PBX]
                                                            │
                            ┌───────────────────────────────┴──────────────────────────────┐
                            ▼ (Primary Audio Stream)                                       ▼ (Listen-Only Forked RTP)
                   [Human Agent Headset]                                          [Skew Edge Audio Bridge]
                            │                                                              │
                            ▼                                                              ▼
                  [Agent Wrap-Up Ticket]                                          [AI Shadow Transcript]
                  • entity_1..3                                                   • AI Extracted Slots
                  • category                                                      • AI Safety Triggers
                  • safety_needed (T/F)                                           • AI Severity (Triage)
                  • verified_cluster                                              • Candidate Clusters
                            │                                                              │
                            └───────────────────────────────┬──────────────────────────────┘
                                                            ▼
                                        [Blind Discrepancy Evaluator]
                                        • Wilson 95% Confidence Intervals
                                        • Cohen's Kappa Inter-Rater Agreement
```

### Protocol for the 500-Call + 100-Safety Cohort
1. **Duration**: 14 continuous business days.
2. **Volume**: Minimum 500 unselected incoming customer interactions tapped.
3. **Safety Enrichment Set**: Because real-time life safety emergencies represent $< 1\%$ of daily calls, the cohort is supplemented with **100 historical recorded calls of known safety events** (fires, unintended acceleration, brake loss, roll-overs, air bag failures) labeled independently by human safety auditors.
   * Testing on $N \ge 100$ true positives guarantees that $R \ge 0.98$ yields a Wilson lower bound $\ge 0.945$, providing legitimate statistical proof.
4. **Blind Dual-Review**: Human agents fill standard CRM tickets without seeing AI suggestions. Independent QE grades discrepancies.

---

## 5. Daily Operational Cadence & Debrief Protocol

```
[08:30 UTC] Morning Smoke Test:
            • Re-run test suite (test_health_checks.py, test_phase1_live_pilot.py).
            • Verify Merkle head integrity (python3 -m src.qubot.locker verify).
            • Check circuit breaker status: GET /api/interactions/routing/status.

[09:00 UTC] Open Ingress Gate:
            • Activate 5% routing gate (target 5%, max 50 calls/day).
            • Dedicated supervisor logged into LiveContactConsole.

[13:00 UTC] Mid-Day Triage:
            • Inspect supervisor takeovers and flagged hedged safety turns.
            • Review novel candidate clustering and latency distribution.

[17:00 UTC] Close Ingress Gate:
            • Route 100% of traffic back to standard human queue.

[17:30 UTC] Daily Operational Debrief:
            • Complete Daily Debrief Sheet (see template below).
            • Cross-reference AI extractions with supervisor wrap-up tickets.
            • Calculate daily drift and verify zero unhandled exceptions.
```

---

## 6. Daily Debrief Template

```markdown
### Phase 1 Live Pilot Daily Debrief — Day [X]
Date: YYYY-MM-DD | Supervisor on Duty: [Name] | Pack: automotive_nhtsa

#### 1. Volume & Routing Metrics
- Total Inbound Calls Offered: [N]
- Admitted to AI Pilot (Target 5%): [N] (Actual %: [X.X%])
- Diverted (Outside Hours / Volume Ceiling): [N]
- Reverted to Human Control: [N]

#### 2. Health & Failsafe Status
- Circuit Breaker Trips: [0 / N] (If >0, state reason and timestamp)
- Panic Switch Triggered: [Yes / No]
- Supervisor Takeovers: [N] ([X.X%])
- Mean Latency (TTFA): [X]ms | p95 Latency: [X]ms | Max Latency: [X]ms

#### 3. Human vs. AI Accuracy Discrepancy
- Year Match: [X / N] ([X.X%])
- Make Match: [X / N] ([X.X%])
- Model Match: [X / N] ([X.X%])
- System/Category Match: [X / N] ([X.X%])
- Discrepancy Root Causes: [Phonetic miss, background noise, caller self-correction]

#### 4. Safety & Remedy Review
- Actual Safety Hazards Encountered: [N]
- Correctly Tripped by AI: [N] (Missed: [0])
- False-Positive Safety Escalations: [N]
- Proposed Remedies Authorized by Supervisor: [N]
- Proposed Remedies Rejected/Edited by Supervisor: [N]

#### 5. Sign-Off
- Supervisor Signature: _______________________ Date: _________
- Lead Engineer Signature: ____________________ Date: _________
```

---

## 6. Traffic Gate Seed Computation & Ingress Hashing Architecture (Remediation F-002)

To maintain an exact, statistically uniform 5% split during Phase 1 live rollout without bias or accidental leakage:

### Deterministic Seed Sources
1. **Telephony Session Identifiers**: Inbound carrier media streams pass `channel_session_id` (Twilio `CallSid`) or header `X-Call-Sid`.
2. **Customer References**: Caller E.164 ANI or normalized phone number (`customer_ref`).
3. **Dedicated Ingress Identifier**: When no upstream telephony SID is present, ingress generates an immutable ULID (`int_{new_ulid()}`).

### Uniform Hash Algorithm
* **Input**: Deterministic string material UTF-8 encoded.
* **Digest**: Standard SHA-256 hash.
* **Bucket Assignment**: First 8 bytes interpreted as a 64-bit unsigned big-endian integer, modulo 100:
  $$\text{call\_hash} = \text{int.from\_bytes}(\text{SHA256}(\text{seed})[:8], \text{"big"}) \pmod{100}$$
* **Threshold Evaluation**: $\text{call\_hash} < \lfloor 100 \times \text{target\_ratio} \rfloor$. For 5% ($\text{target\_ratio} = 0.05$), calls with hash $0, 1, 2, 3, 4$ are admitted.

### Fail-Closed Safety Invariant
* If the seed cannot be computed or is missing/empty, the gate logs a `CRITICAL` event, increments `gate_seed_failure_total`, and **immediately rejects** the call to human control with reason `"seed_computation_failed"`.
* The gate **never** defaults `call_hash` to `0` or admits calls upon exception.
