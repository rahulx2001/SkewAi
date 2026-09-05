# Design: semantic embedding cutover

Status: **draft — not signed off**. An engineer who did not write the
embedding code must review this before `FRONTLINE_EMBEDDING_MODE=semantic`.

## Baseline (hash)

- Provider: blake2b-512 feature hash.
- On `pairs_v1` (ineligible for acceptance): ROC-AUC 0.28, AP 0.45.
- Thresholds: `FRONTLINE_CLUSTER_MAX_DISTANCE=0.85`, `FRONTLINE_NOVELTY_MIN_SCORE=3.0`.

## Candidate

- MiniLM-L6 ONNX int8, mean-pool, L2, zeropad512.
- On the same ineligible fixture: ROC-AUC 0.72, AP 0.71.
- CPU p50 ~1 ms (1 thread, this machine). Artifact ~23 MB.

## Why MiniLM, not bge-small-en-v1.5

Apache-2.0, ready quantized ONNX, CPU-only, already in the runtime budget.
bge was not exported.

## Rejected

- Cloud embedding APIs.
- Untrained dense 384→512 projection.
- Using cluster assignments or canonical_identity as positives.

## Rollback

`FRONTLINE_EMBEDDING_MODE=rollback`. Hash vectors and hash clusters remain.
Sidecar semantic data is retained.

## Data migration

Backfill writes `record_embeddings` only. `records.embedding` stays hash.

## Risk register

| Risk | Mitigation |
| --- | --- |
| Agent-authored eval labels | Ineligible for gates; human desk + κ |
| Hash thresholds on MiniLM | Keep semantic mode off until calibration |
| Mixed-version cosine | Typed error + Qubot |
| Safety coupling | Tests with ML disabled |
| Style clustering | `style_bias_report` |

## Sign-off

- Author of embedding code: ________________
- Independent reviewer: ________________  date: ________
