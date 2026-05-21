"""State mapping draft for future Microsoft Agent Framework state."""

from __future__ import annotations

from typing import Any

from agent_runtime.workflow_state import WorkflowState


def map_workflow_state_to_framework_payload(state: WorkflowState) -> dict[str, Any]:
    """Map internal WorkflowState to a serializable future framework payload."""

    return {
        "dataset_id": state.dataset_id,
        "question": state.question,
        "schema_profile": state.schema_profile,
        "logic_form": state.logic_form,
        "analysis_plan": state.analysis_plan,
        "verification": state.verification,
        "final_response": state.final_response,
        "warnings": state.warnings,
        "errors": state.errors,
    }
