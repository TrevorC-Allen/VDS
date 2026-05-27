"""Phase 8 multi-file and multi-table capability tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.contracts.analysis_contracts import UserQuestion
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.intent_parser import parse_generic_table_question
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.verifier.rule_checker import verify_execution


class Phase8MultiTableCapabilityTest(unittest.TestCase):
    def test_multi_file_routing_selects_inventory_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            tables = [
                {
                    "table_name": "销售文件",
                    "source_file": "销售文件.csv",
                    "rows": [
                        {"产品": "A", "销售额": 100},
                        {"产品": "B", "销售额": 300},
                        {"产品": "C", "销售额": 200},
                    ],
                },
                {
                    "table_name": "库存文件",
                    "source_file": "库存文件.csv",
                    "rows": [
                        {"产品": "A", "库存量": 10},
                        {"产品": "B", "库存量": 30},
                        {"产品": "C", "库存量": 80},
                    ],
                },
            ]

            sales = service.run_agent_with_inline_tables(question="哪个产品销售额最高？", tables=tables)
            inventory = service.run_agent_with_inline_tables(question="哪个产品库存量最高？", tables=tables)
            explicit_inventory = service.run_agent_with_inline_tables(question="库存文件里哪个产品库存量最高？", tables=tables)

        self.assertTrue(sales["success"])
        self.assertEqual({"产品": "B", "销售额": 300}, sales["result"]["rows"][0])
        self.assertEqual(["销售文件"], sales["debug"]["source_tables"])
        self.assertTrue(inventory["success"])
        self.assertEqual({"产品": "C", "库存量": 80}, inventory["result"]["rows"][0])
        self.assertEqual(["库存文件"], inventory["debug"]["source_tables"])
        self.assertTrue(explicit_inventory["success"])
        self.assertEqual({"产品": "C", "库存量": 80}, explicit_inventory["result"]["rows"][0])
        self.assertIn("explicit_table_mention", explicit_inventory["debug"]["table_selection_reason"])

    def test_join_plan_materializes_city_aggregation(self) -> None:
        tables = _orders_and_customers()
        ranking = _execute("哪个城市订单金额最高？", tables)
        aggregation = _execute("按城市统计订单金额", tables)

        self.assertTrue(ranking["result"].success, ranking["result"].errors)
        self.assertEqual([{"城市": "北京", "订单金额": 200}], ranking["result"].value)
        self.assertEqual(["订单表", "客户表"], ranking["logic"].source_tables)
        self.assertTrue(ranking["logic"].join_plan["trusted"])
        self.assertEqual("many_to_one", ranking["logic"].join_plan["relationship"])
        self.assertEqual(3, ranking["result"].debug["join_execution_summary"]["joined_rows"])
        self.assertTrue(aggregation["result"].success, aggregation["result"].errors)
        self.assertEqual(
            [{"城市": "上海", "订单金额": 150}, {"城市": "北京", "订单金额": 200}],
            aggregation["result"].value,
        )

    def test_untrusted_join_key_requires_clarification(self) -> None:
        tables = {
            "订单表": pd.DataFrame({"客户ID": ["C1", "C2"], "订单金额": [100, 200]}),
            "客户表": pd.DataFrame({"客户编号": ["X1", "X2"], "城市": ["上海", "北京"]}),
        }
        executed = _execute("按城市统计订单金额", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="按城市统计订单金额"),
        )

        self.assertFalse(executed["result"].success)
        self.assertFalse(executed["logic"].join_plan["trusted"])
        self.assertFalse(verification.passed)
        self.assertEqual("clarify_join_key", verification.correction_action["action"])

    def test_many_to_many_join_risk_is_not_silent_success(self) -> None:
        tables = {
            "订单表": pd.DataFrame({"客户ID": ["C1", "C2", "C1"], "订单金额": [100, 200, 50]}),
            "客户表": pd.DataFrame({"客户ID": ["C1", "C1", "C2"], "城市": ["上海", "杭州", "北京"]}),
        }
        executed = _execute("按城市统计订单金额", tables)
        verification = verify_execution(
            executed["result"],
            plan=executed["plan"],
            user_question=UserQuestion(dataset_id="ds_phase8", question="按城市统计订单金额"),
        )

        self.assertFalse(executed["result"].success)
        self.assertTrue(executed["logic"].join_plan["many_to_many_risk"])
        self.assertFalse(verification.passed)
        self.assertEqual("clarify_join_key", verification.correction_action["action"])

    def test_single_table_regression_still_ranks_normally(self) -> None:
        tables = {"sales": pd.DataFrame({"city": ["Shanghai", "Beijing", "Shanghai"], "sales": [100, 150, 200]})}
        executed = _execute("Which city has the highest sales?", tables)

        self.assertTrue(executed["result"].success, executed["result"].errors)
        self.assertEqual([{"city": "Shanghai", "sales": 300}], executed["result"].value)
        self.assertEqual(["sales"], executed["logic"].source_tables)
        self.assertEqual({}, executed["logic"].join_plan)


def _orders_and_customers() -> dict[str, pd.DataFrame]:
    return {
        "订单表": pd.DataFrame({"客户ID": ["C1", "C2", "C1"], "订单金额": [100, 200, 50]}),
        "客户表": pd.DataFrame({"客户ID": ["C1", "C2"], "城市": ["上海", "北京"]}),
    }


def _execute(question: str, tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    logic = parse_generic_table_question(question, tables, "")
    plan = build_analysis_plan(logic)
    result = execute_plan(plan, {"tables": tables, "primary_table": next(iter(tables))})
    return {"logic": logic, "plan": plan, "result": result}


if __name__ == "__main__":
    unittest.main()
