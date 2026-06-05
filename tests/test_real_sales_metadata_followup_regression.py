"""Regression coverage for real uploaded sales-table semantics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.core.intent_parser import parse_generic_table_question
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.oracle_results import oracle_topn_followup_gap
from data_agent_core.output.dataset_overview import build_dataset_overview_response
from data_agent_core.output.response_builder import build_response
from data_agent_core.task_contract_builder import apply_referent_contract
from data_agent_core.verifier.rule_checker import verify_execution


FACT_TABLE = "v_trd_dist_ord_dtl"
METADATA_TABLE = "数据表结构&表说明__数据表说明"


class RealSalesMetadataFollowupRegressionTest(unittest.TestCase):
    def test_sku_volume_ranking_excludes_metadata_table_from_business_join(self) -> None:
        logic = parse_generic_table_question("什么sku销量最高", _sales_tables(with_quantity=True), "")

        self.assertEqual("ranking", logic.operation)
        self.assertEqual("sku_factor", logic.parameters.get("dimension"))
        self.assertEqual("qty", logic.parameters.get("metric"))
        self.assertEqual(FACT_TABLE, logic.parameters.get("table"))
        self.assertNotIn(METADATA_TABLE, logic.source_tables)
        self.assertNotIn(METADATA_TABLE, logic.parameters.get("source_tables") or [])
        self.assertFalse(logic.join_plan)
        self.assertFalse(logic.parameters.get("join_plan"))

        result = execute_plan(build_analysis_plan(logic, question="什么sku销量最高"), {"tables": _sales_tables(with_quantity=True)})

        self.assertTrue(result.success, result.errors)
        self.assertEqual([{"sku_factor": "SKU-A", "qty": 22}], result.value)

    def test_top5_sku_sales_with_only_three_distinct_objects_reports_hard_caveat(self) -> None:
        response = _execute_response("前5个sku销量最高", _sales_tables(with_quantity=True))

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("topn", response["contract_family"])
        task_contract = response["verification"]["task_contract"]
        self.assertEqual(5, int(task_contract.get("required_n") or 0))
        self.assertEqual("sku_factor", task_contract.get("dimension"))
        self.assertEqual("qty", task_contract.get("metric"))
        self.assertEqual(3, len(response["result"]["rows"]))
        self.assertEqual(3, response["debug"]["result_artifacts"]["distinct_count"])

        answer = str(response.get("answer") or "")
        self.assertIn("Top 5", answer)
        self.assertIn("sku_factor", answer)
        self.assertIn("实际只有 3", answer)
        self.assertIn("只能返回 Top 3", answer)
        self.assertIn("source field 为 sku_factor", answer)
        self.assertIn("不是系统漏算", answer)

        sections = response.get("structured_answer_sections") or {}
        caveats = " ".join(str(item) for item in sections.get("caveats") or [])
        self.assertIn("source field 为 sku_factor", caveats)
        self.assertIn("Top 5", caveats)
        self.assertIn("无法满足 Top 5", caveats)

    def test_service_top5_sku_sales_only_three_distinct_items_shows_topn_shortage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = _write_sales_topn_qty_csv(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales_fact.csv")
            dataset_id = str(upload["dataset_id"])

            response = service.respond_to_message(
                dataset_id=dataset_id,
                question="前5个sku销量最高",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("topn", response.get("contract_family"))
        self.assertEqual("passed", response.get("semantic_status"))

        task_contract = response.get("verification", {}).get("task_contract") or {}
        self.assertEqual(5, int(task_contract.get("required_n") or 0))
        self.assertEqual("sku_factor", task_contract.get("dimension"))
        self.assertEqual("qty", task_contract.get("metric"))
        self.assertEqual(3, len(response["result"]["rows"]))

        answer = str(response.get("answer") or "")
        self.assertIn("Top 5", answer)
        self.assertIn("当前数据中sku_factor实际只有 3 个不同sku_factor", answer)
        self.assertIn("只能返回 Top 3", answer)
        self.assertIn("source field 为 sku_factor", answer)
        self.assertIn("不是系统漏算", answer)

        sections = response.get("structured_answer_sections") or {}
        caveats = " ".join(str(item) for item in sections.get("caveats") or [])
        self.assertIn("Top 5", caveats)
        self.assertIn("当前只有 3", caveats)
        self.assertIn("source field 为 sku_factor", caveats)

    def test_city_order_amount_top1_keeps_dimension_and_metric_in_result_artifact(self) -> None:
        response = _execute_response("哪个城市订单金额最大", _sales_tables(with_quantity=True))

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual(["city", "sign_amt"], response["result"]["columns"])
        self.assertEqual("杭州市", response["result"]["rows"][0]["city"])
        self.assertAlmostEqual(136330.74, float(response["result"]["rows"][0]["sign_amt"]), places=2)
        self.assertNotEqual({"answer": 136330.74}, response["result"].get("value"))

        artifact = response["debug"].get("result_artifacts") or {}
        self.assertEqual("city", artifact.get("dimension"))
        self.assertEqual("sign_amt", artifact.get("metric"))
        self.assertEqual("杭州市", artifact.get("top_objects", [{}])[0].get("value"))
        self.assertAlmostEqual(136330.74, float(artifact.get("top_objects", [{}])[0].get("metric_value")), places=2)
        self.assertNotIn(METADATA_TABLE, artifact.get("source_tables") or [])

    def test_city_sales_question_prefers_city_name_over_capacity_and_preserves_capacity_ranking(self) -> None:
        tables = {"sales_fact": _city_capacity_sales_table()}

        for question in ("什么城市销售额最高", "哪个城市销售额最高"):
            with self.subTest(question=question):
                response = _execute_response_with_fact_table(question, tables, fact_table="sales_fact")

                self.assertTrue(response["success"], response.get("errors"))
                self.assertEqual("ranking", response["logic_form"]["operation"])
                params = response["logic_form"]["parameters"]
                self.assertEqual("city_name", params.get("dimension"))
                self.assertEqual("sign_amt", params.get("metric"))
                self.assertEqual("sales_fact", params.get("table"))
                self.assertEqual(["sales_fact"], params.get("source_tables"))
                self.assertNotEqual("capacity", params.get("dimension"))
                self.assertEqual(["city_name", "sign_amt"], response["result"]["columns"])
                self.assertEqual("杭州市", response["result"]["rows"][0]["city_name"])

                answer = str(response.get("answer") or "")
                self.assertIn("杭州市", answer)
                self.assertNotIn("500mL", answer)
                self.assertNotIn("容量", answer)
                self.assertNotEqual("clarification", response.get("answer_type"))

        capacity_response = _execute_response_with_fact_table("哪个容量销售额最高", tables, fact_table="sales_fact")

        self.assertTrue(capacity_response["success"], capacity_response.get("errors"))
        capacity_params = capacity_response["logic_form"]["parameters"]
        self.assertEqual("capacity", capacity_params.get("dimension"))
        self.assertEqual("sign_amt", capacity_params.get("metric"))
        self.assertNotEqual("city_name", capacity_params.get("dimension"))
        self.assertEqual(["capacity", "sign_amt"], capacity_response["result"]["columns"])
        self.assertEqual("1L", capacity_response["result"]["rows"][0]["capacity"])
        self.assertIn("1L", str(capacity_response.get("answer") or ""))
        self.assertNotIn("城市是1L", str(capacity_response.get("answer") or ""))

    def test_service_city_sales_question_prefers_city_name_over_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = _write_city_capacity_sales_csv(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales_fact.csv")
            dataset_id = str(upload["dataset_id"])

            city_what = service.respond_to_message(
                dataset_id=dataset_id,
                question="什么城市销售额最高",
                execution_mode="dual",
            )
            city_which = service.respond_to_message(
                dataset_id=dataset_id,
                question="哪个城市销售额最高",
                execution_mode="dual",
            )
            capacity = service.respond_to_message(
                dataset_id=dataset_id,
                question="哪个容量销售额最高",
                execution_mode="dual",
            )

        for response in (city_what, city_which):
            self.assertTrue(response["success"], response.get("errors"))
            params = response["logic_form"]["parameters"]
            self.assertEqual("city_name", params.get("dimension"))
            self.assertEqual("sign_amt", params.get("metric"))
            self.assertEqual("sales_fact", params.get("table"))
            self.assertEqual(["sales_fact"], params.get("source_tables"))
            self.assertNotEqual("capacity", params.get("dimension"))
            self.assertEqual(["city_name", "sign_amt"], response["result"]["columns"])
            self.assertEqual("杭州市", response["result"]["rows"][0]["city_name"])
            self.assertNotIn("500mL", str(response.get("answer") or ""))
            self.assertNotEqual("clarification", response.get("answer_type"))

        self.assertTrue(capacity["success"], capacity.get("errors"))
        capacity_params = capacity["logic_form"]["parameters"]
        self.assertEqual("capacity", capacity_params.get("dimension"))
        self.assertEqual("sign_amt", capacity_params.get("metric"))
        self.assertEqual(["capacity", "sign_amt"], capacity["result"]["columns"])
        self.assertEqual("1L", capacity["result"]["rows"][0]["capacity"])
        self.assertIn("1L", str(capacity.get("answer") or ""))
        self.assertNotIn("城市是1L", str(capacity.get("answer") or ""))

    def test_generic_adjacent_comparison_followup_inherits_previous_city_metric_and_table(self) -> None:
        first_response = _execute_response("哪个城市订单金额最大", _sales_tables(with_quantity=True))
        context = build_analysis_context(first_response, original_question="哪个城市订单金额最大")

        actions = plan_followup_actions("对比相邻时间段或相关对象的同一指标", context)

        self.assertEqual(1, len(actions))
        action = actions[0]
        contract = action.get("referent_contract") or {}
        inherited = action.get("inherited_parameters") or {}
        params = action.get("parameters") or {}
        self.assertEqual("杭州市", contract.get("referent_values", [None])[0])
        self.assertEqual("city", contract.get("referent_dimension"))
        self.assertEqual("sign_amt", params.get("metric"))
        self.assertEqual(FACT_TABLE, inherited.get("table"))
        self.assertEqual([FACT_TABLE], inherited.get("source_tables"))
        self.assertNotIn(METADATA_TABLE, inherited.get("source_tables") or [])
        self.assertEqual({"city": "杭州市"}, inherited.get("filters"))

    def test_city_top1_adjacent_time_comparison_followup_executes_with_gap_contract(self) -> None:
        first_response = _execute_response("哪个城市订单金额最大", _sales_tables(with_quantity=True))
        second_response = _execute_followup_response(
            "对比相邻时间段或相关对象的同一指标",
            first_response,
            _sales_tables(with_quantity=True),
        )

        self.assertTrue(second_response["success"], second_response.get("errors"))
        self.assertNotIn("缺过滤条件", str(second_response.get("answer") or ""))
        self.assertEqual("gap", second_response.get("contract_family"))
        self.assertEqual("sign_amt", second_response["verification"]["task_contract"]["metric"])
        self.assertEqual("sign_time", second_response["verification"]["task_contract"]["dimension"])
        self.assertEqual("sign_time", second_response["debug"]["task_contract"]["dimension"])
        self.assertEqual("sign_time", second_response["logic_form"]["parameters"].get("time_column"))
        self.assertEqual(FACT_TABLE, second_response["logic_form"]["parameters"].get("table"))
        self.assertEqual([FACT_TABLE], second_response["logic_form"]["parameters"].get("source_tables"))
        self.assertEqual({"city": "杭州市"}, second_response["logic_form"].get("filters"))

        task_contract = second_response["verification"]["task_contract"]
        self.assertEqual("city", task_contract.get("referent_dimension"))
        self.assertEqual(["杭州市"], task_contract.get("referent_values"))
        self.assertTrue(task_contract.get("requires_previous_artifact"))

        rows = second_response["result"]["rows"]
        self.assertEqual("2026-01-15", rows[0]["sign_time"])
        self.assertAlmostEqual(50000.25, float(rows[0]["sign_amt"]), places=2)
        self.assertEqual("2026-02-15", rows[1]["sign_time"])
        self.assertAlmostEqual(86330.49, float(rows[1]["sign_amt"]), places=2)

        gap_rows = second_response["debug"]["result_artifacts"].get("gap_rows") or []
        self.assertEqual(2, len(gap_rows))
        self.assertIn("adjacent_gap", gap_rows[1])
        self.assertAlmostEqual(-36330.24, float(gap_rows[1]["adjacent_gap"]), places=2)
        self.assertIn("差距", second_response.get("answer") or "")

        expected_gap = {
            "task_family": "ranking_followup_gap",
            "top_objects": [
                {"rank": 1, "value": "2026-01-15", "metric_value": 50000.25},
                {"rank": 2, "value": "2026-02-15", "metric_value": 86330.49},
            ],
            "adjacent_gaps": [-36330.24],
            "gap_to_leader": [0, -36330.24],
        }
        actual_gap = {
            "task_family": "ranking_followup_gap",
            "top_objects": [
                {"rank": index + 1, "value": row["sign_time"], "metric_value": row["sign_amt"]}
                for index, row in enumerate(rows)
            ],
            "adjacent_gaps": [gap_rows[1]["adjacent_gap"]],
            "gap_to_leader": [row.get("gap_to_leader") for row in gap_rows],
        }
        oracle = oracle_topn_followup_gap(expected_gap, actual_gap, answer=str(second_response.get("answer") or ""))
        self.assertTrue(oracle.oracle_available)
        self.assertTrue(oracle.passed, oracle.issue_codes)

    def test_service_city_top1_adjacent_time_comparison_followup_uses_gap_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = _write_sales_fact_csv(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales_fact.csv")
            dataset_id = str(upload["dataset_id"])

            first_response = service.respond_to_message(
                dataset_id=dataset_id,
                question="哪个城市订单金额最大？",
                execution_mode="dual",
            )
            conversation_id = str(first_response["conversation_id"])
            second_response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="对比相邻时间段或相关对象的同一指标",
                execution_mode="dual",
            )

        self.assertTrue(first_response["success"], first_response.get("errors"))
        self.assertEqual("ranking", first_response["logic_form"]["operation"])
        self.assertEqual("杭州市", first_response["result"]["rows"][0]["city"])

        self.assertTrue(second_response["success"], second_response.get("errors"))
        self.assertTrue(second_response.get("followup_context", {}).get("is_followup"), second_response.get("followup_context"))
        self.assertNotEqual("filtering", second_response["logic_form"]["operation"])
        self.assertEqual("gap", second_response.get("contract_family"))
        self.assertNotIn("缺过滤条件", str(second_response.get("answer") or ""))
        self.assertNotIn("Top 3 城市中", str(second_response.get("answer") or ""))

        logic = second_response["logic_form"]
        params = logic["parameters"]
        self.assertEqual("sign_amt", params.get("metric"))
        self.assertEqual("sign_time", params.get("dimension"))
        self.assertEqual("sign_time", params.get("time_column"))
        self.assertEqual("sales_fact", params.get("table"))
        self.assertEqual(["sales_fact"], params.get("source_tables"))
        self.assertEqual({"city": "杭州市"}, logic.get("filters"))

        task_contract = second_response["verification"]["task_contract"]
        self.assertEqual("gap", task_contract.get("task_family"))
        self.assertEqual("sign_amt", task_contract.get("metric"))
        self.assertEqual("sign_time", task_contract.get("dimension"))
        self.assertEqual("city", task_contract.get("referent_dimension"))
        self.assertEqual(["杭州市"], task_contract.get("referent_values"))
        self.assertTrue(task_contract.get("requires_previous_artifact"))

        rows = second_response["result"]["rows"]
        self.assertEqual(["sign_time", "sign_amt"], second_response["result"]["columns"])
        self.assertEqual("2026-01-15", rows[0]["sign_time"])
        self.assertAlmostEqual(50000.25, float(rows[0]["sign_amt"]), places=2)
        self.assertEqual("2026-02-15", rows[1]["sign_time"])
        self.assertAlmostEqual(86330.49, float(rows[1]["sign_amt"]), places=2)

        gap_rows = second_response["debug"]["result_artifacts"].get("gap_rows") or []
        self.assertEqual(2, len(gap_rows))
        self.assertAlmostEqual(-36330.24, float(gap_rows[1]["adjacent_gap"]), places=2)

    def test_salesperson_growth_ranking_resolves_specific_candidates(self) -> None:
        logic = parse_generic_table_question("看一下这几个销售的表现，按照增长率排名", _sales_tables(with_quantity=True), "")

        self.assertEqual("growth_ranking", logic.operation)
        self.assertEqual("emp_name", logic.parameters.get("dimension"))
        self.assertEqual("sign_amt", logic.parameters.get("metric"))
        self.assertEqual("sign_time", logic.parameters.get("time_column"))
        self.assertEqual(FACT_TABLE, logic.parameters.get("table"))
        self.assertNotIn(METADATA_TABLE, logic.parameters.get("source_tables") or [])

        result = execute_plan(build_analysis_plan(logic, question="看一下这几个销售的表现，按照增长率排名"), {"tables": _sales_tables(with_quantity=True)})

        self.assertTrue(result.success, result.errors)
        self.assertEqual("张三", result.rows[0]["emp_name"])
        self.assertIn("sign_amt_growth_rate", result.rows[0])

    def test_service_salesperson_growth_ranking_escapes_prior_adjacent_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = _write_sales_fact_csv(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales_fact.csv")
            dataset_id = str(upload["dataset_id"])

            first_response = service.respond_to_message(
                dataset_id=dataset_id,
                question="哪个城市订单金额最大？",
                execution_mode="dual",
            )
            conversation_id = str(first_response["conversation_id"])
            second_response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="对比相邻时间段或相关对象的同一指标",
                execution_mode="dual",
            )
            third_response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="销售员增长率排名",
                execution_mode="dual",
            )

        self.assertTrue(first_response["success"], first_response.get("errors"))
        self.assertEqual("ranking", first_response["logic_form"]["operation"])
        self.assertEqual("city", first_response["logic_form"]["parameters"].get("dimension"))
        self.assertEqual("杭州市", first_response["result"]["rows"][0]["city"])
        self.assertTrue(second_response.get("followup_context", {}).get("is_followup"), second_response.get("followup_context"))

        self.assertTrue(third_response["success"], third_response.get("errors"))
        self.assertEqual("self_contained_followup", third_response.get("followup_context", {}).get("reason"))

        logic = third_response["logic_form"]
        params = logic["parameters"]
        self.assertEqual("growth_ranking", logic["operation"])
        self.assertEqual("emp_name", params.get("dimension"))
        self.assertEqual("sign_amt", params.get("metric"))
        self.assertEqual("sign_time", params.get("time_column"))
        self.assertEqual("sales_fact", params.get("table"))
        self.assertEqual(["sales_fact"], params.get("source_tables"))
        self.assertNotIn("city", logic.get("filters") or {})

        task_contract = third_response["verification"]["task_contract"]
        self.assertEqual("emp_name", task_contract.get("dimension"))
        self.assertEqual("sign_amt", task_contract.get("metric"))
        self.assertIn("emp_name", task_contract.get("required_output_columns") or [])
        self.assertIn("sign_amt_growth_rate", task_contract.get("required_output_columns") or [])

        rows = third_response["result"]["rows"]
        self.assertEqual("张三", rows[0]["emp_name"])
        self.assertIn("sign_amt_growth_rate", rows[0])
        self.assertNotEqual(["sign_time", "sign_amt"], third_response["result"]["columns"])
        self.assertIn("张三", third_response.get("answer") or "")

    def test_overview_question_with_metadata_reference_table_is_distinguishable_and_not_recommended_for_business_join(self) -> None:
        response = build_dataset_overview_response(
            run_id="run_sales_overview_metadata",
            dataset_id="ds_sales",
            question="能分析什么？这几张表",
            tables=_sales_tables(with_quantity=True),
            profile=None,
        )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("overview", response.get("answer_type"))
        overview = response["overview_report"] if isinstance(response.get("overview_report"), dict) else {}
        self.assertEqual("multi_table", str(overview.get("overview_scope") or ""))

        tables = overview.get("tables_summary")
        self.assertIsInstance(tables, list)
        self.assertEqual(2, len(tables))
        table_map: dict[str, dict[str, Any]] = {}
        for item in tables:
            if isinstance(item, dict):
                table_map[str(item.get("table") or "")] = item
        self.assertIn(FACT_TABLE, table_map)
        self.assertIn(METADATA_TABLE, table_map)
        self.assertEqual("说明或元数据表", str(table_map[METADATA_TABLE].get("table_type") or ""))

        join_keys = [str(item.get("text") or "") for item in overview.get("candidate_join_keys") or [] if isinstance(item, dict)]
        for key_text in join_keys:
            self.assertNotIn(METADATA_TABLE, key_text)

        answer = str(response.get("answer") or "")
        compact = "".join(answer.split())
        self.assertIn(FACT_TABLE, answer)
        self.assertIn(METADATA_TABLE, answer)
        self.assertNotIn(f"关联{FACT_TABLE}与{METADATA_TABLE}", compact)
        self.assertNotIn(f"关联{METADATA_TABLE}与{FACT_TABLE}", compact)
        self.assertTrue(any(token in answer for token in ("qty", "city", "sign_amt")))


def _execute_response(question: str, tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    return _execute_response_with_fact_table(question, tables, fact_table=FACT_TABLE)


def _execute_response_with_fact_table(question: str, tables: dict[str, pd.DataFrame], *, fact_table: str) -> dict[str, object]:
    logic = parse_generic_table_question(question, tables, "")
    plan = build_analysis_plan(logic, question=question)
    result = execute_plan(plan, {"tables": tables, "primary_table": fact_table})
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds_sales", question=question))
    return build_response(
        run_id="run_sales_regression",
        user_question=UserQuestion(dataset_id="ds_sales", question=question),
        plan=plan,
        execution_result=result,
        verification=verification,
    ).to_dict()


def _execute_followup_response(question: str, previous_response: dict[str, object], tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    context = build_analysis_context(previous_response, original_question="哪个城市订单金额最大")
    actions = plan_followup_actions(question, context)
    if len(actions) != 1:
        raise AssertionError(f"expected one structured follow-up action, got {actions!r}")
    action = actions[0]
    params = dict(action.get("parameters") or {})
    inherited = dict(action.get("inherited_parameters") or {})
    logic = LogicForm(
        task_type=str(action.get("operation") or "aggregation"),
        operation=str(action.get("operation") or "aggregation"),
        metric=str(params.get("metric") or ""),
        group_by=str(params.get("dimension") or ""),
        filters={},
        parameters={
            **inherited,
            **params,
            "table": inherited.get("table") or FACT_TABLE,
            "source_tables": inherited.get("source_tables") or [FACT_TABLE],
            "available_columns": inherited.get("available_columns") or list(tables[FACT_TABLE].columns),
        },
        output_format={"answer_type": "table"},
    )
    apply_referent_contract(logic, action.get("referent_contract") or {})
    plan = build_analysis_plan(logic, question=str(action.get("question") or question))
    result = execute_plan(plan, {"tables": tables, "primary_table": FACT_TABLE})
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds_sales", question=str(action.get("question") or question)))
    return build_response(
        run_id="run_sales_followup_regression",
        user_question=UserQuestion(dataset_id="ds_sales", question=question),
        plan=plan,
        execution_result=result,
        verification=verification,
    ).to_dict()


def _sales_tables(*, with_quantity: bool) -> dict[str, pd.DataFrame]:
    fact_rows = [
        {"dist_ord_item_id": "A1", "sku_factor": "SKU-A", "city": "杭州市", "emp_name": "张三", "sign_amt": 50000.25, "sign_time": "2026-01-15", **({"qty": 10} if with_quantity else {})},
        {"dist_ord_item_id": "A2", "sku_factor": "SKU-B", "city": "上海市", "emp_name": "李四", "sign_amt": 60000.00, "sign_time": "2026-01-20", **({"qty": 18} if with_quantity else {})},
        {"dist_ord_item_id": "A3", "sku_factor": "SKU-A", "city": "杭州市", "emp_name": "张三", "sign_amt": 86330.49, "sign_time": "2026-02-15", **({"qty": 12} if with_quantity else {})},
        {"dist_ord_item_id": "A4", "sku_factor": "SKU-B", "city": "上海市", "emp_name": "李四", "sign_amt": 30000.00, "sign_time": "2026-02-20", **({"qty": 4} if with_quantity else {})},
        {"dist_ord_item_id": "A5", "sku_factor": "SKU-C", "city": "北京市", "emp_name": "王五", "sign_amt": 45000.00, "sign_time": "2026-01-18", **({"qty": 6} if with_quantity else {})},
        {"dist_ord_item_id": "A6", "sku_factor": "SKU-C", "city": "北京市", "emp_name": "王五", "sign_amt": 47000.00, "sign_time": "2026-02-18", **({"qty": 5} if with_quantity else {})},
    ]
    metadata_rows = [
        {"table_name": FACT_TABLE, "field_name": "dist_ord_item_id", "field_desc": "分销订单明细行 ID", "dist_ord_item_id": "字段说明"},
        {"table_name": FACT_TABLE, "field_name": "sku_factor", "field_desc": "SKU 因子/商品标识", "dist_ord_item_id": "字段说明"},
        {"table_name": FACT_TABLE, "field_name": "sign_amt", "field_desc": "订单签收金额", "dist_ord_item_id": "字段说明"},
    ]
    return {
        FACT_TABLE: pd.DataFrame(fact_rows),
        METADATA_TABLE: pd.DataFrame(metadata_rows),
    }


def _city_capacity_sales_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"city_name": "杭州市", "capacity": "500mL", "sign_amt": 120000.00, "sign_time": "2026-01-15"},
            {"city_name": "上海市", "capacity": "500mL", "sign_amt": 80000.00, "sign_time": "2026-01-16"},
            {"city_name": "杭州市", "capacity": "1L", "sign_amt": 220000.00, "sign_time": "2026-02-15"},
            {"city_name": "上海市", "capacity": "1L", "sign_amt": 200000.00, "sign_time": "2026-02-16"},
        ]
    )


def _write_city_capacity_sales_csv(root: Path) -> Path:
    path = root / "sales_fact.csv"
    _city_capacity_sales_table().to_csv(path, index=False)
    return path


def _write_sales_fact_csv(root: Path) -> Path:
    rows = [
        {"order_id": "A1", "city": "杭州市", "emp_name": "张三", "sign_amt": 50000.25, "sign_time": "2026-01-15"},
        {"order_id": "A2", "city": "上海市", "emp_name": "李四", "sign_amt": 60000.00, "sign_time": "2026-01-20"},
        {"order_id": "A3", "city": "杭州市", "emp_name": "张三", "sign_amt": 86330.49, "sign_time": "2026-02-15"},
        {"order_id": "A4", "city": "上海市", "emp_name": "李四", "sign_amt": 30000.00, "sign_time": "2026-02-20"},
        {"order_id": "A5", "city": "北京市", "emp_name": "王五", "sign_amt": 45000.00, "sign_time": "2026-01-18"},
        {"order_id": "A6", "city": "北京市", "emp_name": "王五", "sign_amt": 47000.00, "sign_time": "2026-02-18"},
    ]
    path = root / "sales_fact.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_sales_topn_qty_csv(root: Path) -> Path:
    path = root / "sales_topn_qty.csv"
    _sales_tables(with_quantity=True)[FACT_TABLE].drop(columns=["dist_ord_item_id", "emp_name"]).to_csv(path, index=False)
    return path


if __name__ == "__main__":
    unittest.main()
