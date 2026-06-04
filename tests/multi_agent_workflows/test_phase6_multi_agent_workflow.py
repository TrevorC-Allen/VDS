"""Tests for the runnable Phase 6 multi-agent workflow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_runtime.agent_result import AgentResult
from data_agent_core.contracts.response_contracts import FinalResponse
from data_agent_core.core.file_parser import parse_dataset_file
from data_agent_core.llm.client import MockLLMClient
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


class Phase6MultiAgentWorkflowTest(unittest.TestCase):
    def test_uploaded_table_runs_all_core_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sales.csv"
            csv_path.write_text(
                "city,sales\n"
                "Shanghai,100\n"
                "Beijing,150\n"
                "Shanghai,200\n",
                encoding="utf-8",
            )
            parsed = parse_dataset_file(csv_path, dataset_id="ds_phase6_sales")
            workflow = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
                parsed.tables,
                dataset_id=parsed.profile.dataset_id,
                dataset_profile=parsed.profile,
                llm_client=MockLLMClient(),
            )
            result = workflow.run("Which city has the highest sales?", execution_mode="dual")

        self.assertTrue(result.response.success)
        self.assertEqual("multi_agent", result.response.debug["agent_mode"])
        self.assertEqual("phase6_internal_multi_agent", result.response.debug["workflow_mode"])
        self.assertEqual(result.response.result["rows"][0]["city"], "Shanghai")
        self.assertIn("planner", result.response.debug["multi_agent_roles"])
        self.assertIn("data_engineer", result.response.debug["multi_agent_roles"])
        self.assertIn("pandas_executor", result.response.debug["multi_agent_roles"])
        self.assertIn("sql_executor", result.response.debug["multi_agent_roles"])
        self.assertIn("verifier", result.response.debug["multi_agent_roles"])
        self.assertIn("correction", result.response.debug["multi_agent_roles"])
        self.assertIn("insight", result.response.debug["multi_agent_roles"])
        self.assertIn("visualization", result.response.debug["multi_agent_roles"])
        self.assertIn("response_builder", result.response.debug["multi_agent_roles"])
        self.assertGreaterEqual(len(result.trace.tool_call_summary), 5)

    def test_workflow_supports_bounded_correction_attempts(self) -> None:
        workflow = DataAnalysisMultiAgentWorkflow.__new__(DataAnalysisMultiAgentWorkflow)
        workflow.dataset_id = "ds_retry"
        workflow.context = {}
        workflow.max_correction_attempts = 2
        workflow.runtime = _FakeCorrectionRuntime()

        result = workflow.run("retry this question", max_correction_attempts=2)

        self.assertTrue(result.response.success)
        self.assertEqual(2, workflow.runtime.correction_calls)
        self.assertEqual(3, workflow.runtime.verifier_calls)
        self.assertEqual(2, len(result.state.correction_attempts))
        self.assertTrue(all(attempt["rerun_triggered"] for attempt in result.state.correction_attempts))
        self.assertEqual("verification_passed", result.state.correction_attempts[-1]["retry_stopped_reason"])


class _FakeCorrectionRuntime:
    def __init__(self) -> None:
        self.verifier_calls = 0
        self.correction_calls = 0

    def run_planner(self, task, state, *, guidelines: str) -> AgentResult:
        logic_form = {"operation": "initial", "parameters": {}, "output_format": {"answer_type": "text"}}
        state.logic_form = logic_form
        state.analysis_plan = {"logic_form": logic_form, "steps": []}
        return AgentResult(task.task_id, task.role, True, {"analysis_planner": {}, "logic_form": logic_form})

    def run_data_engineer(self, task, state) -> AgentResult:
        state.schema_profile = {"dataset_id": "ds_retry"}
        return AgentResult(task.task_id, task.role, True, state.schema_profile)

    def run_pandas_executor(self, task, state) -> AgentResult:
        state.pandas_result = {"backend": "pandas", "success": True, "value": "ok", "rows": [{"answer": "ok"}], "columns": ["answer"]}
        return AgentResult(task.task_id, task.role, True, state.pandas_result)

    def run_sql_executor(self, task, state, *, execution_mode: str) -> AgentResult:
        state.sql_result = {"skipped": True, "reason": "fake runtime"}
        return AgentResult(task.task_id, task.role, True, state.sql_result)

    def run_verifier(self, task, state, *, guidelines: str) -> AgentResult:
        self.verifier_calls += 1
        passed = self.verifier_calls >= 3
        state.verification = {"passed": passed, "issues": [] if passed else ["needs correction"]}
        if not passed:
            corrected = {"operation": f"corrected_{self.verifier_calls}", "parameters": {}, "output_format": {"answer_type": "text"}}
            state.verification["correction_action"] = {"corrected_logic_form": corrected}
        return AgentResult(task.task_id, task.role, passed, {"verification": state.verification})

    def run_correction(self, task, state, *, guidelines: str, attempt_index: int = 1, max_attempts: int = 1) -> AgentResult:
        self.correction_calls += 1
        action = state.verification.get("correction_action")
        corrected = action["corrected_logic_form"] if isinstance(action, dict) else None
        output = {
            "needs_correction": corrected is not None,
            "corrected_logic_form": corrected,
            "attempt_index": attempt_index,
            "max_attempts": max_attempts,
        }
        state.correction_attempts.append(output)
        return AgentResult(task.task_id, task.role, True, output)

    def apply_corrected_logic_form(self, state, corrected_logic_form) -> None:
        state.logic_form = corrected_logic_form
        state.analysis_plan = {"logic_form": corrected_logic_form, "steps": []}
        state.pandas_result = None
        state.sql_result = None
        state.verification = None

    def run_insight(self, task, state, *, guidelines: str) -> AgentResult:
        state.insight = {"summary": "ok"}
        return AgentResult(task.task_id, task.role, True, {"insight": state.insight})

    def run_visualization(self, task, state, *, guidelines: str) -> AgentResult:
        state.chart = {"chart_type": "none"}
        return AgentResult(task.task_id, task.role, True, {"chart": state.chart})

    def build_final_response(self, *, run_id: str, state, guidelines: str, execution_mode: str, task_results: list[AgentResult]) -> FinalResponse:
        return FinalResponse(
            response_version="v1",
            success=True,
            run_id=run_id,
            dataset_id="ds_retry",
            question=state.question,
            answer_type="text",
            execution_mode=execution_mode,
            answer="ok",
            debug={"agent_mode": "multi_agent"},
        )


if __name__ == "__main__":
    unittest.main()
