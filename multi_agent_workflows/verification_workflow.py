"""Verification workflow task builder."""

from __future__ import annotations

from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask


def build_verification_tasks(dataset_id: str, question: str) -> list[AgentTask]:
    """Build verifier and correction tasks without implementing verification."""

    payload = {"dataset_id": dataset_id, "question": question}
    return [
        AgentTask(
            task_id="verifier",
            role=AgentRole.VERIFIER,
            input_payload=payload,
            constraints={"rules_first": True, "llm_assisted": True},
        ),
        AgentTask(
            task_id="correction",
            role=AgentRole.CORRECTION,
            input_payload=payload,
            constraints={"max_attempts": 2, "verifier_required": True},
        ),
    ]
