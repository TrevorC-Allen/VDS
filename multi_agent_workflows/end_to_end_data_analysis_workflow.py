"""Future end-to-end data analysis workflow plan.

This module builds framework-neutral AgentTask values only. It does not execute
core algorithms and does not import Microsoft Agent Framework.
"""

from __future__ import annotations

from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask
from agent_runtime.workflow_state import WorkflowState


END_TO_END_ROLE_ORDER = [
    AgentRole.PLANNER,
    AgentRole.DATA_ENGINEER,
    AgentRole.PANDAS_EXECUTOR,
    AgentRole.SQL_EXECUTOR,
    AgentRole.VERIFIER,
    AgentRole.CORRECTION,
    AgentRole.INSIGHT,
    AgentRole.VISUALIZATION,
    AgentRole.RESPONSE_BUILDER,
]


def build_end_to_end_tasks(dataset_id: str, question: str) -> list[AgentTask]:
    """Build the canonical future multi-agent task sequence."""

    return [
        AgentTask(
            task_id=f"{index:02d}_{role.value}",
            role=role,
            input_payload={"dataset_id": dataset_id, "question": question},
            constraints={
                "no_benchmark_answer_access": True,
                "no_task_id_optimization": True,
                "core_algorithm_location": "data_agent_core",
            },
        )
        for index, role in enumerate(END_TO_END_ROLE_ORDER, start=1)
    ]


def build_initial_state(dataset_id: str, question: str) -> WorkflowState:
    """Create a serializable initial workflow state."""

    return WorkflowState(dataset_id=dataset_id, question=question)
