"""Tests for the minimal backend Data Agent service shell."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.services.data_agent_service import DataAgentService, _suppress_raw_detail_answer
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
            single_agent_analysis = service.analyze_dataset(
                dataset_id=dataset_id,
                question="Which city has the highest sales?",
                execution_mode="dual",
                agent_mode="single_agent",
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
            self.assertTrue(analysis["reasoning_trace_view"])
            self.assertTrue(analysis["process_view_v2"]["steps"])
            self.assertEqual("single_agent", single_agent_analysis["debug"]["agent_mode"])
            self.assertTrue(single_agent_analysis["reasoning_trace_view"])
            self.assertTrue(single_agent_analysis["process_view_v2"]["steps"])

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
        serialized_events = json.dumps(events, ensure_ascii=False).lower()
        for forbidden in (
            "task_id",
            "standard_answer",
            "standard answer",
            "hidden_answer",
            "public_proxy",
            "public proxy",
            "raw_prompt",
            "raw prompt",
            "full_reasoning",
            "api_key",
            "scorer",
        ):
            self.assertNotIn(forbidden, serialized_events)
        response_ready = next(event for event in events if event["event_type"] == "response_ready")
        self.assertIn("process_view_v2", response_ready["payload"])
        self.assertNotIn("response", response_ready["payload"])
        self.assertNotIn("debug", response_ready["payload"])
        self.assertNotIn("trace_path", response_ready["payload"])
        self.assertNotIn("reasoning_trace_view", response_ready["payload"])
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

    def test_uploaded_dataset_tables_restore_after_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sales_path = root / "tmp_sales_upload.csv"
            inventory_path = root / "tmp_inventory_upload.csv"
            sales_path.write_text("产品,销售额\nA,100\nB,300\n", encoding="utf-8")
            inventory_path.write_text("产品,库存量\nA,10\nC,80\n", encoding="utf-8")
            store = TempFileStore(root / "storage")
            service = DataAgentService(file_store=store, llm_client=MockLLMClient())

            upload = service.upload_datasets(
                [sales_path, inventory_path],
                original_filenames=["销售文件.csv", "库存文件.csv"],
            )
            dataset_id = upload["dataset_id"]
            restarted_store = TempFileStore(root / "storage")
            restored_tables = restarted_store.get_tables(dataset_id)

        self.assertTrue(upload["success"])
        self.assertIsNotNone(restored_tables)
        self.assertEqual(2, len(restored_tables or {}))
        self.assertEqual(["产品", "销售额"], list((restored_tables or {})["销售文件"].columns))
        self.assertEqual(["产品", "库存量"], list((restored_tables or {})["库存文件"].columns))

    def test_legacy_multi_source_restore_recovers_table_names_by_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sales_path = root / "z_tmp_sales_upload.csv"
            inventory_path = root / "a_tmp_inventory_upload.csv"
            sales_path.write_text("产品,销售额\nA,100\nB,300\n", encoding="utf-8")
            inventory_path.write_text("产品,库存量\nA,10\nC,80\n", encoding="utf-8")
            store = TempFileStore(root / "storage")
            service = DataAgentService(file_store=store, llm_client=MockLLMClient())

            upload = service.upload_datasets(
                [sales_path, inventory_path],
                original_filenames=["销售文件.csv", "库存文件.csv"],
            )
            dataset_id = upload["dataset_id"]
            marker_path = root / "storage" / "datasets" / dataset_id / "multi_source.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker.pop("stored_files", None)
            marker.pop("source_file_map", None)
            marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")

            restarted_store = TempFileStore(root / "storage")
            restored_tables = restarted_store.get_tables(dataset_id)

        self.assertTrue(upload["success"])
        self.assertIsNotNone(restored_tables)
        self.assertEqual(["产品", "销售额"], list((restored_tables or {})["销售文件"].columns))
        self.assertEqual(["产品", "库存量"], list((restored_tables or {})["库存文件"].columns))

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
        self.assertEqual(rule["file_id"], with_rule["debug"]["user_rule_context"]["files"][0]["file_id"])

    def test_auto_bound_rule_file_uploaded_with_dataset_applies_to_analysis_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            rule_path = root / "manual.md"
            csv_path.write_text("city,sales\nShanghai,100\nBeijing,150\nShanghai,200\n", encoding="utf-8")
            rule_path.write_text("sales 表示成交销售额，回答要说明字段含义。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [csv_path, rule_path],
                original_filenames=["sales.csv", "manual.md"],
            )
            profile = service.get_dataset_profile(upload["dataset_id"])
            response = service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="Which city has the highest sales?",
                execution_mode="dual",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertEqual(1, len(upload["auto_bound_user_rule_file_ids"]))
        self.assertEqual(upload["auto_bound_user_rule_file_ids"], profile["auto_bound_user_rule_file_ids"])
        self.assertTrue(response["success"], response.get("errors"))
        self.assertTrue(response["debug"]["user_rule_context"]["enabled"])
        self.assertTrue(response["debug"]["user_rule_context"]["auto_bound"])
        self.assertEqual(upload["auto_bound_user_rule_file_ids"][0], response["debug"]["user_rule_context"]["files"][0]["file_id"])

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
        self.assertEqual("overview", response["answer_type"])
        self.assertIn("overview_report", response)
        self.assertIn("订阅收入合计", response["answer"])
        self.assertNotIn("SS001,2026-01-01,上海,大客户", response["answer"])
        self.assertEqual(["指标", "数值"], response["result"]["columns"])
        self.assertTrue(response["execution_artifacts"])
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
        self.assertIn("overview_report", response)
        self.assertEqual("overview_report", response["overview_report"]["report_type"])
        self.assertNotEqual("3", response["answer"])
        self.assertEqual(["指标", "数值"], response["result"]["columns"])
        self.assertTrue(response["insight"]["business_suggestions"])
        self.assertIn("依据", response["insight"]["business_suggestions"][0])
        self.assertTrue(response["execution_artifacts"])
        self.assertIn("python", {item["language"] for item in response["execution_artifacts"]})
        self.assertTrue(response["debug"]["user_experience_shaping"]["applied"])
        self.assertEqual("dataset_overview", response["debug"]["message_intent"])
        self.assertEqual("dataset_overview", response["process_view_v2"]["mode"])
        self.assertTrue(response["process_view_v2"]["steps"])

    def test_multi_table_field_overview_never_dumps_detail_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "orders.csv"
            customers_path = root / "customers.csv"
            orders_path.write_text(
                "InvoiceNo,StockCode,Description,Quantity,UnitPrice,CustomerID,Country\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2.55,17850,United Kingdom\n"
                "536365,71053,WHITE METAL LANTERN,6,3.39,17850,United Kingdom\n"
                "536366,22633,HAND WARMER UNION JACK,-1,1.85,,United Kingdom\n",
                encoding="utf-8",
            )
            customers_path.write_text(
                "CustomerID,Segment,Region\n"
                "17850,Retail,UK\n"
                "13047,Wholesale,UK\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [orders_path, customers_path],
                original_filenames=["orders.csv", "customers.csv"],
            )
            field_response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这几个表什么意思，有什么字段",
                execution_mode="dual",
            )
            story_response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这个数据主要讲什么？",
                execution_mode="dual",
            )

        for response in (field_response, story_response):
            self.assertTrue(response["success"])
            self.assertEqual("overview", response["answer_type"])
            self.assertEqual("multi_table_dataset_overview", response["debug"]["operation"])
            self.assertEqual(["表名", "来源", "行数", "列数", "可能含义", "关键字段"], response["result"]["columns"])
            payload = json.dumps(response, ensure_ascii=False)
            self.assertIn("orders", response["answer"])
            self.assertIn("customers", response["answer"])
            self.assertNotIn("WHITE HANGING HEART T-LIGHT HOLDER,6,2.55", payload)
            self.assertNotIn("WHITE METAL LANTERN,6,3.39", payload)

    def test_cleaning_guidance_routes_before_detail_lookup_and_keeps_source_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "retail.csv"
            csv_path.write_text(
                "InvoiceNo,StockCode,Description,Quantity,UnitPrice,CustomerID,Country\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2.55,17850,United Kingdom\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2.55,17850,United Kingdom\n"
                "536366,22633,HAND WARMER UNION JACK,-1,1.85,,United Kingdom\n"
                "536367,22632,HAND WARMER RED POLKA DOT,10000,1.85,13047,United Kingdom\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="retail.csv")
            policy = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="给出建议清洗规则、影响行数、影响比例，并说明是否需要用户确认。",
                execution_mode="dual",
            )
            boundary = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="你会直接修改原始数据吗？",
                execution_mode="dual",
            )

        self.assertTrue(policy["success"])
        self.assertEqual("cleaning_simulation", policy["answer_type"])
        self.assertIn("建议清洗规则", policy["answer"])
        self.assertIn("影响", policy["answer"])
        self.assertIn("不能覆盖原始文件", policy["answer"])
        self.assertEqual(["表名", "规则", "影响行数", "影响比例", "建议"], policy["result"]["columns"])
        self.assertNotIn("WHITE HANGING HEART T-LIGHT HOLDER,6,2.55", json.dumps(policy, ensure_ascii=False))
        self.assertTrue(policy["debug"]["user_experience_shaping"]["applied"])
        self.assertTrue(boundary["success"])
        self.assertEqual("chat", boundary["answer_type"])
        self.assertIn("不会直接修改原始数据", boundary["answer"])
        self.assertIn("必须等用户明确确认", boundary["answer"])

    def test_raw_detail_exit_guard_replaces_agent_csv_dump_with_overview(self) -> None:
        rows = [
            "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2.55,17850,United Kingdom",
            "536365,71053,WHITE METAL LANTERN,6,3.39,17850,United Kingdom",
            "536367,22745,POPPY'S PLAYHOUSE BEDROOM,6,2.10,13047,United Kingdom",
            "536367,22748,POPPY'S PLAYHOUSE KITCHEN,6,2.10,13047,United Kingdom",
            "536367,84969,BOX OF 6 ASSORTED COLOUR TEASPOONS,6,4.25,13047,United Kingdom",
            "536367,22623,BOX OF VINTAGE JIGSAW BLOCKS,3,4.95,13047,United Kingdom",
        ]
        raw_answer = ", ".join(rows * 6)
        payload = {
            "response_version": "v1",
            "success": True,
            "run_id": "run_raw_dump",
            "dataset_id": "dataset_raw_dump",
            "question": "给我一个结论。",
            "answer_type": "analysis",
            "execution_mode": "dual",
            "answer": raw_answer,
            "result": {"columns": [], "rows": [], "value": None},
            "debug": {"agent_mode": "multi_agent"},
        }
        tables = {
            "online_retail": pd.DataFrame(
                [
                    {
                        "InvoiceNo": "536365",
                        "StockCode": "85123A",
                        "Description": "WHITE HANGING HEART T-LIGHT HOLDER",
                        "Quantity": 6,
                        "InvoiceDate": "2026-01-01 08:26:00",
                        "UnitPrice": 2.55,
                        "CustomerID": 17850,
                        "Country": "United Kingdom",
                    },
                    {
                        "InvoiceNo": "536366",
                        "StockCode": "22633",
                        "Description": "HAND WARMER UNION JACK",
                        "Quantity": 6,
                        "InvoiceDate": "2026-01-01 08:28:00",
                        "UnitPrice": 1.85,
                        "CustomerID": 17850,
                        "Country": "United Kingdom",
                    },
                ]
            )
        }

        guarded = _suppress_raw_detail_answer(
            payload,
            question="给我一个结论。",
            tables=tables,
            profile=None,
            agent_mode="multi_agent",
        )

        serialized = json.dumps(guarded, ensure_ascii=False)
        self.assertEqual("overview", guarded["answer_type"])
        self.assertEqual("dataset_overview", guarded["debug"]["message_intent"])
        self.assertTrue(guarded["debug"]["raw_detail_answer_guard"]["applied"])
        self.assertIn("online_retail", guarded["answer"])
        self.assertIn("订单 / 零售交易明细表", guarded["answer"])
        self.assertIn("InvoiceDate：时间字段", guarded["answer"])
        self.assertIn("Country：地理或区域维度", guarded["answer"])
        self.assertNotIn("WHITE HANGING HEART T-LIGHT HOLDER,6,2.55", serialized)

    def test_broad_dataset_readiness_questions_do_not_return_row_count_only(self) -> None:
        questions = [
            "这个数据适合做哪些分析？",
            "这个数据正常吗？",
            "这个数据能不能用？",
            "这个数据能不能做趋势、环比或同比？",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "retail.csv"
            csv_path.write_text(
                "InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2026-01-01 08:26:00,2.55,17850,United Kingdom\n"
                "536366,22633,HAND WARMER UNION JACK,-1,2026-01-02 09:00:00,1.85,,United Kingdom\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_dataset(csv_path, original_filename="retail.csv")
            responses = [
                service.respond_to_message(dataset_id=upload["dataset_id"], question=question, execution_mode="dual")
                for question in questions
            ]

        for response in responses:
            self.assertTrue(response["success"], response.get("errors"))
            self.assertIn(response["answer_type"], {"overview", "cleaning_simulation"})
            self.assertNotEqual("2", str(response["answer"]).strip())
            self.assertNotIn("WHITE HANGING HEART T-LIGHT HOLDER,6,2026", json.dumps(response, ensure_ascii=False))

    def test_dataset_overview_generalizes_beyond_payments_tables(self) -> None:
        cases = [
            (
                "subscription.csv",
                "客户,月份,套餐,订阅收入,是否流失\nA,2026-01,Pro,1000,false\nB,2026-01,Basic,200,true\n",
                "订阅收入",
            ),
            (
                "inventory.csv",
                "仓库,产品,库存量,安全库存,是否缺货\n上海,A,30,20,false\n北京,B,5,10,true\n",
                "库存量",
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            responses = []
            for file_name, content, metric in cases:
                path = root / file_name
                path.write_text(content, encoding="utf-8")
                upload = service.upload_dataset(path, original_filename=file_name)
                responses.append(
                    (
                        metric,
                        service.respond_to_message(
                            dataset_id=upload["dataset_id"],
                            question="总结一下这个表",
                            execution_mode="dual",
                        ),
                    )
                )

        for metric, response in responses:
            self.assertTrue(response["success"], response.get("errors"))
            self.assertEqual("overview", response["answer_type"])
            self.assertEqual(metric, response["overview_report"]["metric_column"])
            self.assertIn(metric, response["answer"])
            self.assertNotIn("MCC", response["answer"])

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
        self.assertEqual("chat", greeting["process_view_v2"]["mode"])
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
        self.assertEqual("chat", response["process_view_v2"]["mode"])

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

    def test_conversation_can_move_into_project_and_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            first = service.respond_to_message(question="你好")
            conversation_id = first["conversation_id"]
            project = service.create_project(name="可归档 Project")
            project_id = project["project"]["project_id"]
            moved = service.update_conversation(conversation_id, project_id=project_id)
            listed_project = service.list_conversations(project_id=project_id)
            loaded_project = service.get_project(project_id)
            deleted = service.delete_conversation(conversation_id)
            listed_after_delete = service.list_conversations(project_id=project_id)
            project_after_delete = service.get_project(project_id)

        self.assertTrue(moved["success"], moved.get("errors"))
        self.assertEqual(project_id, moved["conversation"]["project_id"])
        self.assertEqual(conversation_id, listed_project["conversations"][0]["conversation_id"])
        self.assertEqual([conversation_id], loaded_project["project"]["conversation_ids"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual([], listed_after_delete["conversations"])
        self.assertEqual([], project_after_delete["project"]["conversation_ids"])

    def test_project_rename_and_delete_detaches_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            project_id = service.create_project(name="旧项目")["project"]["project_id"]
            created = service.create_conversation(title="项目对话", project_id=project_id)
            conversation_id = created["conversation"]["conversation_id"]
            renamed = service.update_project(project_id, name="新项目名")
            deleted = service.delete_project(project_id)
            conversation = service.get_conversation(conversation_id)
            project_lookup = service.get_project(project_id)

        self.assertEqual("新项目名", renamed["project"]["name"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual(1, deleted["detached_conversation_count"])
        self.assertEqual("", conversation["conversation"]["project_id"])
        self.assertFalse(project_lookup["success"])

    def test_project_workspace_memory_sources_and_conversation_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            project = service.create_project(name="销售 Project", instructions="回答要优先说明口径。")
            project_id = project["project"]["project_id"]
            memory = service.create_project_memory(project_id, content="销售额字段代表含税成交金额。", title="销售口径")
            source = service.create_project_source(
                project_id,
                source_type="note",
                title="项目说明",
                content="只分析本项目上传的数据。",
            )
            first = service.respond_to_message(project_id=project_id, question="你好")
            outside = service.respond_to_message(question="你好")
            listed_project = service.list_conversations(project_id=project_id)
            loaded_project = service.get_project(project_id)

        self.assertTrue(project_id.startswith("proj_"))
        self.assertTrue(memory["memory"]["memory_id"].startswith("mem_"))
        self.assertTrue(source["source"]["source_id"].startswith("src_"))
        self.assertEqual(project_id, first["project_id"])
        self.assertEqual(project_id, first["conversation"]["project_id"])
        self.assertEqual(project_id, first["debug"]["project_context"]["project_id"])
        self.assertEqual(1, first["debug"]["project_context"]["memory_count"])
        self.assertEqual(1, first["debug"]["project_context"]["source_count"])
        self.assertEqual("", outside.get("project_id", ""))
        self.assertEqual(1, len(listed_project["conversations"]))
        self.assertEqual(project_id, listed_project["conversations"][0]["project_id"])
        self.assertEqual([first["conversation_id"]], loaded_project["project"]["conversation_ids"])

    def test_project_upload_sources_default_dataset_and_project_only_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text("city,sales\n上海,100\n北京,80\n", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            project_id = service.create_project(name="项目文件")["project"]["project_id"]
            upload = service.upload_project_sources(project_id, [csv_path], original_filenames=["sales.csv"])
            overview = service.respond_to_message(project_id=project_id, question="看一下这个数据")
            loaded = service.get_project(project_id)

        self.assertTrue(upload["success"])
        self.assertTrue(upload["dataset_id"].startswith("ds_"))
        self.assertEqual(project_id, upload["project_id"])
        self.assertEqual("dataset", upload["project_sources"][0]["source_type"])
        self.assertEqual(upload["dataset_id"], loaded["project"]["default_dataset_id"])
        self.assertEqual(upload["dataset_id"], overview["dataset_id"])
        self.assertEqual(project_id, overview["conversation"]["project_id"])
        self.assertEqual("project_only", overview["project"]["memory_mode"])

    def test_project_text_source_upload_does_not_create_dataset_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            note_path = root / "instructions.md"
            note_path.write_text("按含税 GMV 口径回答，引用项目说明。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            project_id = service.create_project(name="说明文件")["project"]["project_id"]
            upload = service.upload_project_sources(project_id, [note_path], original_filenames=["instructions.md"])
            loaded = service.get_project(project_id)
            reply = service.respond_to_message(project_id=project_id, question="你好")

        self.assertTrue(upload["success"])
        self.assertEqual(project_id, upload["project_id"])
        self.assertEqual("project_source", upload["file_role"])
        self.assertEqual("", upload.get("dataset_id", ""))
        self.assertEqual("note", upload["project_sources"][0]["source_type"])
        self.assertEqual("instructions.md", upload["project_sources"][0]["title"])
        self.assertIn("含税 GMV", loaded["project"]["sources"][0]["content"])
        self.assertEqual("", loaded["project"]["default_dataset_id"])
        self.assertEqual("", reply["dataset_id"])
        self.assertEqual(1, reply["project"]["source_count"])

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
