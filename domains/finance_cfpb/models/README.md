# Finance severity model

The finance_cfpb pack uses **rules-based severity** only (no ML artifact).
See `pack.yaml` → `severity.rules`.

The `model_artifact` field is intentionally absent; the pack relies on the
ordered rule list for severity scoring.
