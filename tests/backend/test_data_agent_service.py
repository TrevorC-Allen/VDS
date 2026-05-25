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
from data_agent_core.tracing.live_monitor import live_run_monitor


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

    def test_analyze_publishes_live_monitor_events(self) -> None:
        monitor_run_id = "test_monitor_service"
        live_run_monitor.clear(monitor_run_id)
        try:
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
                analysis = service.analyze_dataset(
                    dataset_id=upload["dataset_id"],
                    question="Which city has the highest sales?",
                    execution_mode="dual",
                    monitor_run_id=monitor_run_id,
                )

            events = live_run_monitor.history(monitor_run_id)
            global_events = live_run_monitor.history("workbench_live")
        finally:
            live_run_monitor.clear(monitor_run_id)
            live_run_monitor.clear("workbench_live")

        self.assertTrue(analysis["success"])
        event_types = [event["event_type"] for event in events]
        roles = {event["role"] for event in events if event.get("role")}
        self.assertIn("analysis_requested", event_types)
        self.assertIn("workflow_started", event_types)
        self.assertIn("agent_started", event_types)
        self.assertIn("agent_completed", event_types)
        self.assertIn("response_ready", event_types)
        self.assertIn("planner", roles)
        self.assertIn("response_builder", roles)
        self.assertNotIn("chain_of_thought", json.dumps(events, ensure_ascii=False))
        self.assertTrue(any(event["monitor_run_id"] == monitor_run_id for event in global_events))

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

    def test_upload_json_dataset_defaults_to_dataset_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_path = root / "sales.json"
            json_path.write_text(
                json.dumps(
                    [
                        {"city": "Shanghai", "sales": 100},
                        {"city": "Beijing", "sales": 150},
                    ]
                ),
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(json_path, original_filename="sales.json")

        self.assertTrue(upload["success"])
        self.assertEqual("dataset", upload["file_role"])
        self.assertEqual("sales.json", upload["file_name"])
        self.assertEqual(["city", "sales"], [column["name"] for column in upload["tables"][0]["columns"]])

    def test_rule_upload_requires_scope_and_does_not_create_dataset_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rule_path = root / "analysis_rules.yaml"
            rule_path.write_text(
                "language: zh-CN\n"
                "analysis_rules:\n"
                "  - 所有金额保留两位小数\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            missing_scope = service.upload_dataset(
                rule_path,
                original_filename="analysis_rules.yaml",
                file_role="rule",
            )
            uploaded_rule = service.upload_dataset(
                rule_path,
                original_filename="analysis_rules.yaml",
                file_role="rule",
                rule_scope="user_analysis",
            )

        self.assertFalse(missing_scope["success"])
        self.assertIn("rule_scope", missing_scope["errors"][0]["error_message"])
        self.assertTrue(uploaded_rule["success"], uploaded_rule.get("errors"))
        self.assertTrue(uploaded_rule["file_id"].startswith("rule_"))
        self.assertEqual("rule", uploaded_rule["file_role"])
        self.assertEqual("user_analysis", uploaded_rule["rule_scope"])
        self.assertNotIn("tables", uploaded_rule)

    def test_user_analysis_rule_is_explicit_analysis_context_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            rule_path = root / "analysis_rules.md"
            csv_path.write_text("city,sales\nShanghai,100\nBeijing,150\nShanghai,200\n", encoding="utf-8")
            rule_path.write_text("回答必须使用中文，并引用字段名。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            rule = service.upload_dataset(
                rule_path,
                original_filename="analysis_rules.md",
                file_role="rule",
                rule_scope="user_analysis",
            )
            without_rule = service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="Which city has the highest sales?",
                execution_mode="dual",
            )
            with_rule = service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="Which city has the highest sales?",
                execution_mode="dual",
                user_rule_file_id=rule["file_id"],
            )

        self.assertTrue(without_rule["success"])
        self.assertFalse(without_rule["debug"]["user_rule_context"]["enabled"])
        self.assertTrue(with_rule["success"], with_rule.get("errors"))
        self.assertTrue(with_rule["debug"]["user_rule_context"]["enabled"])
        self.assertEqual(rule["file_id"], with_rule["debug"]["user_rule_context"]["file_id"])

    def test_benchmark_rule_runs_only_through_benchmark_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            benchmark_path = root / "benchmark_rules.json"
            csv_path.write_text(
                "city,sales\n"
                "Shanghai,100\n"
                "Beijing,150\n"
                "Shanghai,200\n",
                encoding="utf-8",
            )
            benchmark_path.write_text(
                json.dumps(
                    {
                        "benchmark_name": "sales_smoke",
                        "questions": [
                            {
                                "id": "q1",
                                "question": "Which city has the highest sales?",
                                "expected_output": "Shanghai",
                            }
                        ],
                        "metrics": ["string_match"],
                    }
                ),
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            benchmark_rule = service.upload_dataset(
                benchmark_path,
                original_filename="benchmark_rules.json",
                file_role="rule",
                rule_scope="benchmark",
            )
            ordinary_analysis = service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="Which city has the highest sales?",
                user_rule_file_id=benchmark_rule["file_id"],
            )
            report = service.run_benchmark_from_rule(
                dataset_id=upload["dataset_id"],
                benchmark_rule_file_id=benchmark_rule["file_id"],
            )

        self.assertFalse(ordinary_analysis["success"])
        self.assertIn("expected user_analysis", ordinary_analysis["errors"][0]["error_message"])
        self.assertTrue(report["success"], report.get("errors"))
        self.assertEqual("sales_smoke", report["benchmark"])
        self.assertEqual(1, report["total"])
        self.assertEqual(1, report["scored"])
        self.assertEqual(1, report["correct"])
        self.assertEqual("q1", report["details"][0]["case_id"])
        self.assertNotIn("expected_output", json.dumps(report["details"], ensure_ascii=False))

    def test_upload_dabstep_context_package_enables_web_rule_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "storage"
            file_paths = _write_dabstep_context_package(root)
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="What are the possible values for the field account_type?",
                execution_mode="pandas",
            )
            reloaded_service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )
            reloaded_response = reloaded_service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="What are the possible values for the field account_type?",
                execution_mode="pandas",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertIn("DABstep context package", upload["file_name"])
        self.assertIn("规则上下文包", " ".join(upload["warnings"]))
        profiles = {table["table_name"]: table for table in upload["tables"]}
        self.assertIn("payments", profiles)
        self.assertIn("merchant_category_codes", profiles)
        self.assertIn("acquirer_countries", profiles)
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("dabstep_context", response["debug"]["dataset_kind"])
        self.assertIn("manual.md", response["debug"]["knowledge_files"])
        self.assertIn("A", response["answer"])
        self.assertIn("O", response["answer"])
        self.assertTrue(reloaded_response["success"], reloaded_response.get("errors"))
        self.assertEqual("dabstep_context", reloaded_response["debug"]["dataset_kind"])
        self.assertIn("O", reloaded_response["answer"])

    def test_incomplete_dabstep_context_upload_returns_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fees_path = root / "fees.json"
            fees_path.write_text("[]", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets([fees_path], original_filenames=["fees.json"])

        self.assertFalse(upload["success"])
        self.assertIn("DABstep context package is incomplete", upload["errors"][0]["error_message"])
        self.assertIn("payments.csv", upload["errors"][0]["error_message"])

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

    def test_message_conversation_persists_history_and_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            first = service.respond_to_message(question="你好")
            conversation_id = first["conversation_id"]
            second = service.respond_to_message(conversation_id=conversation_id, question="你是谁")
            renamed = service.rename_conversation(conversation_id, "VDS 助手介绍")
            listed = service.list_conversations()
            loaded = service.get_conversation(conversation_id)
            reloaded_service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )
            loaded_after_restart = reloaded_service.get_conversation(conversation_id)

        self.assertTrue(first["success"])
        self.assertTrue(conversation_id.startswith("conv_"))
        self.assertEqual(conversation_id, second["conversation_id"])
        self.assertEqual("VDS 助手介绍", renamed["conversation"]["title"])
        self.assertEqual(conversation_id, listed["conversations"][0]["conversation_id"])
        self.assertEqual("VDS 助手介绍", listed["conversations"][0]["title"])
        self.assertEqual("chat", listed["conversations"][0]["last_answer_type"])
        self.assertEqual(4, len(loaded["conversation"]["messages"]))
        self.assertEqual("user", loaded["conversation"]["messages"][0]["role"])
        self.assertEqual("assistant", loaded["conversation"]["messages"][1]["role"])
        self.assertEqual("chat", loaded["conversation"]["messages"][1]["payload"]["answer_type"])
        self.assertEqual("VDS 助手介绍", loaded_after_restart["conversation"]["title"])

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

def _write_dabstep_context_package(root: Path) -> list[Path]:
    fee_rule = {
        "ID": 1,
        "card_scheme": "GlobalCard",
        "account_type": [],
        "capture_delay": None,
        "monthly_fraud_level": None,
        "monthly_volume": None,
        "merchant_category_code": [],
        "is_credit": True,
        "aci": ["A"],
        "fixed_amount": 0.10,
        "rate": 0,
        "intracountry": None,
    }
    files = {
        "payments.csv": (
            "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,"
            "has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
            "SyntheticMerchant,2023,1,0,0,10.0,true,false,false,A,GlobalCard,NL,NL\n"
        ),
        "merchant_category_codes.csv": "mcc,description\n5411,Grocery Stores\n",
        "acquirer_countries.csv": "country_code,country\nNL,Netherlands\n",
        "fees.json": json.dumps([fee_rule]),
        "merchant_data.json": json.dumps(
            [{"merchant": "SyntheticMerchant", "account_type": "A", "capture_delay": "manual", "merchant_category_code": 5411}]
        ),
        "manual.md": (
            "## Account Types\n\n"
            "| Account Type | Description |\n"
            "|--------------|-------------|\n"
            "| A | Alpha |\n"
            "| O | Other |\n"
        ),
    }
    paths: list[Path] = []
    for filename, content in files.items():
        path = root / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


if __name__ == "__main__":
    unittest.main()
