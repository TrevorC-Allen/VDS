from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.semantic_contract import (
    build_canonical_semantic_contract,
    build_execution_spec_from_semantic_contract,
    build_lightweight_schema_semantic_profile,
)
from data_agent_core.executors import pandas_executor
from agent_runtime.data_agent_tool_impl import runtime_verify_results
from data_agent_core.output.response_builder import build_response
from data_agent_core.verifier.rule_checker import verify_execution
from scripts.run_agent_random_conversation_eval import ScenarioResult, TurnEvidence, TurnPlan, _coverage_summary, _turn_issues


class SemanticContractInstrumentationTest(unittest.TestCase):
    def _trace(self, **overrides: object) -> dict[str, object]:
        trace: dict[str, object] = {
            "operation": "aggregation",
            "metric_columns": [],
            "aggregation": None,
            "formula": None,
            "groupby_columns": [],
            "filters_applied": [],
            "comparison_type": None,
            "time_column": None,
            "time_grain": None,
            "ranking": {"order": "desc", "limit": None},
            "source": "pandas_executor",
            "trace_status": "complete",
            "trace_source": "actual_executor",
            "trace_is_actual": True,
        }
        trace.update(overrides)
        return trace

    def test_analysis_plan_attaches_topn_task_contract(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="sales",
            group_by="city",
            parameters={"metric": "sales", "dimension": "city", "limit": 3},
            output_format={"answer_type": "table"},
        )

        plan = build_analysis_plan(logic)

        self.assertIsNotNone(plan.task_contract)
        self.assertEqual("topn", plan.task_contract.task_family)
        self.assertEqual(3, plan.task_contract.required_n)
        self.assertEqual("topn", logic.task_contract["task_family"])
        self.assertEqual("ranking", plan.semantic_contract["task_type"])
        self.assertEqual("ranking", plan.semantic_contract["capability_family"])

    def test_canonical_contract_promotes_parameter_metric_and_dimension(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            parameters={"metric": "order_amount", "dimension": "city", "limit": 1, "aggregation": "sum"},
            output_format={"answer_type": "table"},
        )

        plan = build_analysis_plan(logic, question="订单金额最高的城市是哪个？")

        self.assertEqual("order_amount", plan.logic_form.metric)
        self.assertEqual("city", plan.logic_form.group_by)
        self.assertEqual("order_amount", plan.semantic_contract["metrics"][0]["display_name"])
        self.assertEqual("city", plan.semantic_contract["dimensions"][0]["resolved_column"])

    def test_schema_value_linker_adds_explicit_filter_to_contract_and_plan(self) -> None:
        df = pd.DataFrame({"country": ["France", "Germany", "France"], "sales": [10, 20, 30]})
        schema_profile = build_lightweight_schema_semantic_profile({"tables": {"sales": df}})
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="sales",
            parameters={"table": "sales", "metric": "sales", "aggregation": "sum"},
            output_format={"answer_type": "number"},
        )

        contract = build_canonical_semantic_contract(
            question="法国销售额是多少？ France sales total?",
            selected_logic_form=logic,
            deterministic_logic_form=logic,
            schema_profile=schema_profile,
        )
        plan = build_analysis_plan(logic, question="France sales total?", semantic_contract=contract)

        self.assertEqual("country", contract.filters[0].resolved_column)
        self.assertEqual(["France"], contract.filters[0].values)
        self.assertEqual("France", plan.logic_form.filters["country"])

    def test_entity_quantity_prefers_schema_entity_id_over_row_count(self) -> None:
        df = pd.DataFrame({"客户ID": ["C1", "C1", "C2"], "销售额": [10, 20, 30]})
        schema_profile = build_lightweight_schema_semantic_profile({"tables": {"customers": df}})
        logic = LogicForm(
            task_type="aggregation",
            operation="row_count",
            metric="row_count",
            parameters={"metric": "row_count", "aggregation": "count"},
            output_format={"answer_type": "number"},
        )

        contract = build_canonical_semantic_contract(
            question="客户数量是多少？",
            selected_logic_form=logic,
            deterministic_logic_form=logic,
            schema_profile=schema_profile,
        )
        plan = build_analysis_plan(logic, question="客户数量是多少？", semantic_contract=contract)

        self.assertEqual("entity_count", contract.metrics[0].semantic_type)
        self.assertEqual(["客户ID"], contract.metrics[0].resolved_columns)
        self.assertEqual("客户ID", plan.logic_form.metric)
        self.assertEqual("nunique", plan.logic_form.parameters["aggregation"])

    def test_pairwise_gap_contract_uses_category_values_not_adjacent_time(self) -> None:
        df = pd.DataFrame({"country": ["France", "Germany", "Spain"], "sales": [10, 20, 30], "month": ["2024-01", "2024-01", "2024-01"]})
        schema_profile = build_lightweight_schema_semantic_profile({"tables": {"sales": df}})
        logic = LogicForm(
            task_type="comparison",
            operation="aggregation",
            metric="sales",
            parameters={"table": "sales", "metric": "sales", "aggregation": "sum"},
            output_format={"answer_type": "number"},
        )

        contract = build_canonical_semantic_contract(
            question="Germany and France sales gap?",
            selected_logic_form=logic,
            deterministic_logic_form=logic,
            schema_profile=schema_profile,
        )
        plan = build_analysis_plan(logic, question="Germany and France sales gap?", semantic_contract=contract)

        self.assertEqual("pairwise_gap", contract.comparison.type)
        self.assertEqual("country", contract.comparison.dimension_ref)
        self.assertEqual(["France", "Germany"], plan.logic_form.filters["country"])
        self.assertTrue(plan.logic_form.parameters["requires_gap_comparison"])

    def test_chinese_and_connective_does_not_force_pairwise_comparison(self) -> None:
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="sales",
            group_by="city",
            parameters={"metric": "sales", "dimension": "city", "aggregation": "sum"},
            output_format={"answer_type": "table"},
        )

        contract = build_canonical_semantic_contract(
            question="按城市和产品看销售额",
            selected_logic_form=logic,
            deterministic_logic_form=logic,
        )

        self.assertEqual("aggregation", contract.task_type)
        self.assertIsNone(contract.comparison)

    def test_trend_task_type_keeps_time_series_capability_when_physical_operation_is_aggregation(self) -> None:
        logic = LogicForm(
            task_type="trend",
            operation="aggregation",
            metric="Sales",
            group_by="month",
            parameters={
                "table": "orders",
                "metric": "Sales",
                "dimension": "month",
                "time_column": "InvoiceDate",
                "time_bucket": "month",
                "aggregation": "sum",
                "capability_family": "time_series",
            },
            output_format={"answer_type": "table"},
        )

        plan = build_analysis_plan(logic, question="按月看订单金额趋势")

        self.assertEqual("trend", plan.semantic_contract["task_type"])
        self.assertEqual("aggregation", plan.semantic_contract["physical_operation"])
        self.assertEqual("time_series", plan.semantic_contract["capability_family"])
        self.assertEqual("time_series", plan.constraints["generalization_contract"]["capability_family"])

    def test_verifier_fails_when_plan_omits_canonical_filter(self) -> None:
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="sales",
            parameters={"metric": "sales", "aggregation": "sum"},
            output_format={"answer_type": "number"},
        )
        plan = AnalysisPlan(
            plan_id="plan_missing_filter",
            logic_form=logic,
            semantic_contract={
                "contract_version": 1,
                "route": "test",
                "task_type": "aggregation",
                "capability_family": "metric_aggregation",
                "physical_operation": "aggregation",
                "metrics": [
                    {
                        "metric_id": "metric:sales",
                        "display_name": "sales",
                        "semantic_type": "measure",
                        "aggregation": "sum",
                        "resolved_columns": ["sales"],
                        "confidence": 0.95,
                        "evidence": ["test"],
                    }
                ],
                "dimensions": [],
                "filters": [
                    {
                        "dimension_id": "filter:country",
                        "display_name": "country",
                        "resolved_column": "country",
                        "operator": "eq",
                        "values": ["France"],
                        "confidence": 0.95,
                        "evidence": ["test"],
                    }
                ],
                "comparison": None,
                "time": None,
                "ranking": None,
                "evidence": {},
                "ambiguities": [],
                "validation_issues": [],
                "needs_clarification": False,
            },
        )
        execution_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["sales"],
            rows=[{"sales": 100}],
            value=100,
            execution_trace={
                "operation": "aggregation",
                "metric_columns": ["sales"],
                "aggregation": "sum",
                "formula": None,
                "groupby_columns": [],
                "filters_applied": [],
                "comparison_type": None,
                "time_column": None,
                "time_grain": None,
                "ranking": {"order": "desc", "limit": None},
                "source": "pandas_executor",
                "trace_status": "complete",
                "trace_source": "actual_executor",
                "trace_is_actual": True,
            },
        )

        verification = verify_execution(
            execution_result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question="France sales total?", execution_mode="dual"),
        )

        self.assertFalse(verification.passed)
        self.assertIn("Canonical semantic contract coverage failed.", verification.issues)
        self.assertTrue(any(item["type"] == "missing_filter" for item in verification.semantic_issues))

    def test_detail_lookup_actual_filter_trace_prevents_false_positive(self) -> None:
        df = pd.DataFrame({"country": ["DE", "FR"], "amount": [100, 200]})
        contract = {
            "contract_version": 1,
            "route": "test",
            "task_type": "detail_lookup",
            "capability_family": "detail_lookup",
            "physical_operation": "detail_lookup",
            "metrics": [],
            "dimensions": [],
            "filters": [
                {
                    "display_name": "country",
                    "resolved_column": "country",
                    "operator": "eq",
                    "values": ["FR"],
                    "confidence": 0.95,
                    "evidence": ["test"],
                }
            ],
            "comparison": None,
            "time": None,
            "ranking": None,
        }
        logic = LogicForm(task_type="detail_lookup", operation="detail_lookup", parameters={"table": "transactions", "limit": 20})
        plan = build_analysis_plan(logic, question="Show FR rows", semantic_contract=contract)

        result = pandas_executor.execute_plan(plan, {"tables": {"transactions": df}})
        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="Show FR rows"))

        self.assertEqual([{"country": "FR", "amount": 200}], result.rows)
        self.assertEqual("actual_executor", result.execution_trace["trace_source"])
        self.assertEqual("country", result.execution_trace["filters_applied"][0]["column"])
        self.assertEqual("passed", verification.semantic_status)

    def test_verifier_rejects_filter_trace_when_result_contains_unfiltered_rows(self) -> None:
        contract = {
            "contract_version": 1,
            "route": "test",
            "task_type": "detail_lookup",
            "capability_family": "detail_lookup",
            "physical_operation": "detail_lookup",
            "metrics": [],
            "dimensions": [],
            "filters": [{"display_name": "country", "resolved_column": "country", "operator": "eq", "values": ["FR"]}],
            "comparison": None,
            "time": None,
            "ranking": None,
        }
        plan = build_analysis_plan(LogicForm(task_type="detail_lookup", operation="detail_lookup"), question="Show FR rows", semantic_contract=contract)
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["country", "amount"],
            rows=[{"country": "DE", "amount": 100}, {"country": "FR", "amount": 200}],
            value=[{"country": "DE", "amount": 100}, {"country": "FR", "amount": 200}],
            execution_trace=self._trace(operation="detail_lookup", filters_applied=[{"column": "country", "operator": "eq", "values": ["FR"]}]),
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="Show FR rows"))

        self.assertEqual("failed", verification.semantic_status)
        self.assertTrue(any(item["type"] == "contract_execution_mismatch" for item in verification.semantic_issues))

    def test_trace_missing_cannot_pass_canonical_coverage(self) -> None:
        logic = LogicForm(task_type="detail_lookup", operation="detail_lookup")
        plan = build_analysis_plan(logic)
        execution_result = ExecutionResult(backend="pandas", success=True, value={"row_count": 2})
        verification = verify_execution(
            execution_result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question="看一下明细", execution_mode="dual"),
        )

        response = build_response(
            run_id="run_test",
            user_question=UserQuestion(dataset_id="ds", question="看一下明细", execution_mode="dual"),
            plan=plan,
            execution_result=execution_result,
            verification=verification,
        ).to_dict()

        self.assertEqual("failed", response["semantic_status"])
        self.assertTrue(any(item["type"] == "missing_execution_trace" for item in response["verification"]["semantic_issues"]))
        self.assertIsNone(response["contract_satisfied"])
        self.assertIsNone(response["contract_family"])
        self.assertEqual([], response["violations"])
        self.assertFalse(response["oracle_result"]["oracle_available"])

    def test_contract_failure_is_reported_with_violation_code(self) -> None:
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="sales",
            group_by="city",
            parameters={"metric": "sales", "dimension": "city", "limit": 3},
            output_format={"answer_type": "table"},
        )
        plan = build_analysis_plan(logic)
        execution_result = ExecutionResult(backend="pandas", success=True, columns=["city"], rows=[{"city": "上海"}], value=[{"city": "上海"}])

        verification = verify_execution(
            execution_result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question="城市 sales Top 3 是哪些？", execution_mode="dual"),
        )

        self.assertEqual("failed", verification.semantic_status)
        self.assertIsNotNone(verification.contract_report)
        codes = [item["code"] for item in verification.contract_report["violations"]]
        self.assertIn("required_output_column_missing", codes)

    def test_pandas_executor_trace_closes_non_retail_contract_loop(self) -> None:
        df = pd.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3", "C4"],
                "segment": ["Enterprise", "SMB", "Enterprise", "Enterprise"],
                "country": ["US", "US", "CA", "MX"],
                "revenue": [100, 50, 80, 40],
                "created_at": ["2024-01-01", "2024-01-02", "2024-02-01", "2024-03-01"],
            }
        )
        schema_profile = build_lightweight_schema_semantic_profile({"tables": {"customers": df}})
        logic = LogicForm(
            task_type="ranking",
            operation="ranking",
            metric="revenue",
            group_by="country",
            parameters={"table": "customers", "metric": "revenue", "dimension": "country", "aggregation": "sum", "limit": 2},
            output_format={"answer_type": "table"},
        )
        question = "Top 2 Enterprise countries by revenue"
        contract = build_canonical_semantic_contract(
            question=question,
            route="test",
            selected_logic_form=logic,
            deterministic_logic_form=logic,
            schema_profile=schema_profile,
        )
        plan = build_analysis_plan(logic, question=question, semantic_contract=contract)
        result = pandas_executor.execute_plan(plan, {"tables": {"customers": df}})
        verification = verify_execution(
            result,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question=question, execution_mode="dual"),
        )

        self.assertEqual("revenue", plan.semantic_contract["metrics"][0]["resolved_columns"][0])
        self.assertEqual("country", plan.execution_spec["dimensions"][0])
        self.assertEqual("segment", plan.execution_spec["filters"][0]["column"])
        self.assertEqual("segment", result.execution_trace["filters_applied"][0]["column"])
        self.assertEqual("country", result.execution_trace["groupby_columns"][0])
        self.assertEqual("passed", verification.semantic_status)
        expected_trace_fields = {
            "operation",
            "metric_columns",
            "aggregation",
            "formula",
            "groupby_columns",
            "filters_applied",
            "comparison_type",
            "time_column",
            "time_grain",
            "ranking",
            "trace_status",
            "source",
            "trace_source",
        }
        self.assertTrue(expected_trace_fields.issubset(result.execution_trace))

    def test_verifier_fails_when_trace_omits_groupby(self) -> None:
        contract = {
            "contract_version": 1,
            "route": "test",
            "task_type": "ranking",
            "capability_family": "ranking",
            "physical_operation": "ranking",
            "metrics": [{"display_name": "sessions", "semantic_type": "measure", "aggregation": "sum", "resolved_columns": ["sessions"]}],
            "dimensions": [{"display_name": "platform", "resolved_column": "platform", "semantic_type": "dimension"}],
            "filters": [],
            "comparison": None,
            "time": None,
            "ranking": {"order": "desc", "limit": 3},
        }
        logic = LogicForm(task_type="ranking", operation="ranking", metric="sessions", parameters={"metric": "sessions", "dimension": "platform", "limit": 3})
        plan = build_analysis_plan(logic, question="Top 3 platforms by sessions", semantic_contract=contract)
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["sessions"],
            rows=[{"sessions": 10}],
            value=[{"sessions": 10}],
            execution_trace=self._trace(operation="ranking", metric_columns=["sessions"], aggregation="sum", groupby_columns=[], ranking={"order": "desc", "limit": 3}),
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="Top 3 platforms by sessions", execution_mode="dual"))

        self.assertEqual("failed", verification.semantic_status)
        self.assertTrue(any(item["type"] == "missing_groupby" for item in verification.semantic_issues))
        self.assertEqual("add_missing_groupby_and_rerun", verification.correction_action["action"])

    def test_verifier_fails_count_distinct_contract_when_trace_is_row_count(self) -> None:
        contract = {
            "contract_version": 1,
            "route": "test",
            "task_type": "aggregation",
            "capability_family": "metric_aggregation",
            "physical_operation": "distinct_count",
            "metrics": [{"display_name": "users", "semantic_type": "entity_count", "aggregation": "nunique", "resolved_columns": ["user_id"]}],
            "dimensions": [],
            "filters": [],
            "comparison": None,
            "time": None,
            "ranking": None,
        }
        plan = build_analysis_plan(LogicForm(task_type="aggregation", operation="row_count"), question="How many users?", semantic_contract=contract)
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["answer"],
            rows=[{"answer": 3}],
            value=3,
            execution_trace=self._trace(operation="row_count", metric_columns=[], aggregation="count"),
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="How many users?", execution_mode="dual"))

        self.assertEqual("failed", verification.semantic_status)
        self.assertTrue(any(item["type"] == "wrong_metric_formula" for item in verification.semantic_issues))
        self.assertEqual("fix_metric_formula_and_rerun", verification.correction_action["action"])

    def test_pandas_executor_actual_formula_trace_records_derived_metric(self) -> None:
        df = pd.DataFrame({"quantity": [2, 3], "unit_price": [10, 5], "segment": ["A", "A"]})
        contract = {
            "contract_version": 1,
            "route": "test",
            "task_type": "aggregation",
            "capability_family": "metric_aggregation",
            "physical_operation": "aggregation",
            "metrics": [
                {
                    "display_name": "sales",
                    "semantic_type": "derived_metric",
                    "aggregation": "sum",
                    "formula": "sum(quantity * unit_price)",
                    "resolved_columns": ["quantity", "unit_price"],
                }
            ],
            "dimensions": [],
            "filters": [],
            "comparison": None,
            "time": None,
            "ranking": None,
        }
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            parameters={
                "table": "transactions",
                "aggregation": "sum",
                "derived_metric": {
                    "name": "sales",
                    "numerator": "quantity",
                    "denominator": "unit_price",
                    "operator": "product_sum",
                    "formula": "sum(quantity * unit_price)",
                },
            },
        )
        plan = build_analysis_plan(logic, question="sales total", semantic_contract=contract)

        result = pandas_executor.execute_plan(plan, {"tables": {"transactions": df}})
        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="sales total"))

        self.assertEqual({"sales": 35.0}, result.value)
        self.assertEqual("actual_executor", result.execution_trace["trace_source"])
        self.assertEqual("sum(quantity * unit_price)", result.execution_trace["formula"])
        self.assertEqual(["quantity", "unit_price"], result.execution_trace["metric_columns"])
        self.assertEqual("passed", verification.semantic_status)

    def test_verifier_fails_wrong_comparison_type(self) -> None:
        contract = {
            "contract_version": 1,
            "route": "test",
            "task_type": "comparison",
            "capability_family": "comparison",
            "physical_operation": "aggregation",
            "metrics": [{"display_name": "amount", "semantic_type": "measure", "aggregation": "sum", "resolved_columns": ["amount"]}],
            "dimensions": [{"display_name": "channel", "resolved_column": "channel", "semantic_type": "dimension"}],
            "filters": [],
            "comparison": {"type": "category_comparison", "metric_ref": "amount", "dimension_ref": "channel"},
            "time": None,
            "ranking": None,
        }
        plan = build_analysis_plan(LogicForm(task_type="comparison", operation="aggregation", metric="amount", group_by="channel", parameters={"metric": "amount", "dimension": "channel"}), question="Compare channel amount", semantic_contract=contract)
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["channel", "amount"],
            rows=[{"channel": "Online", "amount": 100}],
            value=[{"channel": "Online", "amount": 100}],
            execution_trace=self._trace(metric_columns=["amount"], aggregation="sum", groupby_columns=["channel"], comparison_type="time_adjacent_diff"),
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="Compare channel amount", execution_mode="dual"))

        self.assertEqual("failed", verification.semantic_status)
        self.assertTrue(any(item["type"] == "wrong_comparison_type" for item in verification.semantic_issues))
        self.assertEqual("fix_comparison_type_and_rerun", verification.correction_action["action"])

    def test_verifier_rejects_non_actual_trace_source(self) -> None:
        plan = build_analysis_plan(
            LogicForm(task_type="aggregation", operation="aggregation", metric="amount", parameters={"metric": "amount", "aggregation": "sum"}),
            question="amount total",
        )
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["answer"],
            rows=[{"answer": 100}],
            value=100,
            execution_trace=self._trace(operation="aggregation", metric_columns=["amount"], aggregation="sum", trace_source="execution_spec", trace_is_actual=False),
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="amount total"))

        self.assertEqual("failed", verification.semantic_status)
        self.assertTrue(any(item["type"] == "trace_not_actual" for item in verification.semantic_issues))

    def test_verifier_rejects_unsupported_trace_when_contract_requires_semantics(self) -> None:
        plan = build_analysis_plan(
            LogicForm(task_type="aggregation", operation="aggregation", metric="amount", parameters={"metric": "amount", "aggregation": "sum"}),
            question="amount total",
        )
        result = ExecutionResult(
            backend="sqlite",
            success=True,
            columns=["answer"],
            rows=[{"answer": 100}],
            value=100,
            execution_trace=self._trace(operation="aggregation", trace_status="unsupported"),
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question="amount total"))

        self.assertEqual("failed", verification.semantic_status)
        self.assertTrue(any(item["type"] == "unsupported_execution_trace" for item in verification.semantic_issues))

    def test_runtime_verify_results_without_plan_is_legacy_unverified_warning(self) -> None:
        payload = {
            "backend": "pandas",
            "success": True,
            "columns": ["answer"],
            "rows": [{"answer": 1}],
            "value": 1,
            "execution_trace": self._trace(operation="row_count", aggregation="count"),
        }

        output = runtime_verify_results()({"pandas_result": payload, "sql_result": {**payload, "backend": "sqlite"}})

        verification = output["verification"]
        self.assertEqual("warning", verification["semantic_status"])
        self.assertFalse(verification["passed"])
        self.assertFalse(verification["semantic_passed"])
        self.assertTrue(any(item["type"] == "legacy_unverified" for item in verification["semantic_issues"]))
        self.assertEqual("legacy_unverified", verification["correction_action"]["action"])

    def test_executor_prefers_execution_spec_and_exposes_mismatch_warning(self) -> None:
        df = pd.DataFrame({"amount": [10, 20], "cost": [1, 2], "channel": ["Online", "Store"]})
        contract = {
            "contract_version": 1,
            "route": "test",
            "task_type": "aggregation",
            "capability_family": "metric_aggregation",
            "physical_operation": "aggregation",
            "metrics": [{"display_name": "amount", "semantic_type": "measure", "aggregation": "sum", "resolved_columns": ["amount"]}],
            "dimensions": [],
            "filters": [],
            "comparison": None,
            "time": None,
            "ranking": None,
        }
        logic = LogicForm(task_type="aggregation", operation="aggregation", metric="cost", parameters={"table": "transactions", "metric": "cost", "aggregation": "sum"})
        plan = AnalysisPlan(
            plan_id="plan_mismatch",
            logic_form=logic,
            semantic_contract=contract,
            execution_spec=build_execution_spec_from_semantic_contract(contract, logic),
        )

        result = pandas_executor.execute_plan(plan, {"tables": {"transactions": df}})

        self.assertEqual(30.0, result.value)
        self.assertEqual(["amount"], result.execution_trace["metric_columns"])
        self.assertEqual("actual_executor", result.execution_trace["trace_source"])
        self.assertEqual("execution_spec", result.expected_trace["trace_source"])
        self.assertTrue(any("metric" in warning for warning in result.expected_trace.get("trace_warnings", [])))

    def test_response_semantic_warning_is_not_complete_success(self) -> None:
        plan = build_analysis_plan(LogicForm(task_type="aggregation", operation="aggregation", metric="amount", parameters={"metric": "amount"}))
        execution_result = ExecutionResult(backend="pandas", success=True, columns=["answer"], rows=[{"answer": 100}], value=100)
        verification = VerificationResult(
            passed=False,
            semantic_passed=False,
            semantic_status="warning",
            semantic_issues=[{"type": "legacy_unverified", "code": "legacy_unverified", "severity": "warning"}],
            correction_action={"action": "legacy_unverified", "reason": "missing plan"},
        )

        response = build_response(
            run_id="run_semantic_warning",
            user_question=UserQuestion(dataset_id="ds", question="amount total"),
            plan=plan,
            execution_result=execution_result,
            verification=verification,
        ).to_dict()

        self.assertFalse(response["success"])
        self.assertFalse(response["semantic_success"])
        self.assertTrue(any("Semantic verification did not fully pass" in warning for warning in response["warnings"]))

    def test_single_agent_generic_contract_uses_schema_profile(self) -> None:
        df = pd.DataFrame({"ticket_id": ["T1", "T2"], "status": ["Closed", "Open"], "cost": [10, 30], "created_at": ["2024-01-01", "2024-01-02"]})
        schema_profile = build_lightweight_schema_semantic_profile({"tables": {"tickets": df}})
        logic = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            metric="cost",
            parameters={"table": "tickets", "metric": "cost", "aggregation": "sum"},
            output_format={"answer_type": "number"},
        )
        contract = build_canonical_semantic_contract(
            question="Closed ticket cost total",
            route="single_agent_generic",
            selected_logic_form=logic,
            deterministic_logic_form=logic,
            schema_profile=schema_profile,
            column_mapping={"table": "tickets", "mapped_columns": {"metric": "cost"}},
        )
        plan = build_analysis_plan(logic, question="Closed ticket cost total", semantic_contract=contract)

        self.assertEqual("single_agent_generic", plan.semantic_contract["route"])
        self.assertEqual("cost", plan.execution_spec["metric_columns"][0])
        self.assertEqual("status", plan.execution_spec["filters"][0]["column"])

    def test_eval_coverage_counts_semantic_contract_fields(self) -> None:
        result = ScenarioResult(
            scenario_id="semantic_contract_smoke",
            capability_family="ranking",
            run_index=1,
            passed=True,
            simulator_source="deterministic",
            issues=[],
            turns=[
                TurnEvidence(
                    index=1,
                    question="哪个城市销售额最高？",
                    expected_kind="analysis",
                    capability_family="ranking",
                    required_operation="ranking",
                    success=True,
                    answer_type="table",
                    operation="ranking",
                    conversation_id="conv",
                    state_name="analysis_ready",
                    semantic_status="passed",
                    contract_satisfied=True,
                    contract_family="topn",
                    contract_checked=True,
                    oracle_available=True,
                    oracle_passed=True,
                    oracle_issue_codes=["oracle_expected_result_missing"],
                )
            ],
        )

        coverage = _coverage_summary([result])

        self.assertEqual(1, coverage["semantic_contract_turns"])
        self.assertEqual(1, coverage["oracle_result_turns"])
        self.assertEqual(1, coverage["oracle_available_turns"])
        self.assertEqual(1, coverage["oracle_passed_turns"])
        self.assertEqual(0, coverage["oracle_failed_turns"])
        self.assertEqual(1, coverage["contract_checked_turns"])
        self.assertEqual(1, coverage["contract_satisfied_turns"])
        self.assertEqual(1, coverage["semantic_passed_turns"])

    def test_eval_turn_issues_fail_oracle_mismatch(self) -> None:
        evidence = TurnEvidence(
            index=1,
            question="哪个城市销售额最高？",
            expected_kind="analysis",
            capability_family="ranking",
            required_operation="ranking",
            success=True,
            answer_type="table",
            operation="ranking",
            conversation_id="conv",
            state_name="analysis_ready",
            oracle_available=True,
            oracle_passed=False,
            oracle_issue_codes=["deterministic_fixture_oracle_mismatch"],
        )

        issues = _turn_issues(
            1,
            TurnPlan("哪个城市销售额最高？", capability_family="ranking", required_operation="ranking"),
            {
                "success": True,
                "answer": "上海最高。",
                "logic_form": {"operation": "ranking", "parameters": {"metric": "sales", "dimension": "city"}},
                "current_analysis_context": {"state_name": "analysis_ready"},
            },
            previous_conversation_id="",
            evidence=evidence,
        )

        self.assertIn("turn_1:oracle_result_failed:deterministic_fixture_oracle_mismatch", issues)


if __name__ == "__main__":
    unittest.main()
