"""Referent follow-up behavior when no previous result artifact is available."""

from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import plan_followup_actions
from data_agent_core.output.response_builder import build_response
from data_agent_core.result_artifacts import resolve_followup_referent
from data_agent_core.rule_checker import verify_execution


class ReferentMissingNoGlobalFallbackTest(unittest.TestCase):
    def test_referent_followup_without_previous_artifact_returns_clarification(self) -> None:
        question = "这些城市按月份销售额趋势怎么样？"
        context = {
            "state_name": "analysis_ready",
            "logic_form": {
                "operation": "ranking",
                "task_type": "ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {},
                "parameters": {
                    "table": "orders",
                    "available_columns": ["city", "month", "sales", "profit"],
                    "metric": "sales",
                    "dimension": "city",
                    "group_by": "city",
                    "limit": 5,
                },
                "output_format": {"answer_type": "table"},
            },
            "scope": {"metric": "sales", "dimension": "city"},
            "focus_sets": [],
            "last_result_artifact_id": "",
            "active_result_artifacts": [],
            "available_followup_actions": [],
        }

        resolved = resolve_followup_referent(question, context)
        self.assertFalse(resolved["resolved"])
        self.assertIn("REFERENT_ARTIFACT_MISSING", str(resolved.get("missing_reason", "")))

        # 不能因为找不到 artifact 而退回成“全表按月份趋势”动作
        followup_actions = plan_followup_actions(question, context)
        self.assertEqual([], followup_actions)

        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="sales",
            group_by="month",
            filters={},
            parameters={
                "table": "orders",
                "metric": "sales",
                "dimension": "month",
                "available_columns": ["month", "city", "sales", "profit"],
            },
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic, question=question)
        verification_result = verify_execution(
            ExecutionResult(
                backend="pandas",
                success=True,
                columns=["month", "sales"],
                rows=[
                    {"month": "2026-01", "sales": 120, "city": "上海"},
                    {"month": "2026-02", "sales": 130, "city": "上海"},
                ],
                value=[
                    {"month": "2026-01", "sales": 120, "city": "上海"},
                    {"month": "2026-02", "sales": 130, "city": "上海"},
                ],
            ),
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question=question),
        )

        violations = {str(item.get("code") or "") for item in verification_result.contract_report["violations"]}
        self.assertIn("REFERENT_ARTIFACT_MISSING", violations)
        self.assertIn(verification_result.semantic_status, {"needs_clarification", "failed"})
        self.assertFalse(verification_result.passed)

        response = build_response(
            run_id="run_referent_missing",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=ExecutionResult(
                backend="pandas",
                success=True,
                columns=["month", "sales"],
                rows=[
                    {"month": "2026-01", "sales": 120},
                    {"month": "2026-02", "sales": 130},
                ],
                value=[
                    {"month": "2026-01", "sales": 120},
                    {"month": "2026-02", "sales": 130},
                ],
            ),
            verification=verification_result,
        )

        self.assertNotIn("按月份展示", response.answer)
        self.assertNotIn("趋势", response.answer)
        self.assertNotIn("按月", response.answer)


if __name__ == "__main__":
    unittest.main()
