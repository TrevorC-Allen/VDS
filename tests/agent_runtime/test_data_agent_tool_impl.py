"""Tests for executable internal Data Agent tool callables."""

from __future__ import annotations

import unittest

import pandas as pd

from agent_runtime.agent_role import AgentRole
from agent_runtime.data_agent_tool_catalog import build_runtime_data_agent_tool_registry
from agent_runtime.data_agent_tool_impl import DataAgentToolRuntime
from agent_runtime.tool_contracts import ToolCall
from agent_runtime.tool_dispatcher import ToolDispatcher


class DataAgentToolImplTest(unittest.TestCase):
    def test_core_tool_chain_executes_without_framework_dependency(self) -> None:
        tables = {
            "sales": pd.DataFrame(
                [
                    {"city": "Shanghai", "sales": 120},
                    {"city": "Beijing", "sales": 80},
                    {"city": "Shanghai", "sales": 30},
                ]
            )
        }
        runtime = DataAgentToolRuntime(dataset_contexts={"ds_1": {"tables": tables}})
        dispatcher = ToolDispatcher(build_runtime_data_agent_tool_registry(runtime))

        profile = dispatcher.dispatch(
            ToolCall("tool_profile", "profile_schema", {"dataset_id": "ds_1"}, AgentRole.DATA_ENGINEER)
        )
        self.assertTrue(profile.success)
        self.assertEqual("ds_1", profile.output_payload["dataset_id"])

        plan_result = dispatcher.dispatch(
            ToolCall(
                "tool_plan",
                "build_analysis_plan",
                {
                    "dataset_id": "ds_1",
                    "intent": {
                        "task_type": "ranking",
                        "operation": "ranking",
                        "parameters": {
                            "table": "sales",
                            "metric": "sales",
                            "dimension": "city",
                            "aggregation": "sum",
                            "sort_order": "desc",
                            "limit": 1,
                        },
                        "output_format": {"answer_type": "table"},
                    },
                    "column_mapping": {"table": "sales", "mapped_columns": {"metric": "sales", "dimension": "city"}},
                },
                AgentRole.PLANNER,
            )
        )
        self.assertTrue(plan_result.success)

        analysis_plan = plan_result.output_payload["analysis_plan"]
        pandas_result = dispatcher.dispatch(
            ToolCall("tool_pandas", "execute_pandas_plan", {"dataset_id": "ds_1", "analysis_plan": analysis_plan}, AgentRole.PANDAS_EXECUTOR)
        )
        sql_result = dispatcher.dispatch(
            ToolCall("tool_sql", "execute_sql_plan", {"dataset_id": "ds_1", "analysis_plan": analysis_plan}, AgentRole.SQL_EXECUTOR)
        )
        self.assertTrue(pandas_result.success)
        self.assertTrue(sql_result.success)
        self.assertEqual([{"city": "Shanghai", "sales": 150}], pandas_result.output_payload["rows"])

        verification = dispatcher.dispatch(
            ToolCall(
                "tool_verify",
                "verify_results",
                {"pandas_result": pandas_result.output_payload, "sql_result": sql_result.output_payload},
                AgentRole.VERIFIER,
            )
        )
        self.assertTrue(verification.success)
        self.assertTrue(verification.output_payload["verification"]["passed"])

        chart = dispatcher.dispatch(
            ToolCall(
                "tool_chart",
                "build_chart_spec",
                {"analysis_plan": analysis_plan, "verified_result": verification.output_payload},
                AgentRole.VISUALIZATION,
            )
        )
        insight = dispatcher.dispatch(
            ToolCall(
                "tool_insight",
                "generate_insight",
                {"question": "Which city has the highest sales?", "verified_result": verification.output_payload},
                AgentRole.INSIGHT,
            )
        )
        self.assertTrue(chart.success)
        self.assertEqual("bar", chart.output_payload["chart_type"])
        self.assertTrue(insight.success)
        self.assertIn("Verified result", insight.output_payload["summary"])


if __name__ == "__main__":
    unittest.main()
