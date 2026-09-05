# Engineering Audit: Telephony Latency Deferral to Phase 1 Listen-Only SIP Fork

**Date:** 2026-09-06  
**Status:** Audit & Architecture Governance  
**Git Provenance:** `b0e923ea375c1eb8f86e3c5ec644cc8605c461f0` (tagged `v1.0-embed-setup`)  
**Target Milestone:** Phase 1 Listen-Only Media Tap (Pre-Ingress Activation)  
**Reference Document:** `docs/phase1_operating_charter.md`

---

## 1. Context & Purpose

During Phase 0, synthetic and shadow benchmarks recorded a composite Time-to-First-Audio (TTFA) $p95$ of **332.2 ms** (against a system threshold of 550 ms).

While this benchmark verifies that the internal algorithmic pipeline (VAD slice $\to$ local feature extraction $\to$ slot parsing $\to$ enrichment $\to$ TTS synthesis queue) executes within budget in local memory, **it does not constitute empirical proof of live telephony latency**. 

This document formally records that **carrier-grade telephony latency validation is deferred to the Phase 1 Listen-Only SIP Fork** before any live two-way customer traffic is admitted.

---

## 2. The Phase 0 Reality Gap: What Local Fixtures Miss

Local acoustic simulation (`simulation.py`, test fixtures, replayed WAV/PCM buffers) cannot measure real-world PSTN/carrier physical realities:

1. **Carrier SIP Trunk & RTP Jitter:**
   - Inbound carrier traversal, SBC session setup, and RTP packet jitter buffer latencies (often adding 80–150 ms depending on carrier routing).
   - Audio codec transcoding overhead (G.711 $\mu$-law / A-law $\leftrightarrow$ Opus 16 kHz).

2. **WebSocket Streaming & Connection Dynamics:**
   - Twilio / SIP provider Media Streams run over bidirectional WebSockets.
   - Network edge handshakes, TCP slow-start, packet retransmission, and mid-call WebSocket frame buffering are absent in loopback tests.
   - Reconnect handling during mid-call packet stalls.

3. **Vendor Streaming ASR & TTS Latency Under Load:**
   - In Phase 0, speech services run against mock fixtures or deterministic test streams.
   - Live cloud ASR providers (e.g., Deepgram Nova-2, Google Cloud Speech-to-Text streaming) experience network round-trip time (RTT) variance, streaming backpressure, and occasional API throttling spikes.

4. **Real-World Acoustic Variance & Barge-In:**
   - Cabin road noise, speakerphone echo, low-bandwidth cellular compression, and multi-speaker crosstalk alter VAD endpointing decisions.
   - In live settings, premature or delayed speech endpointing directly inflates perceived turn latency or causes awkward customer interruptions.

---

## 3. The Resolution: Phase 1 Listen-Only SIP Fork Tap

Rather than risking live customer interactions with theoretical latency models, the platform architecture enforces a **listen-only media tap** on the customer PBX/SBC trunk as Step 0 of Phase 1 (as defined in `docs/phase1_operating_charter.md` §4).

```
[Inbound PSTN Caller] ───(Carrier Trunk)───► [Customer SBC / PBX]
                                                    │
                 ┌──────────────────────────────────┴──────────────────────────────────┐
                 ▼ (Primary Audio Stream)                                              ▼ (Listen-Only Forked RTP)
        [Human Agent Headset]                                                 [Skew Edge Audio Bridge]
                 │                                                                     │
                 ▼                                                                     ▼
       [Agent Wrap-Up Ticket]                                                 [AI Shadow Transcript & TTFA Monitor]
       • Ground Truth Failure Slots                                           • Live Packet-Arrival TTFA Tracker
       • Real Caller Interaction                                              • Real Vendor ASR/TTS Latencies
```

### Key Properties of the Listen-Only Fork:
- **Zero Customer Risk:** The caller speaks exclusively to a human contact-center agent. The AI agent generates transcripts, slot extractions, and shadow turns in parallel without streaming audio back to the caller.
- **Empirical Ingress Telemetry:** The edge audio bridge records the exact timestamps of real RTP packet arrivals, streaming ASR finalization, VAD silence detection, and shadow TTS frame availability.
- **Real Carrier Conditions:** Latency metrics are collected across genuine cellular, VoIP, and landline audio paths.

---

## 4. Empirical Acceptance Criteria for Two-Way Ingress Gate

Live two-way traffic split (5% pilot activation) remains **hard-locked** until the listen-only SIP fork records the following empirical gates across a **14-day continuous run ($N \ge 500$ calls + 100 safety cohort calls)**:

| Metric | Target / Ceiling | Measurement Method |
| :--- | :--- | :--- |
| **Real-World TTFA ($p95$)** | $\le 550\text{ ms}$ | Real RTP arrival to synthesized TTS first chunk |
| **Real-World TTFA ($p99$)** | $\le 800\text{ ms}$ | Peak carrier jitter tail |
| **WebSocket Stream Frame Loss** | $< 0.1\%$ | Audio bridge frame sequence counter |
| **ASR Stream Finalization ($p95$)** | $\le 220\text{ ms}$ | Utterance end to final speech-to-text event |
| **TTS First Chunk Delivery ($p95$)** | $\le 180\text{ ms}$ | Generation request to first RTP playback packet |
| **VAD False Cutoff Rate** | $< 2.0\%$ | Discrepancy comparison against human agent speech turns |
| **Vendor Circuit Breaker Recovery** | $< 50\text{ ms}$ fallback | Tested against simulated vendor socket drops |

---

## 5. Summary & Sign-off Invariant

- **Phase 0 acoustic tests are marked:** `LOCAL_BENCHMARK_ONLY` — unverified against live telephony trunks.
- **Phase 1 ingress gate status:** `LOCKED`.
- **Authorizing Condition:** The two-way live pilot gate (`POST /api/interactions/routing/activate`) will refuse activation until the Telemetry Latency Log from the 14-day Listen-Only SIP Fork is reviewed and signed off by Telephony Engineering.
