"""Failing coverage for TopN -> filtered drilldown follow-up semantics."""

from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.output.response_builder import build_response
from data_agent_core.output.text_answer_framework import apply_text_answer_framework
from data_agent_core.result_artifacts import resolve_followup_referent
from data_agent_core.task_contract_builder import apply_referent_contract
from data_agent_core.task_execution_contracts import TaskExecutionContract, verify_task_execution_contract
from data_agent_core.verifier.rule_checker import verify_execution


class TopNFilterDrilldownFollowupTest(unittest.TestCase):
    def test_first_turn_topn_artifact_records_ranking_scope(self) -> None:
        question = "销售额 Top 5 城市是哪些？"
        rows = [
            {"city": "深圳", "order_amount": 920},
            {"city": "上海", "order_amount": 870},
            {"city": "杭州", "order_amount": 760},
            {"city": "北京", "order_amount": 650},
            {"city": "广州", "order_amount": 610},
        ]
        response = _build_topn_response(question=question, rows=rows, limit=5)

        artifact = response["debug"].get("result_artifacts") or {}
        self.assertEqual("order_amount", artifact.get("metric"))
        self.assertEqual("order_amount", artifact.get("metric_column"))
        self.assertEqual("city", artifact.get("dimension"))
        self.assertEqual("city", artifact.get("dimension_column"))
        self.assertEqual(5, artifact.get("requested_n"))
        self.assertEqual("desc", artifact.get("sort_order"))
        self.assertEqual(rows, artifact.get("result_rows"))
        self.assertEqual(["深圳", "上海", "杭州", "北京", "广州"], [item["value"] for item in artifact.get("top_objects") or []])

    def test_rank_one_city_product_drilldown_contract_switches_dimension_and_keeps_city_filter(self) -> None:
        context = _ranking_context(["深圳", "上海", "杭州"], metric="order_amount", limit=3)
        question = "只看排名第一的城市，它下面哪些产品销售额最高？"

        resolved = resolve_followup_referent(question, context)
        self.assertTrue(resolved["resolved"], resolved)
        self.assertEqual(["深圳"], resolved["referent_values"])
        self.assertEqual("order_amount", resolved["metric"])

        actions = plan_followup_actions(question, context)
        self.assertTrue(actions, "drilldown_referent_missing: follow-up planner should emit a drilldown action")
        contract = actions[0].get("referent_contract") or {}
        action_parameters = contract.get("action_parameters") or {}

        self.assertEqual("drilldown_followup", contract.get("capability_family"))
        self.assertEqual(["深圳"], contract.get("referent_values"))
        self.assertEqual("order_amount", action_parameters.get("metric"))
        self.assertEqual("product", action_parameters.get("dimension"))
        self.assertEqual({"city": "深圳"}, action_parameters.get("merged_filters"))

    def test_rank_one_city_product_drilldown_execution_is_not_global_product_ranking(self) -> None:
        context = _ranking_context(["深圳", "上海", "杭州"], metric="order_amount", limit=3)
        question = "只看排名第一的城市，它下面哪些产品销售额最高？"
        actions = plan_followup_actions(question, context)
        self.assertTrue(actions, "drilldown_referent_missing: follow-up planner should emit a drilldown action")

        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="order_amount",
            group_by="product",
            filters={},
            parameters={"table": "sales", "metric": "order_amount", "dimension": "product", "limit": 2, "sort_order": "desc"},
            output_format={"answer_type": "table"},
        )
        apply_referent_contract(logic, actions[0]["referent_contract"])
        plan = build_analysis_plan(logic, question=question)
        result = execute_plan(plan, {"tables": {"sales": _sales_frame()}, "primary_table": "sales"})
        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual({"city": "深圳"}, logic.filters)
        self.assertEqual("product", logic.parameters.get("dimension"))
        self.assertEqual([{"product": "数据治理", "order_amount": 500}, {"product": "云服务", "order_amount": 420}], result.rows)
        self.assertNotEqual([{"product": "硬件", "order_amount": 999}, {"product": "数据治理", "order_amount": 500}], result.rows)

    def test_top3_cities_plus_region_drilldown_artifact_keeps_merged_scope(self) -> None:
        context = _ranking_context(["深圳", "上海", "杭州"], metric="order_amount", limit=3)
        question = "这些城市里，华东区域的产品销售额排名如何？"
        actions = plan_followup_actions(question, context)
        self.assertTrue(actions, "drilldown_referent_missing: follow-up planner should emit a drilldown action")

        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="order_amount",
            group_by="product",
            filters={"region": "华东"},
            parameters={"table": "sales", "metric": "order_amount", "dimension": "product", "limit": 3, "sort_order": "desc"},
            output_format={"answer_type": "table"},
        )
        apply_referent_contract(logic, actions[0]["referent_contract"])
        plan = build_analysis_plan(logic, question=question)
        result = execute_plan(plan, {"tables": {"sales": _sales_frame()}, "primary_table": "sales"})
        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_top3_region_drilldown",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        ).to_dict()

        self.assertEqual({"region": "华东", "city": ["深圳", "上海", "杭州"]}, logic.filters)
        self.assertEqual("product", logic.parameters.get("dimension"))
        for row in result.rows:
            self.assertNotIn(row.get("city"), {"北京", "广州"})
            self.assertNotEqual("华南", row.get("region"))
        artifact = response["debug"].get("result_artifacts") or {}
        self.assertEqual({"city": ["深圳", "上海", "杭州"], "region": "华东"}, artifact.get("filters"))
        self.assertEqual("drilldown_followup", response.get("contract_family"))

    def test_drilldown_followup_contract_requires_previous_referent_metric_dimension_filters_and_rows(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="order_amount",
            group_by="product",
            filters={"city": "深圳"},
            parameters={
                "table": "sales",
                "metric": "order_amount",
                "dimension": "product",
                "requires_previous_artifact": True,
                "referent_dimension": "city",
                "referent_values": ["深圳"],
                "referent_source": "result_artifact:ranking:top_objects:rank_1",
            },
            output_format={"answer_type": "table"},
        )

        contract = build_analysis_plan(logic, question="只看排名第一的城市，它下面哪些产品销售额最高？").task_contract
        self.assertEqual("drilldown_followup", contract.task_family)
        self.assertEqual(["深圳"], contract.referent_values)
        self.assertEqual("order_amount", contract.metric)
        self.assertEqual("product", contract.dimension)
        self.assertEqual({"city": "深圳"}, contract.verification_rules.get("merged_filters"))
        self.assertIn("previous_referent_values", contract.required_answer_elements)
        self.assertIn("output_ranking_rows", contract.required_answer_elements)

    def test_missing_previous_artifact_uses_drilldown_referent_missing_violation(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_drilldown_missing_referent",
            task_family="drilldown_followup",
            metric="order_amount",
            dimension="product",
            requires_previous_artifact=True,
            referent_dimension="city",
            referent_values=[],
            verification_rules={"requires_execution_success": True, "requires_referent_values": True},
        )
        report = verify_task_execution_contract(
            contract,
            ExecutionResult(backend="unit-test", success=True, columns=["product", "order_amount"], rows=[{"product": "数据治理", "order_amount": 500}], value=[]),
        )

        codes = {item.code for item in report.violations}
        self.assertIn("drilldown_referent_missing", codes)

    def test_missing_new_drilldown_dimension_requires_clarification(self) -> None:
        contract = TaskExecutionContract(
            contract_id="contract_drilldown_missing_dimension",
            task_family="drilldown_followup",
            metric="order_amount",
            dimension="",
            requires_previous_artifact=True,
            referent_dimension="city",
            referent_values=["深圳"],
            verification_rules={"requires_drilldown_dimension": True},
            insufficiency_policy="needs_clarification",
        )
        report = verify_task_execution_contract(
            contract,
            ExecutionResult(backend="unit-test", success=True, columns=["city", "order_amount"], rows=[{"city": "深圳", "order_amount": 920}], value=[]),
        )

        codes = {item.code for item in report.violations}
        self.assertIn("drilldown_dimension_missing", codes)
        self.assertTrue(any(item.severity == "needs_clarification" for item in report.violations))

    def test_oracle_fails_when_city_filter_is_not_applied(self) -> None:
        result = build_oracle_result(
            _drilldown_contract(),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["product", "order_amount"],
                rows=[{"product": "硬件", "order_amount": 999}, {"product": "数据治理", "order_amount": 500}],
                value={"filters": {"region": "华东"}},
            ),
        )

        self.assertTrue(result.oracle_available)
        self.assertFalse(result.passed)
        self.assertIn("drilldown_filter_missing", result.issue_codes)
        self.assertIn("drilldown_scope_missing", result.issue_codes)

    def test_oracle_fails_when_region_filter_is_not_applied(self) -> None:
        result = build_oracle_result(
            _drilldown_contract(expected_region=True),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["product", "order_amount", "city", "region"],
                rows=[{"product": "云服务", "order_amount": 430, "city": "上海", "region": "华南"}],
                value={"filters": {"city": ["深圳", "上海", "杭州"]}},
            ),
        )

        self.assertTrue(result.oracle_available)
        self.assertFalse(result.passed)
        self.assertIn("drilldown_filter_missing", result.issue_codes)

    def test_oracle_fails_when_actual_rows_are_still_city_ranking(self) -> None:
        result = build_oracle_result(
            _drilldown_contract(),
            ExecutionResult(
                backend="unit-test",
                success=True,
                columns=["city", "order_amount"],
                rows=[{"city": "深圳", "order_amount": 920}],
                value={"filters": {"city": "深圳"}},
            ),
        )

        self.assertTrue(result.oracle_available)
        self.assertFalse(result.passed)
        self.assertIn("drilldown_wrong_dimension", result.issue_codes)

    def test_response_first_sentence_exposes_rank_one_city_scope(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "已完成排序。",
                "logic_form": {
                    "operation": "ranking",
                    "filters": {"city": "深圳"},
                    "parameters": {"metric": "order_amount", "dimension": "product", "referent_dimension": "city", "referent_values": ["深圳"]},
                    "task_contract": {"task_family": "drilldown_followup", "metric": "order_amount", "dimension": "product", "referent_dimension": "city", "referent_values": ["深圳"]},
                },
                "result": {"columns": ["product", "order_amount"], "rows": [{"product": "数据治理", "order_amount": 500}, {"product": "云服务", "order_amount": 420}]},
            },
            question="只看排名第一的城市，它下面哪些产品销售额最高？",
        )

        first = response["answer"].split("。", 1)[0]
        self.assertTrue(first.startswith("排名第一的城市深圳中，产品销售额最高的是数据治理"), response["answer"])
        self.assertNotIn("可以进一步分析", first)
        self.assertIn("深圳", first)

    def test_response_first_sentence_exposes_top3_city_and_region_scope(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "已完成排序。",
                "logic_form": {
                    "operation": "ranking",
                    "filters": {"city": ["深圳", "上海", "杭州"], "region": "华东"},
                    "parameters": {"metric": "order_amount", "dimension": "product", "referent_dimension": "city", "referent_values": ["深圳", "上海", "杭州"]},
                    "task_contract": {"task_family": "drilldown_followup", "metric": "order_amount", "dimension": "product", "referent_dimension": "city", "referent_values": ["深圳", "上海", "杭州"]},
                },
                "result": {"columns": ["product", "order_amount"], "rows": [{"product": "数据治理", "order_amount": 830}, {"product": "云服务", "order_amount": 710}]},
            },
            question="这些城市里，华东区域的产品销售额排名如何？",
        )

        first = response["answer"].split("。", 1)[0]
        self.assertTrue(first.startswith("在 Top3 城市且华东区域内，产品销售额排名为"), response["answer"])
        self.assertIn("深圳", response["answer"])
        self.assertIn("上海", response["answer"])
        self.assertIn("杭州", response["answer"])


def _build_topn_response(*, question: str, rows: list[dict[str, object]], limit: int) -> dict[str, object]:
    logic = LogicForm(
        task_type="ranking",
        operation="ranking",
        metric="order_amount",
        group_by="city",
        filters={},
        parameters={"table": "sales", "metric": "order_amount", "dimension": "city", "aggregation": "sum", "sort_order": "desc", "limit": limit},
        output_format={"answer_type": "table"},
    )
    plan = build_analysis_plan(logic, question=question)
    execution = ExecutionResult(backend="pandas", success=True, columns=["city", "order_amount"], rows=rows, value=rows)
    verification = verify_execution(execution, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
    return build_response(
        run_id="run_topn_filter_drilldown_first_turn",
        user_question=UserQuestion(dataset_id="ds", question=question),
        plan=plan,
        execution_result=execution,
        verification=verification,
    ).to_dict()


def _ranking_context(values: list[str], *, metric: str, limit: int) -> dict[str, object]:
    rows = [{"city": city, metric: amount} for city, amount in zip(values, [920, 870, 760, 650, 610])]
    return build_analysis_context(
        {
            "success": True,
            "run_id": "run_previous_topn_city",
            "dataset_id": "ds",
            "question": f"销售额 Top {limit} 城市是哪些？",
            "logic_form": {
                "task_type": "ranking",
                "operation": "ranking",
                "metric": metric,
                "group_by": "city",
                "filters": {},
                "parameters": {"table": "sales", "metric": metric, "dimension": "city", "limit": limit, "sort_order": "desc"},
            },
            "result": {"columns": ["city", metric], "rows": rows},
        },
        original_question=f"销售额 Top {limit} 城市是哪些？",
    )


def _sales_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"city": "深圳", "region": "华东", "product": "数据治理", "order_amount": 500},
            {"city": "深圳", "region": "华东", "product": "云服务", "order_amount": 420},
            {"city": "深圳", "region": "华南", "product": "安全", "order_amount": 410},
            {"city": "上海", "region": "华东", "product": "数据治理", "order_amount": 330},
            {"city": "上海", "region": "华南", "product": "云服务", "order_amount": 430},
            {"city": "杭州", "region": "华东", "product": "云服务", "order_amount": 290},
            {"city": "北京", "region": "华东", "product": "硬件", "order_amount": 999},
            {"city": "广州", "region": "华南", "product": "数据治理", "order_amount": 888},
        ]
    )


def _drilldown_contract(*, expected_region: bool = False) -> TaskExecutionContract:
    merged_filters: dict[str, object] = {"city": ["深圳", "上海", "杭州"] if expected_region else "深圳"}
    if expected_region:
        merged_filters["region"] = "华东"
    expected_rows = (
        [{"product": "数据治理", "order_amount": 830}, {"product": "云服务", "order_amount": 290}]
        if expected_region
        else [{"product": "数据治理", "order_amount": 500}, {"product": "云服务", "order_amount": 420}]
    )
    return TaskExecutionContract(
        contract_id="contract_topn_filter_drilldown_followup",
        task_family="drilldown_followup",
        metric="order_amount",
        dimension="product",
        required_n=2,
        sort_order="desc",
        requires_previous_artifact=True,
        referent_dimension="city",
        referent_values=["深圳", "上海", "杭州"] if expected_region else ["深圳"],
        verification_rules={
            "expected_result": {
                "task_family": "drilldown_followup",
                "metric": "order_amount",
                "drilldown_dimension": "product",
                "referent_dimension": "city",
                "referent_values": ["深圳", "上海", "杭州"] if expected_region else ["深圳"],
                "merged_filters": merged_filters,
                "rows": expected_rows,
            },
            "operation": "filtered_metric_ranking",
            "capability_family": "drilldown_followup",
        },
    )


if __name__ == "__main__":
    unittest.main()
