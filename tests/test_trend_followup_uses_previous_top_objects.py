from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.result_artifacts import resolve_followup_referent
from data_agent_core.task_contract_builder import apply_referent_contract
from data_agent_core.task_execution_contracts import build_task_execution_contract
from data_agent_core.verifier.rule_checker import verify_execution


class TrendFollowupUsesPreviousTopObjectsTest(unittest.TestCase):
    def test_top3_trend_followup_filters_to_previous_top_objects(self) -> None:
        context = _ranking_context(
            [
                {"city": "上海", "amount": 325},
                {"city": "北京", "amount": 310},
                {"city": "深圳", "amount": 288},
            ]
        )
        question = "这些 Top 对象按月份的金额趋势怎么样？"

        resolved = resolve_followup_referent(question, context)
        self.assertTrue(resolved["resolved"])
        self.assertEqual(["上海", "北京", "深圳"], resolved["referent_values"])
        self.assertEqual("city", resolved["referent_dimension"])

        actions = plan_followup_actions(question, context)
        self.assertEqual(1, len(actions))
        contract = actions[0]["referent_contract"]
        self.assertEqual(["上海", "北京", "深圳"], contract["referent_values"])

        result, verification = _run_trend(question, contract)
        codes = {item["code"] for item in verification.contract_report["violations"]}
        observed_cities = {row["city"] for row in result.rows}

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual("passed", verification.semantic_status)
        self.assertNotIn("TREND_EMPTY_RESULT", codes)
        self.assertEqual({"上海", "北京", "深圳"}, observed_cities)
        self.assertNotIn("广州", observed_cities)
        self.assertEqual({"上海", "北京", "深圳"}, set(verification.task_contract["referent_values"]))
        self.assertEqual("city", verification.task_contract["referent_dimension"])
        self.assertEqual(["上海", "北京", "深圳"], verification.task_contract["verification_rules"]["candidate_set"]["values"])

    def test_top1_trend_followup_allows_single_previous_top_object(self) -> None:
        context = _ranking_context([{"city": "上海", "amount": 325}], limit=1)
        question = "这些 Top 对象按月份金额趋势怎么样？"
        actions = plan_followup_actions(question, context)

        self.assertEqual(1, len(actions))
        result, verification = _run_trend(question, actions[0]["referent_contract"])

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual(["上海"], verification.task_contract["referent_values"])
        self.assertEqual({"上海"}, {row["city"] for row in result.rows})

    def test_missing_referent_does_not_fall_back_to_global_trend(self) -> None:
        question = "这些 Top 对象按月份的金额趋势怎么样？"
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="amount",
            group_by="month",
            filters={},
            parameters={"table": "orders", "metric": "amount", "dimension": "month"},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic, question=question)
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["month", "amount"],
            rows=[{"month": "2026-01", "amount": 999}],
            value=[{"month": "2026-01", "amount": 999}],
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        codes = {item["code"] for item in verification.contract_report["violations"]}

        self.assertIn("REFERENT_ARTIFACT_MISSING", codes)
        self.assertIn("REFERENT_VALUES_MISSING", codes)
        self.assertIn(verification.semantic_status, {"needs_clarification", "failed"})
        self.assertFalse(verification.passed)

    def test_referent_contract_carries_multi_table_join_context(self) -> None:
        context = _ranking_context(
            [
                {"city": "上海", "amount": 325},
                {"city": "北京", "amount": 310},
                {"city": "深圳", "amount": 288},
            ],
            join_plan={
                "trusted": True,
                "left_table": "orders",
                "right_table": "customers",
                "left_key": "customer_id",
                "right_key": "customer_id",
                "relationship": "many_to_one",
            },
            source_tables=["orders", "customers"],
        )
        question = "这些 Top 对象按月份的金额趋势怎么样？"
        actions = plan_followup_actions(question, context)
        contract = actions[0]["referent_contract"]

        self.assertEqual(["orders", "customers"], contract["inherited_parameters"]["source_tables"])
        self.assertEqual("customers", contract["inherited_parameters"]["join_plan"]["right_table"])

        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="amount",
            group_by="month",
            filters={},
            parameters={"table": "orders", "metric": "amount", "dimension": "month"},
            output_format={"answer_type": "table"},
        )
        apply_referent_contract(logic, contract)

        self.assertEqual(["orders", "customers"], logic.parameters["source_tables"])
        self.assertEqual("customers", logic.parameters["join_plan"]["right_table"])
        self.assertEqual(["上海", "北京", "深圳"], logic.filters["city"])

    def test_file_scope_overview_is_not_previous_referent(self) -> None:
        question = "不直接下结论，先概览这些客户订单收入文件的数据结构。"
        contract = build_task_execution_contract(
            {
                "task_type": "overview",
                "operation": "multi_table_dataset_overview",
                "source_tables": ["orders", "customers"],
                "parameters": {},
                "output_format": {"answer_type": "overview"},
            },
            question=question,
        )

        self.assertIsNotNone(contract)
        self.assertIn(contract.task_family, {"overview", "multi_file_overview"})
        self.assertFalse(contract.requires_previous_artifact)
        self.assertIsNone(contract.referent_artifact_id)
        self.assertEqual([], contract.referent_values)


def _ranking_context(
    rows: list[dict[str, object]],
    *,
    limit: int = 3,
    join_plan: dict[str, object] | None = None,
    source_tables: list[str] | None = None,
) -> dict[str, object]:
    return build_analysis_context(
        {
            "success": True,
            "run_id": "run_previous_top",
            "dataset_id": "ds",
            "question": "按城市汇总金额，Top 3 是哪些？",
            "logic_form": {
                "task_type": "ranking",
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "city",
                "filters": {},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "city",
                    "aggregation": "sum",
                    "sort_order": "desc",
                    "limit": limit,
                    **({"join_plan": join_plan} if join_plan else {}),
                    **({"source_tables": source_tables} if source_tables else {}),
                },
                **({"source_tables": source_tables} if source_tables else {}),
                **({"join_plan": join_plan} if join_plan else {}),
            },
            "result": {"columns": ["city", "amount"], "rows": rows},
        },
        original_question="按城市汇总金额，Top 3 是哪些？",
    )


def _run_trend(question: str, contract: dict[str, object]) -> tuple[ExecutionResult, object]:
    logic = LogicForm(
        task_type="aggregation",
        operation="aggregation",
        metric="amount",
        group_by="month",
        filters={},
        parameters={"table": "orders", "metric": "amount", "dimension": "month"},
        output_format={"answer_type": "table"},
    )
    apply_referent_contract(logic, contract)
    plan = build_analysis_plan(logic, question=question)
    result = execute_plan(plan, {"tables": {"orders": _orders_frame()}, "primary_table": "orders"})
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
    return result, verification


def _orders_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"month": "2026-01", "city": "上海", "amount": 120},
            {"month": "2026-02", "city": "上海", "amount": 205},
            {"month": "2026-01", "city": "北京", "amount": 150},
            {"month": "2026-02", "city": "北京", "amount": 160},
            {"month": "2026-01", "city": "深圳", "amount": 100},
            {"month": "2026-02", "city": "深圳", "amount": 188},
            {"month": "2026-01", "city": "广州", "amount": 999},
        ]
    )


if __name__ == "__main__":
    unittest.main()
