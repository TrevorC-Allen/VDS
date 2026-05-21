"""Workflow mapping draft for future Microsoft Agent Framework steps."""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.agent_role import AgentRole
from ms_agent_framework_adapter.agent_mapping import FrameworkRoleMapping, get_role_mapping


MICROSOFT_DATA_ANALYSIS_ROLE_ORDER = [
    AgentRole.PLANNER,
    AgentRole.DATA_ENGINEER,
    AgentRole.PANDAS_EXECUTOR,
    AgentRole.SQL_EXECUTOR,
    AgentRole.VERIFIER,
    AgentRole.CORRECTION,
    AgentRole.INSIGHT,
    AgentRole.VISUALIZATION,
]


@dataclass(frozen=True)
class WorkflowStepMapping:
    """One internal step mapped to a future Microsoft workflow step."""

    step_index: int
    role_mapping: FrameworkRoleMapping


def build_workflow_mapping() -> list[WorkflowStepMapping]:
    """Return the canonical role order for future Microsoft orchestration."""

    return [
        WorkflowStepMapping(step_index=index, role_mapping=get_role_mapping(role))
        for index, role in enumerate(MICROSOFT_DATA_ANALYSIS_ROLE_ORDER, start=1)
    ]
