"""Tests for the minimal backend Data Agent service shell."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


class DataAgentServiceTest(unittest.TestCase):
    def test_upload_profile_analyze_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "city,sales\n"
                "Shanghai,100\n"
                "Beijing,150\n"
                "Shanghai,200\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path)
            dataset_id = upload["dataset_id"]
            profile = service.get_dataset_profile(dataset_id)
            analysis = service.analyze_dataset(
                dataset_id=dataset_id,
                question="Which city has the highest sales?",
                execution_mode="dual",
            )

            self.assertTrue(upload["success"])
            self.assertEqual(profile["dataset_id"], dataset_id)
            self.assertTrue(analysis["success"])
            self.assertEqual(analysis["response_version"], "v1")
            self.assertTrue(analysis["run_id"].startswith("run_"))
            self.assertEqual(analysis["result"]["rows"][0]["city"], "Shanghai")
            self.assertEqual("multi_agent", analysis["debug"]["agent_mode"])
            self.assertIn("planner", analysis["debug"]["multi_agent_roles"])
            self.assertIn("trace_path", analysis["debug"])

    def test_upload_datasets_preserves_source_file_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            temp_sales = root / "tmp_sales_upload.csv"
            temp_inventory = root / "tmp_inventory_upload.csv"
            temp_sales.write_text("产品,销售额\nA,100\nB,300\n", encoding="utf-8")
            temp_inventory.write_text("产品,库存量\nA,10\nC,80\n", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [temp_sales, temp_inventory],
                original_filenames=["销售文件.csv", "库存文件.csv"],
            )

        self.assertTrue(upload["success"])
        self.assertEqual("销售文件.csv, 库存文件.csv", upload["file_name"])
        profiles = {table["table_name"]: table for table in upload["tables"]}
        self.assertEqual("销售文件.csv", profiles["销售文件"]["source_file"])
        self.assertEqual("库存文件.csv", profiles["库存文件"]["source_file"])
        self.assertEqual(["产品", "销售额"], [column["name"] for column in profiles["销售文件"]["columns"]])

    def test_upload_excel_datetime_profile_is_json_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xlsx_path = root / "sales_dates.xlsx"
            pd.DataFrame(
                {
                    "日期": [pd.Timestamp("2026-05-01"), pd.Timestamp("2026-05-02")],
                    "销售额": [100, 250],
                }
            ).to_excel(xlsx_path, index=False)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(xlsx_path, original_filename="销售日期.xlsx")

        self.assertTrue(upload["success"])
        json.dumps(upload, ensure_ascii=False)
        first_table = upload["tables"][0]
        date_column = next(column for column in first_table["columns"] if column["name"] == "日期")
        self.assertEqual("2026-05-01T00:00:00", date_column["sample_values"][0])

    def test_overview_sales_question_returns_summary_not_raw_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "saas_sales.csv"
            csv_path.write_text(
                "记录ID,日期,城市,客户类型,订阅收入,备注\n"
                "SS001,2026-01-01,上海,大客户,1000,实施中\n"
                "SS002,2026-01-02,北京,试用客户,300,标准服务\n"
                "SS003,2026-01-03,上海,中型企业,700,续费窗口\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="SaaS销售.csv")
            response = service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="看一下整体销售情况",
                execution_mode="dual",
            )

        self.assertTrue(response["success"])
        self.assertLess(len(response["answer"]), 260)
        self.assertIn("订阅收入合计", response["answer"])
        self.assertNotIn("SS001,2026-01-01,上海,大客户", response["answer"])
        self.assertEqual(["指标", "数值"], response["result"]["columns"])
        self.assertTrue(response["debug"]["user_experience_shaping"]["applied"])

    def test_generic_dataset_overview_message_uses_full_table_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "saas_sales.csv"
            csv_path.write_text(
                "记录ID,月份,区域,城市,订阅收入,毛利\n"
                "SS001,2026-01,华东,上海,1000,600\n"
                "SS002,2026-01,华北,北京,300,180\n"
                "SS003,2026-02,华东,杭州,700,420\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="SaaS销售.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="看一下这个数据",
                execution_mode="dual",
            )

        self.assertTrue(response["success"])
        self.assertEqual("overview", response["answer_type"])
        self.assertIn("3 行、6 列", response["answer"])
        self.assertIn("订阅收入", response["answer"])
        self.assertNotEqual("3", response["answer"])
        self.assertEqual(["指标", "数值"], response["result"]["columns"])
        self.assertTrue(response["debug"]["user_experience_shaping"]["applied"])
        self.assertEqual("dataset_overview", response["debug"]["message_intent"])

    def test_dataset_present_message_routes_meta_chat_without_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text("city,sales\nShanghai,100\nBeijing,150\n", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path)
            greeting = service.respond_to_message(dataset_id=upload["dataset_id"], question="你好")
            model = service.respond_to_message(dataset_id=upload["dataset_id"], question="你是什么模型")

        self.assertTrue(greeting["success"])
        self.assertEqual("chat", greeting["answer_type"])
        self.assertEqual("chat_with_dataset", greeting["debug"]["agent_mode"])
        self.assertIn("当前数据已就绪", greeting["answer"])
        self.assertEqual([], greeting["result"]["rows"])
        self.assertTrue(model["success"])
        self.assertEqual("chat", model["answer_type"])
        self.assertIn("VDS 数据分析助手", model["answer"])
        self.assertEqual("chat_with_dataset", model["debug"]["agent_mode"])

    def test_chat_without_dataset_returns_vds_reply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            response = service.chat_without_dataset(question="没有文件时你能做什么？")

        self.assertTrue(response["success"])
        self.assertEqual("chat", response["answer_type"])
        self.assertEqual("", response["dataset_id"])
        self.assertIn("上传数据后", response["answer"])
        self.assertEqual("chat_without_dataset", response["debug"]["agent_mode"])

    def test_analyze_unknown_dataset_returns_standard_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            response = service.analyze_dataset(dataset_id="ds_missing", question="Which city has highest sales?")

        self.assertFalse(response["success"])
        self.assertTrue(response["run_id"].startswith("run_"))
        self.assertEqual(response["errors"][0]["error_type"], "FILE_PARSE_ERROR")

    def test_external_run_accepts_chinese_inline_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            response = service.run_agent_with_inline_tables(
                question="哪个城市销售额最高？",
                request_id="external-001",
                tables=[
                    {
                        "table_name": "销售",
                        "rows": [
                            {"城市": "上海", "销售额": 100},
                            {"城市": "北京", "销售额": 150},
                            {"城市": "上海", "销售额": 200},
                        ],
                    }
                ],
            )

        self.assertTrue(response["success"])
        self.assertEqual("v1", response["response_version"])
        self.assertEqual("external-001", response["request_id"])
        self.assertTrue(response["run_id"].startswith("run_"))
        self.assertTrue(response["dataset_id"].startswith("ds_"))
        self.assertEqual("multi_agent", response["debug"]["agent_mode"])
        self.assertEqual("api_inline_tables", response["debug"]["api_source"])
        self.assertEqual({"城市": "上海", "销售额": 300}, response["result"]["rows"][0])
        self.assertEqual([], response["errors"])

    def test_external_run_accepts_english_table_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            response = service.run_agent_with_inline_tables(
                question="Which city has the highest sales?",
                tables={
                    "sales": {
                        "rows": [
                            {"city": "Shanghai", "sales": 100},
                            {"city": "Beijing", "sales": 150},
                            {"city": "Shanghai", "sales": 200},
                        ]
                    }
                },
            )

        self.assertTrue(response["success"])
        self.assertEqual({"city": "Shanghai", "sales": 300}, response["result"]["rows"][0])
        self.assertEqual("multi_agent", response["debug"]["agent_mode"])

    def test_external_run_rejects_invalid_payloads_with_standard_errors(self) -> None:
        cases = [
            {"question": "", "tables": [{"table_name": "sales", "rows": [{"city": "Shanghai"}]}], "error_type": "LOGIC_FORM_ERROR"},
            {"question": "Which city has highest sales?", "tables": [], "error_type": "FILE_PARSE_ERROR"},
            {
                "question": "Which city has highest sales?",
                "tables": [{"table_name": "sales", "rows": [["Shanghai", 100]]}],
                "error_type": "FILE_PARSE_ERROR",
            },
            {
                "question": "Which city has highest sales?",
                "tables": [
                    {"table_name": "sales", "rows": [{"city": "Shanghai", "sales": 100}]},
                    {"table_name": "sales", "rows": [{"city": "Beijing", "sales": 150}]},
                ],
                "error_type": "FILE_PARSE_ERROR",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            for case in cases:
                response = service.run_agent_with_inline_tables(
                    question=case["question"],
                    tables=case["tables"],
                    request_id="external-error",
                )
                self.assertFalse(response["success"], case)
                self.assertEqual("v1", response["response_version"])
                self.assertTrue(response["run_id"].startswith("run_"))
                self.assertEqual("external-error", response["request_id"])
                self.assertEqual(case["error_type"], response["errors"][0]["error_type"])


if __name__ == "__main__":
    unittest.main()
