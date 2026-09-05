# Embedding evaluation pairs (pairs_v1)

Schema (JSONL, one object per line):

| field | meaning |
| --- | --- |
| `dataset_version` | `pairs_v1` |
| `query` | query complaint text (synthetic; no PII) |
| `candidate` | candidate complaint text |
| `label` | `positive` / `hard_negative` / `negative` |
| `failure_mode` | optional short tag |
| `category` | pack category |
| `novelty` | `true`/`false` when the query is a novel failure mode |
| `label_source` | `author_seed` until a human-reviewed sample exists |
| `review_state` | `seed` / `reviewed` |
| `reviewer` | optional |

`pairs_v1.jsonl` is a **coding-agent development fixture**. It is not an
acceptance gate (`acceptance_eligible: false`).

Human labels live in the ops table `embedding_eval_labels` with provenance
fields. Sample unlabeled pairs (no class assigned):

```
python -m scripts.eval_labels sample --pack automotive_nhtsa --n 20
```

Annotate in the dashboard **Eval labels** desk (text + entity only).
Agreement: `python -m scripts.eval_labels agreement`.

A class is gate-eligible only with ≥2 annotators and Cohen's κ ≥ 0.65,
then the quotas in `decision_rules_v1.yaml`. Those rules were written
before a human comparison is run; do not retune them after seeing scores.

Run:

```
python -c "from src.ml_runtime.embedding_eval import evaluate_pairs, load_pairs; from src.ml_runtime.hash_embedder import HashEmbedder; from src.ml_runtime.onnx_embedder import ToySemanticEmbedder; print(evaluate_pairs({'hash': HashEmbedder(), 'toy': ToySemanticEmbedder()}))"
```
