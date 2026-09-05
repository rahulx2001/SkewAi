# Sampling Plan — Phase 0 Benchmark (Not Production Cutover)

## Source
Real NHTSA complaints and second-source warranty/service records archive (`data/domains/automotive_nhtsa.duckdb`).

## Quotas (must end with κ ≥ 0.65 per class, or class blocked)
- Positive paraphrase pairs: 200 (human-reviewed)
- Hard negatives (same entity/category, different failure): 200
- Multi-symptom / compound: 50
- Negation / hedge: 50
- Novel / unmatched: 50
- Safety-language (lexicon + negation): 50

## Annotators
- IDs must start with human-
- Count: Pending scheduling / recruitment (target: 2 independent annotators + 1 adjudicator; currently unavailable)
- Blind: yes (interface at `/ui/#/label-desk` presents verbatim complaint text and entity context with model identities and cluster IDs stripped)
- Adjudication: third reviewer required; original annotator cannot adjudicate

## Status
- κ target: ≥ 0.65
- Current state: Pending scheduling / access. No artificial labels written. Current baseline has 12 seed pairs only: relative comparison only (hash vs MiniLM). Not sufficient for Macro-F1, cluster ARI, or threshold calibration.

## Decision
- If quotas met + κ passes → proceed to threshold recalibration
- If quotas not met → stay in shadow; do not activate semantic mode
