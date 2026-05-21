"""Optional Microsoft Agent Framework workflow adapter."""

from __future__ import annotations

from typing import Any

from agent_runtime.agent_role import AgentRole
from ms_agent_framework_adapter.framework_tools import MicrosoftAgentFrameworkUnavailable
from ms_agent_framework_adapter.workflow_mapping import MICROSOFT_DATA_ANALYSIS_ROLE_ORDER


def build_microsoft_sequential_workflow(agents_by_role: dict[AgentRole, Any]) -> Any:
    """Build a sequential Microsoft Agent Framework workflow from role agents."""

    WorkflowBuilder = _load_workflow_builder()
    roles = [role for role in MICROSOFT_DATA_ANALYSIS_ROLE_ORDER if role in agents_by_role]
    if not roles:
        raise ValueError("At least one Microsoft Agent Framework agent is required.")
    workflow_builder = WorkflowBuilder(start_executor=agents_by_role[roles[0]])
    previous = roles[0]
    for role in roles[1:]:
        workflow_builder = workflow_builder.add_edge(agents_by_role[previous], agents_by_role[role])
        previous = role
    return workflow_builder.build()


def _load_workflow_builder() -> Any:
    try:
        from agent_framework import WorkflowBuilder
    except Exception as exc:  # noqa: BLE001 - adapter must provide a clear optional dependency error.
        raise MicrosoftAgentFrameworkUnavailable(
            "Microsoft Agent Framework is not installed. Install locally with `pip install agent-framework` "
            "when running the optional workflow adapter."
        ) from exc
    return WorkflowBuilder
