"""Internal runtime interfaces for framework-neutral orchestration."""

from __future__ import annotations

from typing import Protocol

from agent_runtime.agent_result import AgentResult
from agent_runtime.agent_task import AgentTask
from agent_runtime.workflow_state import WorkflowState


class AgentExecutor(Protocol):
    """Protocol for one internal agent step."""

    def execute(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        """Execute a task against current workflow state."""


class WorkflowRuntime(Protocol):
    """Protocol for a runtime that can execute a list of AgentTask values."""

    def run(self, tasks: list[AgentTask], initial_state: WorkflowState) -> WorkflowState:
        """Run workflow tasks and return final state."""
