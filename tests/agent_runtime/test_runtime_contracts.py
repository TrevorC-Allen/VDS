"""Tests for framework-neutral agent runtime contracts."""

from __future__ import annotations

import unittest

from agent_runtime.agent_result import AgentResult
from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask
from agent_runtime.data_analysis_roles import DataAnalysisRoleRuntime
from agent_runtime.workflow_state import WorkflowState
from data_agent_core.llm.client import MockLLMClient
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
        self.assertEqual("data_agent_core", plan["core_algorithm_location"])
        self.assertEqual("agent-framework", plan["optional_dependency"])
        self.assertGreaterEqual(len(plan["workflow_steps"]), 8)
        self.assertGreaterEqual(len(plan["tool_mappings"]), 7)
        self.assertGreaterEqual(len(plan["microsoft_tool_metadata"]), 7)

    def test_end_to_end_task_sequence_uses_internal_roles(self) -> None:
        tasks = build_end_to_end_tasks(dataset_id="ds_1", question="q")
        roles = [task.role for task in tasks]
        self.assertEqual(AgentRole.PLANNER, roles[0])
        self.assertIn(AgentRole.VERIFIER, roles)
        self.assertTrue(all(task.constraints["no_benchmark_answer_access"] for task in tasks))

    def test_dimension_binding_repair_produces_corrected_logic_form(self) -> None:
        runtime = DataAnalysisRoleRuntime(dataset_id="ds_1", context={"tables": {}}, llm_client=MockLLMClient())
        state = WorkflowState(dataset_id="ds_1", question="哪个渠道销售额最高？")
        state.logic_form = {
            "task_type": "ranking",
            "operation": "ranking",
            "parameters": {
                "table": "sales",
                "metric": "sales",
                "dimension": "city",
                "available_columns": ["city", "sales_channel", "sales"],
            },
            "output_format": {"answer_type": "table"},
        }
        state.verification = {
            "passed": False,
            "correction_action": {
                "action": "repair_dimension_binding",
                "requested_dimensions": ["channel"],
                "actual_dimension": "city",
                "available_columns": ["city", "sales_channel", "sales"],
            },
        }

        result = runtime.run_correction(
            AgentTask(task_id="correction", role=AgentRole.CORRECTION, input_payload={}),
            state,
            guidelines="",
        )

        corrected = result.output_payload["corrected_logic_form"]
        self.assertEqual("sales_channel", corrected["parameters"]["dimension"])
        self.assertIn("corrected_dimension_binding=sales_channel", corrected["table_selection_reason"])
        self.assertTrue(state.correction_attempts[-1]["needs_correction"])


if __name__ == "__main__":
    unittest.main()
