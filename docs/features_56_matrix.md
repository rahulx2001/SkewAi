# Features 1–56 inventory (final)

| id | status | primary path | proof |
|----|--------|--------------|-------|
| 1 | present | src/ai/provider.py, narration.py | test_01_llm_narration_fallback |
| 2 | present | src/ml_runtime/embeddings.py | test_02_semantic_rank |
| 3 | present | src/ml_runtime/registry.py | test_03_severity_registry |
| 4 | present | src/backtest/engine.py | test_04_backtest |
| 5 | present | src/ml_runtime/clustering.py | test_05_clustering |
| 6 | implemented_this_goal | eval/frontline/llm_judge.py | test_06_llm_judge_heuristic |
| 7 | present | src/ai/prompts/ | test_07_prompt_registry_stamp |
| 8 | implemented_this_goal | src/channels/twilio_media.py | test_08_twilio_media_no_raise |
| 9 | implemented_this_goal | src/channels/stt_tts.py | test_09_server_stt_tts |
| 10 | implemented_this_goal | src/channels/messaging.py | test_10_whatsapp_sms |
| 11 | implemented_this_goal | src/channels/email_intake.py | test_11_email_intake |
| 12 | present | src/frontline/ingest.py | test_12_webhook_ingest_module |
| 13 | implemented_this_goal | src/frontline/i18n.py | test_13_multilingual |
| 14 | implemented_this_goal | src/frontline/biometrics.py | test_14_biometrics |
| 15 | present | src/agents/case_status.py | test_15_case_status_module |
| 16 | present | src/frontline/remedy.py | test_16_remedy |
| 17 | implemented_this_goal | src/frontline/booking.py | test_17_booking |
| 18 | present | src/frontline/multi_issue.py | test_18_multi_issue |
| 19 | present | src/agents/orchestrator.py | prior suite + confidence escalate |
| 20 | present | src/agents/self_critique.py | test_20_self_critique |
| 21 | implemented_this_goal | src/frontline/callback.py | test_21_callback |
| 22 | implemented_this_goal | src/frontline/dynamic_slots.py | test_22_dynamic_slots |
| 23 | present | src/frontline/alert_rules.py | test_23_alert_rules |
| 24 | implemented_this_goal | src/frontline/analytics.py | test_24_30_analytics |
| 25 | implemented_this_goal | analytics.cross_pack_patterns | test_24_30_analytics |
| 26 | implemented_this_goal | analytics.geographic_hotspots | test_24_30_analytics |
| 27 | implemented_this_goal | analytics.severity_drift | test_24_30_analytics |
| 28 | implemented_this_goal | analytics.cohort_analysis | test_24_30_analytics |
| 29 | implemented_this_goal | analytics.regulator_filing_watch | test_24_30_analytics |
| 30 | implemented_this_goal | analytics.financial_impact | test_24_30_analytics |
| 31 | present | src/ledger/chain.py | test_31_hash_chain |
| 32 | present | src/security/pii.py | test_32_38_trust |
| 33 | present | src/frontline/consent.py | test_32_38_trust |
| 34 | present | src/frontline/dsr.py | test_32_38_trust |
| 35 | present | src/frontline/archive.py | test_32_38_trust |
| 36 | present | src/frontline/explainability.py | test_32_38_trust |
| 37 | implemented_this_goal | analytics.bias_fairness_report | test_24_30_analytics |
| 38 | implemented_this_goal | src/frontline/four_eyes.py | test_32_38_trust |
| 39 | present | src/domains/builder/ | test_39_40_pack_builder_ingest |
| 40 | present | scripts/ingest_scale.py | test_39_40_pack_builder_ingest |
| 41 | implemented_this_goal | src/domains/marketplace.py | test_41_marketplace |
| 42 | implemented_this_goal | domains/medical_maude, consumer_cpsc | test_42_third_fourth_verticals |
| 43 | implemented_this_goal | src/domains/editor.py | test_43_pack_editor_dry_run |
| 44 | present | src/v3/experiments.py | test_44_experiments |
| 45 | implemented_this_goal | src/data/postgres_backend.py + migrations/ | test_45_postgres_backend_seam |
| 46 | implemented_this_goal | src/jobs/queue.py | test_46_job_queue |
| 47 | implemented_this_goal | src/observability/metrics.py | test_47_observability |
| 48 | implemented_this_goal | load/k6_ws_smoke.js + burst test | test_48_load_script_exists |
| 49 | implemented_this_goal | chaos + drain tests | test_49_chaos_defined_states |
| 50 | implemented_this_goal | src/api/rbac.py | test_50_rbac_sso |
| 51 | implemented_this_goal | create_interaction+DRAIN+lifespan SIGTERM | test_51_drain_rejects_create_interaction |
| 52 | implemented_this_goal | src/ops/tenant.py | test_52_tenant_isolation |
| 53 | implemented_this_goal | src/frontline/coach.py | test_53_coach |
| 54 | present | src/frontline/wallboard.py | test_54_wallboard |
| 55 | implemented_this_goal | src/frontline/subscriptions.py | test_55_subscriptions |
| 56 | implemented_this_goal | src/frontline/metering.py | test_56_metering |

Gates: `make ci` → **387 passed**; dual-pack eval **ALL GATES PASSED**.
API: `src/api/routes/platform56.py`.
Zero ids missing/stub_only.
