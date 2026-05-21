"""Planner workflow task builder."""

from __future__ import annotations

from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask


def build_planner_task(dataset_id: str, question: str) -> AgentTask:
    """Build a framework-neutral planner task."""

    return AgentTask(
        task_id="planner",
        role=AgentRole.PLANNER,
        input_payload={"dataset_id": dataset_id, "question": question},
        constraints={"llm_first": True, "output_contract": "LogicForm"},
    )
