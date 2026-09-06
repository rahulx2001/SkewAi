# Model card: all-MiniLM-L6-v2 ONNX int8 (zeropad 512)

**model_key:** `minilm-l6-onnx-384+zeropad512-v1`

## Intended use

Offline CPU sentence similarity for complaint retrieval, cluster matching,
and novelty *candidates*. Not a safety classifier. Not a severity model.

## Training data

None from this project. Upstream: `sentence-transformers/all-MiniLM-L6-v2`
(Wikipedia + s2orc + reddit + etc., as published by the upstream authors).
This deployment does not fine-tune.

## Known limitations

- 256-token truncation.
- Zero-pad 384→512 adds no information.
- Quantized int8 ONNX from Xenova; paraphrase pair
  "stalled at 65 mph" / "died on highway" scores ~0.44, not 0.80.
- Style (NHTSA-formal vs colloquial) can move scores; run `style_bias_report`.
- Hash-era thresholds are not valid for this model.

## Evaluation

Human-labeled acceptance set is **not yet eligible**. `pairs_v1` is a
coding-agent development fixture (`acceptance_eligible=false`). Cutover
requires κ ≥ 0.70 per class and the quotas in
`eval/embeddings/decision_rules_v1.yaml`.

## Failure modes

- Cross-version cosine is rejected.
- Missing artifact: semantic matching skipped, never hash-substituted.
- Safety path does not call this model.

## License

Apache-2.0. Artifact checksums: see `models/minilm/manifest.json` after
`python -m scripts.prepare_minilm_onnx`.

## Artifact

- Revision: `751bff37182d3f1213fa05d7196b954e230abad9`
- model SHA-256: `afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1`
- tokenizer SHA-256: `da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0`

## Date / author

2026-09-06. Engineering implementation; human sign-off of cutover is a
separate review.
