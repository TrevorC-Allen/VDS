from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.output.response_builder import build_response
from data_agent_core.task_execution_contracts import TaskExecutionContract, build_task_execution_contract


QUESTION = "这些 Top 城市分别占总销售额多少？"
TOP_ROWS = [
    {"city": "上海", "sales": 325},
    {"city": "北京", "sales": 310},
    {"city": "深圳", "sales": 288},
]
ALL_CITY_TOTAL = 1103


class ContributionFollowupUsesPreviousTopObjectsTest(unittest.TestCase):
    def test_followup_action_inherits_topn_artifact_and_routes_to_contribution_share(self) -> None:
        actions = plan_followup_actions(QUESTION, _ranking_context(TOP_ROWS))

        self.assertEqual(1, len(actions))
        action = actions[0]
        self.assertEqual("top_k_share", action["operation"])
        self.assertEqual("ranked_entity_share", action["action_id"])
        self.assertEqual("share_followup", action["capability_family"])

        referent_contract = action["referent_contract"]
        self.assertEqual("city", referent_contract["referent_dimension"])
        self.assertEqual(["上海", "北京", "深圳"], referent_contract["referent_values"])
        self.assertEqual("sales", referent_contract["action_parameters"]["metric"])
        self.assertEqual("sales", referent_contract["action_parameters"]["share_metric"])
        self.assertEqual("sales_share", referent_contract["action_parameters"]["share_column"])
        self.assertEqual(["orders", "customers"], referent_contract["inherited_parameters"]["source_tables"])
        self.assertEqual("customer_id", referent_contract["inherited_parameters"]["join_plan"]["left_key"])

    def test_contribution_contract_requires_referent_metric_denominator_and_share_columns(self) -> None:
        contract = build_task_execution_contract(_contribution_logic_form(), question=QUESTION)

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertIn(contract.task_family, {"contribution", "share", "contribution_followup"})
        self.assertTrue(contract.requires_previous_artifact)
        self.assertEqual("previous_top3", contract.referent_artifact_id)
        self.assertEqual("city", contract.referent_dimension)
        self.assertEqual(["上海", "北京", "深圳"], contract.referent_values)
        self.assertEqual("sales", contract.metric)
        self.assertIn("sales", contract.required_output_columns)
        self.assertIn("total_sales", contract.required_output_columns)
        self.assertIn("sales_share", contract.required_output_columns)
        self.assertEqual("sales", contract.verification_rules["numerator_metric"])
        self.assertEqual("total_sales", contract.verification_rules["denominator_total_metric"])
        self.assertEqual("sales_share", contract.verification_rules["share_column"])

    def test_oracle_normalizes_contribution_followup_rows_and_allows_share_tolerance(self) -> None:
        result = build_oracle_result(
            _contribution_contract(_expected_contribution_result()),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "metric_value", "total_metric_value", "share"],
                rows=[
                    {"city": "上海", "metric_value": 325, "total_metric_value": ALL_CITY_TOTAL, "share": 29.464},
                    {"city": "北京", "metric_value": 310, "total_metric_value": ALL_CITY_TOTAL, "share": 28.105},
                    {"city": "深圳", "metric_value": 288, "total_metric_value": ALL_CITY_TOTAL, "share": 26.111},
                ],
            ),
        )

        self.assertTrue(result.oracle_available)
        self.assertTrue(result.passed, result.issue_codes)
        self.assertEqual("contribution_followup", (result.expected_result or {}).get("task_family"))
        actual_items = (result.actual_result or {}).get("items") or []
        self.assertEqual(["上海", "北京", "深圳"], [item["value"] for item in actual_items])

    def test_oracle_flags_missing_share_field_with_specific_issue_code(self) -> None:
        result = build_oracle_result(
            _contribution_contract(_expected_contribution_result()),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "metric_value", "total_metric_value"],
                rows=[
                    {"city": "上海", "metric_value": 325, "total_metric_value": ALL_CITY_TOTAL},
                    {"city": "北京", "metric_value": 310, "total_metric_value": ALL_CITY_TOTAL},
                    {"city": "深圳", "metric_value": 288, "total_metric_value": ALL_CITY_TOTAL},
                ],
            ),
        )

        self.assertTrue(result.oracle_available)
        self.assertFalse(result.passed)
        self.assertIn("contribution_share_missing", result.issue_codes)

    def test_response_first_sentence_directly_lists_each_top_city_share(self) -> None:
        logic = _contribution_logic_form()
        plan = build_analysis_plan(logic, question=QUESTION)
        response = build_response(
            run_id="run_contribution_followup",
            user_question=UserQuestion(dataset_id="ds", question=QUESTION),
            plan=plan,
            execution_result=ExecutionResult(
                backend="unit-test",
                success=True,
                value=83.68,
                columns=[],
                rows=[],
            ),
            verification=VerificationResult(passed=True, semantic_status="passed"),
        ).to_dict()

        answer = str(response["answer"] or "")
        first_sentence = answer.split("。", 1)[0]
        self.assertIn("上海", first_sentence)
        self.assertIn("29.46%", first_sentence)
        self.assertIn("北京", first_sentence)
        self.assertIn("28.10%", first_sentence)
        self.assertIn("深圳", first_sentence)
        self.assertIn("26.11%", first_sentence)
        self.assertNotIn("Top 3 城市是", first_sentence)
        self.assertNotIn("可以进一步分析", answer)

    def test_response_formats_small_share_values_as_percent_not_ratio(self) -> None:
        question = "各商品销售额占比是多少？销售额按 Quantity * UnitPrice 算。"
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="Sales",
            group_by="Description",
            parameters={
                "table": "orders",
                "metric": "Sales",
                "share_metric": "Sales",
                "share_of_total": True,
                "share_column": "Sales_share",
                "dimension": "Description",
                "group_by": "Description",
                "aggregation": "sum",
            },
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic, question=question)

        response = build_response(
            run_id="run_small_share_display",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=ExecutionResult(
                backend="unit-test",
                success=True,
                value=[
                    {
                        "Description": "Tiny item",
                        "Sales": 290.8,
                        "total_Sales": 9_747_747.934,
                        "Sales_share": 0.0029832531777488204,
                    }
                ],
                columns=["Description", "Sales", "total_Sales", "Sales_share"],
                rows=[
                    {
                        "Description": "Tiny item",
                        "Sales": 290.8,
                        "total_Sales": 9_747_747.934,
                        "Sales_share": 0.0029832531777488204,
                    }
                ],
            ),
            verification=VerificationResult(passed=True, semantic_status="passed"),
        ).to_dict()

        answer = str(response["answer"] or "")
        self.assertIn("0.00%", answer)
        self.assertNotIn("29.83%", answer)


def _ranking_context(rows: list[dict[str, object]]) -> dict[str, object]:
    return build_analysis_context(
        {
            "success": True,
            "run_id": "run_previous_top",
            "dataset_id": "ds",
            "question": "销售额 Top 3 城市是哪些？",
            "logic_form": {
                "task_type": "ranking",
                "operation": "ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {},
                "source_tables": ["orders", "customers"],
                "join_plan": {
                    "trusted": True,
                    "left_table": "orders",
                    "right_table": "customers",
                    "left_key": "customer_id",
                    "right_key": "customer_id",
                    "relationship": "many_to_one",
                },
                "parameters": {
                    "table": "orders",
                    "metric": "sales",
                    "dimension": "city",
                    "aggregation": "sum",
                    "sort_order": "desc",
                    "limit": 3,
                    "source_tables": ["orders", "customers"],
                    "join_plan": {
                        "trusted": True,
                        "left_table": "orders",
                        "right_table": "customers",
                        "left_key": "customer_id",
                        "right_key": "customer_id",
                        "relationship": "many_to_one",
                    },
                },
            },
            "result": {"columns": ["city", "sales"], "rows": rows},
        },
        original_question="销售额 Top 3 城市是哪些？",
    )


def _contribution_logic_form() -> LogicForm:
    return LogicForm(
        task_type="aggregation",
        operation="top_k_share",
        metric="sales",
        group_by="city",
        filters={"city": ["上海", "北京", "深圳"]},
        parameters={
            "table": "orders",
            "metric": "sales",
            "share_metric": "sales",
            "dimension": "city",
            "limit": 3,
            "requires_previous_artifact": True,
            "referent_artifact_id": "previous_top3",
            "referent_dimension": "city",
            "referent_values": ["上海", "北京", "深圳"],
            "referent_policy": "must_filter_to_previous_result_objects",
            "share_column": "sales_share",
            "total_metric_column": "total_sales",
        },
        output_format={"answer_type": "table"},
    )


def _contribution_contract(expected: dict[str, object]) -> TaskExecutionContract:
    return TaskExecutionContract(
        contract_id="contract_contribution_followup",
        task_family="topn",
        metric="sales",
        dimension="city",
        requires_previous_artifact=True,
        referent_artifact_id="previous_top3",
        referent_dimension="city",
        referent_values=["上海", "北京", "深圳"],
        verification_rules={
            "expected_result": expected,
            "operation": "top_k_share",
            "capability_family": "contribution_followup",
            "share_tolerance": 0.01,
        },
    )


def _expected_contribution_result() -> dict[str, object]:
    return {
        "task_family": "contribution_followup",
        "dimension": "city",
        "metric": "sales",
        "total_metric_value": ALL_CITY_TOTAL,
        "items": [
            {"value": "上海", "metric_value": 325, "total_metric_value": ALL_CITY_TOTAL, "share": 325 / ALL_CITY_TOTAL * 100},
            {"value": "北京", "metric_value": 310, "total_metric_value": ALL_CITY_TOTAL, "share": 310 / ALL_CITY_TOTAL * 100},
            {"value": "深圳", "metric_value": 288, "total_metric_value": ALL_CITY_TOTAL, "share": 288 / ALL_CITY_TOTAL * 100},
        ],
    }


if __name__ == "__main__":
    unittest.main()
