from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


class OverviewQualityContractTest(unittest.TestCase):
    def test_single_table_overview_lists_fields_types_and_analysis_directions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "service_metrics.csv"
            csv_path.write_text(
                "month,city,service_line,sales,profit,tickets\n"
                "2026-01,Shanghai,installation,1000,220,11\n"
                "2026-01,Beijing,repair,850,160,9\n"
                "2026-02,Shanghai,repair,1200,260,13\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())

            upload = service.upload_dataset(csv_path, original_filename="service_metrics.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="帮我概览上传的服务区域经营数据结构和可分析方向。",
                execution_mode="dual",
            )

        answer = response["answer"]
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("passed", response.get("semantic_status"))
        for field in ("month", "city", "service_line", "sales", "profit", "tickets"):
            self.assertIn(field, answer)
        self.assertIn("字段 | 类型 | 角色 | 可用于什么分析", answer)
        self.assertIn("sales/profit/tickets", answer)
        self.assertIn("按 month 看 sales/profit/tickets 趋势", answer)
        self.assertIn("按 city 分组汇总 sales/profit/tickets", answer)
        self.assertIn("按 service_line", answer)
        self.assertIn("数据质量摘要", answer)

    def test_multi_file_overview_lists_all_fields_join_keys_and_field_bound_directions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "orders.csv"
            customers_path = root / "customers.csv"
            orders_path.write_text(
                "month,amount,profit,customer_id\n"
                "2026-01,1000,220,C1\n"
                "2026-02,1500,300,C2\n",
                encoding="utf-8",
            )
            customers_path.write_text(
                "city,segment,customer_id\n"
                "Shanghai,enterprise,C1\n"
                "Beijing,smb,C2\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())

            upload = service.upload_datasets([orders_path, customers_path], original_filenames=["orders.csv", "customers.csv"])
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="帮我概览这批客户订单收入上传文件能支持哪些分析。",
                execution_mode="dual",
            )

        answer = response["answer"]
        payload = json.dumps(response, ensure_ascii=False)
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("passed", response.get("semantic_status"))
        for field in ("month", "amount", "profit", "customer_id", "city", "segment"):
            self.assertIn(field, answer)
        self.assertIn("orders.customer_id -> customers.customer_id", answer)
        for token in ("amount", "profit", "city", "segment", "month"):
            self.assertIn(token, payload)
        self.assertIn("join 风险", answer)
        self.assertIn("数据质量", answer)

    def test_multi_file_overview_allows_no_candidate_join_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sales_path = root / "sales_fact.csv"
            metadata_path = root / "metadata_fields.csv"
            sales_path.write_text(
                "city,sign_amt,qty,sku_factor,sign_time,emp_name\n"
                "北京市,100,8,A,2026-01-10,张三\n"
                "上海市,200,10,B,2026-01-25,李四\n"
                "杭州市,300,4,C,2026-02-15,王五\n",
                encoding="utf-8",
            )
            metadata_path.write_text(
                "field_name,field_label,field_type,description\n"
                "city,城市,text,城市名称\n"
                "sign_amt,签约金额,numeric,合同签约金额\n"
                "qty,数量,numeric,数量指标\n"
                "sign_time,签约时间,datetime,签约日期\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())

            upload = service.upload_datasets([sales_path, metadata_path], original_filenames=["sales_fact.csv", "metadata_fields.csv"])
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="请概览这批uploaded_dataset数据的结构和关键字段。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("passed", response.get("semantic_status"), response.get("verification"))
        self.assertEqual("multi_file_overview", response.get("contract_family"))
        self.assertNotIn("OVERVIEW_JOIN_KEY_MISSING", json.dumps(response.get("verification"), ensure_ascii=False))

    def test_data_quality_contract_returns_field_level_zero_rows_and_non_repeating_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "service_metrics.csv"
            csv_path.write_text(
                "month,city,service_line,sales,profit,tickets\n"
                "2026-01,Shanghai,installation,1000,220,11\n"
                "2026-01,Beijing,repair,850,160,9\n"
                "2026-02,Shanghai,repair,1200,260,13\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())

            upload = service.upload_dataset(csv_path, original_filename="service_metrics.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="做分析前先看数据质量，重点查缺失、重复和异常值。",
                execution_mode="dual",
            )

        answer = response["answer"]
        quality = response["quality_report"]
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("passed", response.get("semantic_status"))
        self.assertIn("按当前规则检查，各字段缺失、重复、异常统计均为 0；具体字段级结果如下。", answer)
        self.assertIn("字段 | 缺失数 | 缺失率 | 类型异常数 | 异常值数 | 检测规则 | 备注", answer)
        self.assertIn("full_row_duplicate_count=0", answer)
        self.assertIn("numeric IQR rule", answer)
        self.assertIn("non-null type parse failure", answer)
        self.assertNotIn("列出每类质量问题影响的字段和行数", json.dumps(response, ensure_ascii=False))
        self.assertEqual(
            {"month", "city", "service_line", "sales", "profit", "tickets"},
            {row["字段"] for row in quality["field_level_table"]},
        )


if __name__ == "__main__":
    unittest.main()
