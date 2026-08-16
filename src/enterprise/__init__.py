"""Enterprise-grade ops capabilities layered on the Frontline pilot core.

These modules are **deterministic** (SQL + rules). They do not require a live
LLM provider. Empty ``src/ai`` remains honest: copilot answers are intent-
routed warehouse queries, not generative chat.
"""

from src.enterprise.timeline import build_incident_timeline
from src.enterprise.root_cause import analyze_root_cause, list_failure_postmortems
from src.enterprise.copilot import answer_supervisor_query, list_copilot_suggestions
from src.enterprise.risk import score_interaction_risk, score_active_risks, list_risk_history
from src.enterprise.graph import build_ops_graph
from src.enterprise.memory import lookup_memory, upsert_memory_from_interaction, list_memories
from src.enterprise.catalog import list_recent_interactions
from src.enterprise.scenarios import (
    create_scenario,
    list_scenarios,
    get_scenario,
    delete_scenario,
    run_scenario,
    validate_scenario_steps,
)
from src.enterprise.decision_flow import build_decision_flow

__all__ = [
    "build_incident_timeline",
    "analyze_root_cause",
    "list_failure_postmortems",
    "answer_supervisor_query",
    "list_copilot_suggestions",
    "score_interaction_risk",
    "score_active_risks",
    "list_risk_history",
    "build_ops_graph",
    "lookup_memory",
    "upsert_memory_from_interaction",
    "list_memories",
    "list_recent_interactions",
    "create_scenario",
    "list_scenarios",
    "get_scenario",
    "delete_scenario",
    "run_scenario",
    "validate_scenario_steps",
    "build_decision_flow",
]
