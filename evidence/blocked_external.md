=== BLOCKED EXTERNAL — DO NOT CLAIM FIXED ===

F-008 Crypto-shred inert
  Blocked: legal review (crypto-shred vs tombstone) + real interaction test required.
  Code ready (pii.py / encryp / shred). Not exercised on real contact.
  Action: Execute erasure_drill weekly; schedule real DSR test with legal.

F-009 Shadow-pilot label leak / F-010 Self-comparison κ
  Blocked: 200+/200+/50+ human-reviewed pairs required; 2 annotators + adjudicator; κ ≥ 0.70.
  Status: 12 seed pairs (author_seed, acceptance_eligible=false). No synthetic pairs written.
  Action: Execute eval_sampling_plan.md recruitment; do not restore scores until κ passes.

F-011 --mode=live synthetic scorecard
  Blocked: requires real recordings / inputs.
  Status: [OFFLINE_SYNTHETIC] enforced; no synthetic verdict presented as empirical.
  Action: Phase 1 listen-only SIP fork (14-day, N≥500) before any live claim.

F-012 No worker / scheduler
  Blocked: deployment / infrastructure.
  Status: queue mechanism correct; run_next has only manual caller.
  Action: Deploy worker + compose/copy for scheduled_scan / erasure_drill / reenqueue.

Design sign-off (embedding_cutover.md)
  Blocked: independent review unavailable / deferred.
  Status: Implementation verified; documentation unsigned; PENDING / NOT GRANTED.
  Action: Obtain independent sign-off or document explicit deferred status.

Real vendor latency / SIP
  Blocked: telecom provisioning.
  Status: telemetry_latency_deferral.md written; benchmark is offline_lognormal_model.
  Action: Phase 1 listen-only SIP fork; measure p95/p99/max with real Deepgram/Llm/TTS.

Threshold calibration (NOVELTY_MIN_SCORE / CLUSTER_MAX_DISTANCE)
  Blocked: requires validated human-labeled evaluation set.
  Status: 3.0 / 0.85 remain hash-era.
  Action: Derive from PR curve after annotator κ passes; do not change until then.
