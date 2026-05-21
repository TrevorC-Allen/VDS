"""Dual executor workflow task builder."""

from __future__ import annotations

from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask


def build_dual_executor_tasks(dataset_id: str, analysis_plan: dict) -> list[AgentTask]:
    """Build Pandas and SQL executor tasks without embedding execution logic."""

    payload = {"dataset_id": dataset_id, "analysis_plan": analysis_plan}
    return [
        AgentTask(
            task_id="pandas_executor",
            role=AgentRole.PANDAS_EXECUTOR,
            input_payload=payload,
            constraints={"code_only": True, "do_not_reinterpret_question": True},
        ),
        AgentTask(
            task_id="sql_executor",
            role=AgentRole.SQL_EXECUTOR,
            input_payload=payload,
            constraints={"code_only": True, "do_not_reinterpret_question": True},
        ),
    ]
