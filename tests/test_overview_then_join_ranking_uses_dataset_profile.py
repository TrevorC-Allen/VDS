"""Failing tests for overview -> dataset-profile -> join city TopN flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient
from scripts.run_agent_random_conversation_eval import TurnPlan, _deterministic_fixture_oracle_result


OVERVIEW_QUESTION = "不直接下结论，先概览这些客户订单收入文件的数据结构。"
RANKING_QUESTION = "按客户城市统计订单金额 Top 5 是哪些？"


class OverviewThenJoinRankingUsesDatasetProfileTest(unittest.TestCase):
    def test_first_turn_overview_records_multi_table_profile_join_keys_and_roles(self) -> None:
        overview, _ranking = _run_two_turn_service_flow()

        answer_text = _compact_text(overview.get("answer"))
        overview_report = _overview_report(overview)
        task_contract = _task_contract(overview)
        violations = _violation_codes(overview)

        self.assertEqual("overview", str(overview.get("answer_type") or ""))
        self.assertIn(str(task_contract.get("task_family") or ""), {"multi_file_overview", "overview"})
        self.assertFalse(task_contract.get("requires_previous_artifact", True))
        self.assertNotIn("REFERENT_ARTIFACT_MISSING", violations)
        self.assertNotIn("REFERENT_VALUES_MISSING", violations)

        self.assertEqual("multi_table", str(overview_report.get("overview_scope") or ""))
        table_names = set(_overview_table_names(overview_report))
        self.assertEqual({"orders", "customers"}, table_names)

        self.assertIn("orders.customer_id", answer_text)
        self.assertIn("orders.order_amount", answer_text)
        self.assertIn("orders.order_date", answer_text)
        self.assertIn("customers.customer_id", answer_text)
        self.assertIn("customers.city", answer_text)
        self.assertIn("orders.customer_id->customers.customer_id", answer_text)

        self.assertIn("customer_id", _field_names(overview_report, "orders"))
        self.assertIn("order_amount", _metric_candidates(overview_report, "orders"))
        self.assertIn("order_date", _time_columns(overview_report, "orders"))
        self.assertIn("city", _dimension_candidates(overview_report, "customers"))

        self.assertNotIn("Top5", answer_text)
        self.assertNotIn("排名", answer_text)
        self.assertNotIn("最高的5个", answer_text)

    def test_second_turn_city_top5_uses_overview_profile_join_plan_and_direct_answer(self) -> None:
        overview, ranking = _run_two_turn_service_flow()

        logic = ranking.get("logic_form") if isinstance(ranking.get("logic_form"), dict) else {}
        params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
        debug = ranking.get("debug") if isinstance(ranking.get("debug"), dict) else {}
        artifact = debug.get("result_artifacts") if isinstance(debug.get("result_artifacts"), dict) else {}
        task_contract = _task_contract(ranking)
        first_sentence = _first_sentence(ranking.get("answer"))

        self.assertEqual("ranking", str(logic.get("operation") or ""))
        self.assertEqual("city", str(params.get("dimension") or logic.get("group_by") or ""))
        self.assertEqual("order_amount", str(params.get("metric") or logic.get("metric") or ""))
        self.assertEqual(5, int(params.get("limit") or task_contract.get("required_n") or 0))
        self.assertEqual("desc", str(params.get("sort_order") or task_contract.get("sort_order") or ""))

        self.assertEqual({"orders", "customers"}, set(_source_tables(logic, params, debug, artifact)))
        self.assertEqual("city", str(task_contract.get("dimension") or ""))
        self.assertEqual("order_amount", str(task_contract.get("metric") or ""))
        self.assertEqual(5, int(task_contract.get("required_n") or 0))
        self.assertTrue(task_contract.get("join_scope"), task_contract)

        join_plan = _join_plan(logic, params, debug, artifact)
        join_keys = _join_keys(logic, params, artifact)
        self.assertTrue(join_plan, ranking.get("debug"))
        self.assertTrue(join_keys, ranking.get("debug"))
        self.assertIn(("orders", "customer_id", "customers", "customer_id"), join_keys)

        expected_rows = [
            {"city": "上海", "order_amount": 380},
            {"city": "北京", "order_amount": 220},
            {"city": "深圳", "order_amount": 90},
            {"city": "广州", "order_amount": 70},
        ]
        self.assertEqual(expected_rows, _city_amount_rows(ranking))
        self.assertNotIn("customer_id", set(ranking.get("result", {}).get("columns") or []))

        self.assertEqual({"orders", "customers"}, set(artifact.get("source_tables") or []))
        self.assertTrue(artifact.get("join_plan"))
        self.assertTrue(artifact.get("join_keys"))
        self.assertEqual("order_amount", artifact.get("metric") or artifact.get("metric_column"))
        self.assertEqual("city", artifact.get("dimension") or artifact.get("dimension_column"))
        self.assertEqual(expected_rows, artifact.get("result_rows"))
        self.assertEqual(["上海", "北京", "深圳", "广州"], [str(item.get("value")) for item in artifact.get("top_objects") or []])

        self.assertIn("Top 5", first_sentence)
        self.assertIn("城市", first_sentence)
        self.assertIn("上海", first_sentence)
        self.assertIn("只有 4 个", first_sentence)
        self.assertNotIn("数据摘要", first_sentence)
        self.assertNotIn("业务建议", first_sentence)
        self.assertNotIn("可以按城市分析", first_sentence)

        overview_report = _overview_report(overview)
        self.assertEqual("multi_table", overview_report.get("overview_scope"))

    def test_join_ranking_oracle_rejects_missing_top5_explanation_customer_id_ranking_and_missing_join_scope(self) -> None:
        logic = {
            "operation": "ranking",
            "parameters": {"metric": "order_amount", "dimension": "city", "limit": 5},
            "source_tables": ["orders", "customers"],
            "join_plan": {"left": "orders.customer_id", "right": "customers.customer_id"},
        }
        correct_rows_without_insufficient_explanation = {
            "logic_form": logic,
            "success": True,
            "answer": "Top 5 城市是上海、北京、深圳、广州。",
            "result": {
                "rows": [
                    {"rank": 1, "city": "上海", "order_amount": 380},
                    {"rank": 2, "city": "北京", "order_amount": 220},
                    {"rank": 3, "city": "深圳", "order_amount": 90},
                    {"rank": 4, "city": "广州", "order_amount": 70},
                ]
            },
        }

        missing_explanation = _oracle(logic, correct_rows_without_insufficient_explanation)
        self.assertFalse(missing_explanation["passed"], missing_explanation)
        self.assertIn("topn_insufficient_distinct_explanation_missing", missing_explanation["issue_codes"])

        customer_id_ranking = {
            "logic_form": {
                "operation": "ranking",
                "parameters": {"metric": "order_amount", "dimension": "customer_id", "limit": 5},
                "source_tables": ["orders"],
            },
            "success": True,
            "result": {
                "rows": [
                    {"rank": 1, "customer_id": "C2", "order_amount": 220},
                    {"rank": 2, "customer_id": "C3", "order_amount": 210},
                ]
            },
        }
        wrong_scope = _oracle(customer_id_ranking["logic_form"], customer_id_ranking)
        self.assertFalse(wrong_scope["passed"], wrong_scope)
        self.assertIn("multi_table_join_ranking_source_tables_missing", wrong_scope["issue_codes"])
        self.assertIn("join_key_missing", wrong_scope["issue_codes"])

        missing_join_plan_logic = {
            "operation": "ranking",
            "parameters": {"metric": "order_amount", "dimension": "city", "limit": 5},
            "source_tables": ["orders", "customers"],
        }
        missing_join_plan = _oracle(
            missing_join_plan_logic,
            {
                "logic_form": missing_join_plan_logic,
                "success": True,
                "result": {"rows": [{"rank": 1, "city": "上海", "order_amount": 380}]},
            },
        )
        self.assertFalse(missing_join_plan["passed"], missing_join_plan)
        self.assertIn("join_key_missing", missing_join_plan["issue_codes"])
        self.assertIn("join_plan_missing", missing_join_plan["issue_codes"])


def _run_two_turn_service_flow() -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        files = {
            "orders.csv": (
                "customer_id,order_date,order_amount\n"
                "C1,2026-01-03,120\n"
                "C2,2026-01-05,220\n"
                "C3,2026-01-07,210\n"
                "C4,2026-01-08,90\n"
                "C5,2026-01-10,70\n"
                "C6,2026-01-12,50\n"
            ),
            "customers.csv": (
                "customer_id,city,province,customer_type\n"
                "C1,上海,上海,enterprise\n"
                "C2,北京,北京,smb\n"
                "C3,上海,上海,smb\n"
                "C4,深圳,广东,enterprise\n"
                "C5,广州,广东,smb\n"
                "C6,上海,上海,enterprise\n"
            ),
        }
        paths = []
        for filename, content in files.items():
            path = root / filename
            path.write_text(content, encoding="utf-8")
            paths.append(path)

        service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
        upload = service.upload_datasets(paths, original_filenames=[path.name for path in paths])
        dataset_id = str(upload["dataset_id"])
        overview = service.respond_to_message(dataset_id=dataset_id, question=OVERVIEW_QUESTION, execution_mode="dual")
        ranking = service.respond_to_message(
            dataset_id=dataset_id,
            conversation_id=str(overview["conversation_id"]),
            question=RANKING_QUESTION,
            execution_mode="dual",
        )
        return overview, ranking


def _oracle(logic: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    turn = TurnPlan(
        question=RANKING_QUESTION,
        expected_kind="followup_analysis",
        capability_family="multi_table_join_ranking",
        required_operation="ranking",
    )
    return _deterministic_fixture_oracle_result(logic, response, _orders_and_customers_tables(), turn=turn)


def _orders_and_customers_tables() -> dict[str, pd.DataFrame]:
    return {
        "orders": pd.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3", "C4", "C5", "C6"],
                "order_date": ["2026-01-03", "2026-01-05", "2026-01-07", "2026-01-08", "2026-01-10", "2026-01-12"],
                "order_amount": [120, 220, 210, 90, 70, 50],
            }
        ),
        "customers": pd.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3", "C4", "C5", "C6"],
                "city": ["上海", "北京", "上海", "深圳", "广州", "上海"],
                "province": ["上海", "北京", "上海", "广东", "广东", "上海"],
                "customer_type": ["enterprise", "smb", "smb", "enterprise", "smb", "enterprise"],
            }
        ),
    }


def _overview_report(response: Mapping[str, Any]) -> dict[str, Any]:
    report = response.get("overview_report")
    if isinstance(report, dict) and report:
        return report
    result = response.get("result")
    if isinstance(result, Mapping):
        value = result.get("value")
        if isinstance(value, Mapping) and isinstance(value.get("overview_report"), dict):
            return dict(value["overview_report"])
    return {}


def _overview_table_names(report: Mapping[str, Any]) -> list[str]:
    summaries = report.get("tables_summary")
    if not isinstance(summaries, list):
        return []
    return [str(item.get("table") or item.get("table_name") or "") for item in summaries if isinstance(item, Mapping)]


def _table_summary(report: Mapping[str, Any], table_name: str) -> dict[str, Any]:
    for item in report.get("tables_summary") or []:
        if isinstance(item, Mapping) and str(item.get("table") or item.get("table_name") or "") == table_name:
            return dict(item)
    return {}


def _field_names(report: Mapping[str, Any], table_name: str) -> set[str]:
    table = _table_summary(report, table_name)
    return {str(item.get("field") or "") for item in table.get("field_meanings") or [] if isinstance(item, Mapping)}


def _metric_candidates(report: Mapping[str, Any], table_name: str) -> set[str]:
    table = _table_summary(report, table_name)
    return {str(item) for item in table.get("metric_candidates") or [] if str(item)}


def _dimension_candidates(report: Mapping[str, Any], table_name: str) -> set[str]:
    table = _table_summary(report, table_name)
    return {str(item) for item in table.get("dimension_candidates") or [] if str(item)}


def _time_columns(report: Mapping[str, Any], table_name: str) -> set[str]:
    table = _table_summary(report, table_name)
    return {str(item) for item in table.get("time_columns") or [] if str(item)}


def _task_contract(response: Mapping[str, Any]) -> dict[str, Any]:
    for value in (
        response.get("task_contract"),
        (response.get("debug") or {}).get("task_contract") if isinstance(response.get("debug"), Mapping) else None,
        (response.get("verification") or {}).get("task_contract") if isinstance(response.get("verification"), Mapping) else None,
    ):
        if isinstance(value, dict):
            return value
    return {}


def _violation_codes(response: Mapping[str, Any]) -> set[str]:
    reports = [
        response.get("contract_report"),
        (response.get("debug") or {}).get("contract_report") if isinstance(response.get("debug"), Mapping) else None,
        (response.get("verification") or {}).get("contract_report") if isinstance(response.get("verification"), Mapping) else None,
    ]
    for report in reports:
        if isinstance(report, Mapping):
            return {str(item.get("code") or "") for item in report.get("violations") or [] if isinstance(item, Mapping)}
    return set()


def _source_tables(*values: Any) -> list[str]:
    tables: list[str] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key in ("source_tables", "tables", "source_table"):
            raw = value.get(key)
            if isinstance(raw, list):
                tables.extend(str(item) for item in raw if str(item))
            elif isinstance(raw, str) and raw:
                tables.append(raw)
    return tables


def _join_plan(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping) and isinstance(value.get("join_plan"), dict) and value.get("join_plan"):
            return dict(value["join_plan"])
    return {}


def _join_keys(*values: Any) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for value in values:
        if not isinstance(value, Mapping):
            continue
        raw = value.get("join_keys")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping):
                    keys.add(
                        (
                            str(item.get("left_table") or item.get("from_table") or ""),
                            str(item.get("left_column") or item.get("left_key") or item.get("from_key") or ""),
                            str(item.get("right_table") or item.get("to_table") or ""),
                            str(item.get("right_column") or item.get("right_key") or item.get("to_key") or ""),
                        )
                    )
        plan = value.get("join_plan")
        if isinstance(plan, Mapping):
            left = str(plan.get("left") or "")
            right = str(plan.get("right") or "")
            if "." in left and "." in right:
                left_table, left_column = left.split(".", 1)
                right_table, right_column = right.split(".", 1)
                keys.add((left_table, left_column, right_table, right_column))
            elif plan.get("left_table") and plan.get("right_table"):
                keys.add(
                    (
                        str(plan.get("left_table") or ""),
                        str(plan.get("left_column") or plan.get("left_key") or ""),
                        str(plan.get("right_table") or ""),
                        str(plan.get("right_column") or plan.get("right_key") or ""),
                    )
                )
    return keys


def _city_amount_rows(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result") if isinstance(response.get("result"), Mapping) else {}
    rows = result.get("rows") if isinstance(result, Mapping) else []
    normalized: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping):
            normalized.append({"city": row.get("city"), "order_amount": row.get("order_amount")})
    return normalized


def _compact_text(value: Any) -> str:
    return str(value or "").replace(" ", "").replace("\n", "")


def _first_sentence(value: Any) -> str:
    text = str(value or "").strip()
    for separator in ("。", "\n"):
        if separator in text:
            return text.split(separator, 1)[0]
    return text


if __name__ == "__main__":
    unittest.main()
