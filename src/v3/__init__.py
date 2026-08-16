"""Frontline v3 OS foundation — continuous learning, experiments, governance.

Deterministic / offline-first. Does not replace Enterprise Ops explorers or
require a live multi-provider LLM. See docs/v3_platform.md.
"""

from src.v3.learning import (
    generate_proposals_from_failures,
    generate_proposal_for_interaction,
    list_proposals,
    review_proposal,
    learning_trends,
)
from src.v3.experiments import (
    register_artifact,
    list_artifacts,
    create_experiment,
    list_experiments,
    record_trial,
    complete_experiment_report,
    get_experiment,
)
from src.v3.governance import (
    create_deployment,
    activate_deployment,
    rollback_deployment,
    list_deployments,
    get_active_deployment,
    stamp_interaction,
    get_stamp,
)

__all__ = [
    "generate_proposals_from_failures",
    "generate_proposal_for_interaction",
    "list_proposals",
    "review_proposal",
    "learning_trends",
    "register_artifact",
    "list_artifacts",
    "create_experiment",
    "list_experiments",
    "record_trial",
    "complete_experiment_report",
    "get_experiment",
    "create_deployment",
    "activate_deployment",
    "rollback_deployment",
    "list_deployments",
    "get_active_deployment",
    "stamp_interaction",
    "get_stamp",
]
