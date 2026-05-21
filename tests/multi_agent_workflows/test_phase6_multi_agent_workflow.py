"""Tests for the runnable Phase 6 multi-agent workflow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
