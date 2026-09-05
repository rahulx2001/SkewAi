# Shadow Divergence Verification Check

Verified: divergence logic present; not triggered (no live shadow load yet).

## Components Verified:
1. `embedding_shadow_comparisons` table and query logic in `src/ml_runtime/embedding_shadow.py`.
2. `FRONTLINE_SHADOW_DIVERGENCE_PCT` threshold (default 0.35 / 35%) over sliding window (default 50 calls).
3. `shadow_divergence_alerts` table insertion in `src/ml_runtime/embedding_shadow.py:maybe_alert_divergence()`.
4. Live console "Shadow looks wrong" supervisor flag control in `dashboard/routes/LiveContactConsole.jsx:538-575` wiring to `POST /api/frontline/embedding-shadow/{interaction_id}/flag`.
5. Enqueueing of flagged interactions into `unlabeled_eval_queue` via `flag_shadow_wrong()`.
