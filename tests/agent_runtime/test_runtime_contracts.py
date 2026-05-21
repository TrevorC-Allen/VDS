"""Tests for framework-neutral agent runtime contracts."""

from __future__ import annotations

import unittest

from agent_runtime.agent_result import AgentResult
from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask
from agent_runtime.workflow_state import WorkflowState
from ms_agent_framework_adapter.adapter import build_adapter_plan
from multi_agent_workflows.end_to_end_data_analysis_workflow import build_end_to_end_tasks


class AgentRuntimeContractTest(unittest.TestCase):
    def test_agent_task_and_result_are_serializable(self) -> None:
        task = AgentTask(task_id="planner", role=AgentRole.PLANNER, input_payload={"question": "q"})
        result = AgentResult(task_id="planner", role=AgentRole.PLANNER, success=True, confidence=0.9)

        self.assertEqual("planner", task.to_dict()["role"])
        self.assertEqual("planner", result.to_dict()["role"])

    def test_workflow_state_is_serializable(self) -> None:
        state = WorkflowState(dataset_id="ds_1", question="total sales?")
        self.assertEqual("ds_1", state.to_dict()["dataset_id"])

    def test_future_microsoft_adapter_plan_is_declarative(self) -> None:
        plan = build_adapter_plan()
        self.assertFalse(plan["imports_framework"])
        self.assertEqual("data_agent_core", plan["core_algorithm_location"])
        self.assertGreaterEqual(len(plan["workflow_steps"]), 8)

    def test_end_to_end_task_sequence_uses_internal_roles(self) -> None:
        tasks = build_end_to_end_tasks(dataset_id="ds_1", question="q")
        roles = [task.role for task in tasks]
        self.assertEqual(AgentRole.PLANNER, roles[0])
        self.assertIn(AgentRole.VERIFIER, roles)
        self.assertTrue(all(task.constraints["no_benchmark_answer_access"] for task in tasks))


if __name__ == "__main__":
    unittest.main()
