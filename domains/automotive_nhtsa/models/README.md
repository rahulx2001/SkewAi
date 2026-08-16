# Automotive severity model

The automotive pack's `pack.yaml` references `model_artifact: automotive_nhtsa/severity_xgb`
(the v1 XGBoost severity classifier). The artifact itself is NOT shipped with this
fixture — the v2 platform degrades gracefully to the `rules` path when the model
isn't loaded (see `src/agents/triage.py::_apply_model_severity`).

To enable the ML path:
1. Train or copy the v1 XGBoost artifact into this directory.
2. Register it in `src/ml_runtime/registry.py` (not yet ported from v1).
3. Verify: `DOMAIN_PACK=automotive_nhtsa make contact` reports `severity_source=model`.

Until then, the pack uses the `rules` path (deterministic, no ML dependency).
