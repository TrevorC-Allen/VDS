"""Referent artifact follow-up regression tests."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.output.response_builder import build_response
from data_agent_core.result_artifacts import resolve_followup_referent
from data_agent_core.task_contract_builder import apply_referent_contract
from data_agent_core.verifier.rule_checker import verify_execution


class ReferentArtifactFollowupTest(unittest.TestCase):
    def test_top5_city_monthly_trend_filters_to_artifact_values(self) -> None:
        context = _ranking_context(["上海", "北京", "广州", "深圳", "杭州"], limit=5)
        question = "这些 Top 对象按月份的销售额趋势怎么样？"

        resolved = resolve_followup_referent(question, context)
        self.assertTrue(resolved["resolved"])
        self.assertEqual(["上海", "北京", "广州", "深圳", "杭州"], resolved["referent_values"])

        actions = plan_followup_actions(question, context)
        self.assertEqual(1, len(actions))
        contract = actions[0]["referent_contract"]
        self.assertEqual(["上海", "北京", "广州", "深圳", "杭州"], contract["referent_values"])

        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="sales",
            group_by="month",
            filters={},
            parameters={"table": "sales", "metric": "sales", "dimension": "month"},
            output_format={"answer_type": "table"},
        )
        apply_referent_contract(logic, contract)
        plan = build_analysis_plan(logic, question=question)
        result = execute_plan(plan, {"tables": {"sales": _sales_frame()}, "primary_table": "sales"})
        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual("passed", verification.semantic_status)
        observed_cities = {row["city"] for row in result.rows}
        self.assertEqual(set(contract["referent_values"]), observed_cities)
        self.assertNotIn("苏州", observed_cities)

        response = build_response(
            run_id="run_followup_top5",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        )
        self.assertIn("本次分析对象来自上一轮 Top 结果", response.answer)
        for city in contract["referent_values"]:
            self.assertIn(city, response.answer)

    def test_top1_city_monthly_trend_says_previous_top_object_only_has_one_city(self) -> None:
        context = _ranking_context(["上海"], limit=1, metric="amount")
        question = "这些 Top 对象按月份金额趋势怎么样？"
        actions = plan_followup_actions(question, context)
        self.assertEqual(1, len(actions))

        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="amount",
            group_by="month",
            filters={},
            parameters={"table": "sales", "metric": "amount", "dimension": "month"},
            output_format={"answer_type": "table"},
        )
        apply_referent_contract(logic, actions[0]["referent_contract"])
        plan = build_analysis_plan(logic, question=question)
        result = execute_plan(plan, {"tables": {"sales": _sales_frame()}, "primary_table": "sales"})
        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_followup_top1",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual(["上海"], verification.task_contract["referent_values"])
        self.assertIn("上一轮结果，仅包含上海一个城市", response.answer)
        self.assertNotIn("北京", {str(value) for row in result.rows for value in row.values()})

    def test_referent_without_previous_artifact_needs_clarification_not_global_trend(self) -> None:
        question = "这些城市趋势？"
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="sales",
            group_by="month",
            filters={},
            parameters={"table": "sales", "metric": "sales", "dimension": "month"},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic, question=question)
        result = ExecutionResult(backend="pandas", success=True, columns=["month", "sales"], rows=[{"month": "2026-01", "sales": 999}], value=[{"month": "2026-01", "sales": 999}])
        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))

        codes = {item["code"] for item in verification.contract_report["violations"]}
        self.assertIn("REFERENT_ARTIFACT_MISSING", codes)
        self.assertIn(verification.semantic_status, {"needs_clarification", "failed"})
        self.assertFalse(verification.passed)


def _ranking_context(values: list[str], *, limit: int, metric: str = "sales") -> dict[str, object]:
    rows = [{"city": city, metric: 1000 - index * 50} for index, city in enumerate(values)]
    return build_analysis_context(
        {
            "success": True,
            "run_id": "run_previous",
            "dataset_id": "ds",
            "question": "按城市看销售额排名前 5。",
            "logic_form": {
                "task_type": "ranking",
                "operation": "ranking",
                "metric": metric,
                "group_by": "city",
                "filters": {},
                "parameters": {"table": "sales", "metric": metric, "dimension": "city", "limit": limit},
            },
            "result": {"columns": ["city", metric], "rows": rows},
        },
        original_question="按城市看销售额排名前 5。",
    )


def _sales_frame() -> pd.DataFrame:
    rows = []
    for city_index, city in enumerate(["上海", "北京", "广州", "深圳", "杭州", "苏州"]):
        for month_index, month in enumerate(["2026-01", "2026-02"]):
            rows.append(
                {
                    "city": city,
                    "month": month,
                    "sales": 100 + city_index * 10 + month_index,
                    "amount": 200 + city_index * 10 + month_index,
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
