"""Tests for the minimal backend Data Agent service shell."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from backend.services.data_agent_service import DataAgentService, _suppress_raw_detail_answer
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.tracing.live_monitor import live_run_monitor


class PresentationLLMClient(MockLLMClient):
    def __init__(self) -> None:
        self.stage_names: list[str] = []
        self.temperatures: list[float] = []

    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        payload = json.loads(messages[-1]["content"])
        stage_name = str(payload.get("stage_name") or "")
        self.stage_names.append(stage_name)
        self.temperatures.append(temperature)
        if stage_name == "fast_path_presentation":
            return {
                "display_answer": "这份数据可以先按订单、客户、月份和销售额理解：它不是单纯行列表，而是后续做客户、时间和销售指标分析的基础表。",
                "summary": "AI 已复核这组表，关键是先确定主事实表和关联边界。",
                "next_step": "下一步先确认订单明细表与客户维表的关联键，再做趋势分析。",
                "next_questions": ["哪张表适合作为主事实表？", "这些表能按哪些字段关联？"],
                "confidence": 0.73,
                "reasoning_summary": "基于已验证 overview 结果做表达整理。",
            }
        return super().complete_json(messages, temperature=temperature)


class SummaryOnlyPresentationLLMClient(PresentationLLMClient):
    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        payload = json.loads(messages[-1]["content"])
        stage_name = str(payload.get("stage_name") or "")
        self.stage_names.append(stage_name)
        self.temperatures.append(temperature)
        if stage_name == "fast_path_presentation":
            return {
                "summary": "AI 已把这次概览收敛到订单事实表和销售指标，不再只复述行列数。",
                "next_step": "下一步按月份看销售额趋势。",
                "next_questions": ["按月份看销售额趋势吗？"],
                "confidence": 0.71,
                "reasoning_summary": "只返回 summary，测试主回答前导语兜底。",
            }
        return super().complete_json(messages, temperature=temperature)


class EnglishInsightPresentationLLMClient(PresentationLLMClient):
    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        payload = json.loads(messages[-1]["content"])
        stage_name = str(payload.get("stage_name") or "")
        self.stage_names.append(stage_name)
        self.temperatures.append(temperature)
        if stage_name == "fast_path_presentation":
            return {
                "display_answer": "已根据后端验证结果整理，首要结论可以继续围绕国家或地区维度下钻。",
                "summary": "The top 10 ranking of eur_amount by ip_country shows NL leading.",
                "next_step": "The result includes only 8 countries, not a full top 10.",
                "next_questions": ["Compare the top countries by eur_amount?", "Which country is leading?"],
                "confidence": 0.74,
                "reasoning_summary": "Mocked English leakage from presentation LLM.",
            }
        return super().complete_json(messages, temperature=temperature)


class DirectChatLLMClient(MockLLMClient):
    def __init__(self) -> None:
        self.stage_names: list[str] = []
        self.temperatures: list[float] = []

    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        payload = json.loads(messages[-1]["content"])
        stage_name = str(payload.get("stage_name") or "")
        self.stage_names.append(stage_name)
        self.temperatures.append(temperature)
        if stage_name == "direct_chat":
            return {
                "answer": "可以。你现在是在和直连 LLM 对话；如果你问具体数据结论，我会把问题交给后端数据分析 agent 去算。",
                "handoff_hint": "涉及数据计算、图表或 join 时交给数据分析链路。",
                "confidence": 0.82,
                "reasoning_summary": "普通能力说明问题，直接聊天回复。",
            }
        return super().complete_json(messages, temperature=temperature)


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
            self.assertEqual("sales.csv", analysis["source_references"][0]["file_name"])
            self.assertEqual(["sales"], [table["table_name"] for table in analysis["source_references"][0]["tables"]])
            self.assertTrue(analysis["reasoning_trace_view"])
            self.assertTrue(analysis["process_view_v2"]["steps"])
            self.assertTrue(analysis["activity_trace_v2"])
            self.assertIn("pandas_executor", {node["role"] for node in analysis["activity_trace_v2"]})
            self.assertIn("sql_executor", {node["role"] for node in analysis["activity_trace_v2"]})
            self.assertIn("verifier", {node["role"] for node in analysis["activity_trace_v2"]})
            self.assertTrue(analysis["execution_artifacts"])
            self.assertTrue(any(node.get("artifacts") for node in analysis["activity_trace_v2"]))
            self.assertEqual("single_agent", single_agent_analysis["debug"]["agent_mode"])
            self.assertTrue(single_agent_analysis["reasoning_trace_view"])
            self.assertTrue(single_agent_analysis["process_view_v2"]["steps"])
            self.assertTrue(single_agent_analysis["activity_trace_v2"])

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
        self.assertIn("activity_trace_delta", event_types)
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
        self.assertIn("activity_trace_v2", response_ready["payload"])
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
        self.assertEqual("", uploaded_rule["bound_dataset_id"])
        self.assertNotIn("dataset_id", uploaded_rule)
        self.assertNotIn("tables", uploaded_rule)

    def test_dataset_bound_rule_file_is_auto_detected_without_rule_form_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sales_path = root / "sales.csv"
            rule_path = root / "analysis_rules.md"
            sales_path.write_text("city,sales\n上海,100\n北京,150\n", encoding="utf-8")
            rule_path.write_text("回答只展示城市名称，不要返回数值。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(sales_path, original_filename="sales.csv")
            rule_upload = service.upload_datasets(
                [rule_path],
                original_filenames=["analysis_rules.md"],
                bind_dataset_id=upload["dataset_id"],
            )
            profile = service.get_dataset_profile(upload["dataset_id"])

        self.assertTrue(rule_upload["success"], rule_upload.get("errors"))
        self.assertEqual("rule", rule_upload["file_role"])
        self.assertEqual(upload["dataset_id"], rule_upload["bound_dataset_id"])
        self.assertEqual(rule_upload["file_ids"], rule_upload["auto_bound_user_rule_file_ids"])
        self.assertEqual(rule_upload["file_ids"], profile["auto_bound_user_rule_file_ids"])
        self.assertEqual("analysis_rules.md", profile["auto_bound_rule_files"][0]["file_name"])

    def test_bound_rule_upload_uses_bound_dataset_id_not_dataset_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            rule_path = root / "analysis_rules.md"
            csv_path.write_text("city,sales\nShanghai,100\n", encoding="utf-8")
            rule_path.write_text("回答必须说明规则来源。", encoding="utf-8")
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
                bind_dataset_id=upload["dataset_id"],
            )

        self.assertTrue(rule["success"], rule.get("errors"))
        self.assertEqual(upload["dataset_id"], rule["bound_dataset_id"])
        self.assertNotIn("dataset_id", rule)

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

    def test_user_analysis_rule_can_constrain_final_answer_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales2.csv"
            rule_path = root / "analysis_rules.md"
            csv_path.write_text("city,sales\nShanghai,120\nBeijing,80\n", encoding="utf-8")
            rule_path.write_text("只回答城市，不要返回数值。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="sales2.csv")
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

        self.assertTrue(without_rule["success"], without_rule.get("errors"))
        self.assertTrue(with_rule["success"], with_rule.get("errors"))
        self.assertEqual("Shanghai", with_rule["answer"])
        self.assertNotRegex(with_rule["answer"], r"\d")
        self.assertNotEqual(without_rule["answer"], with_rule["answer"])
        self.assertTrue(with_rule["debug"]["user_rule_output_constraints_applied"]["entity_only"])
        self.assertTrue(with_rule["debug"]["user_rule_output_constraints_applied"]["suppress_numbers"])

    def test_message_without_dataset_can_inspect_enabled_user_rule_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rule_path = root / "analysis_rules.md"
            rule_path.write_text("金额保留两位小数；回答必须说明规则来源。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            rule = service.upload_dataset(
                rule_path,
                original_filename="analysis_rules.md",
                file_role="rule",
                rule_scope="user_analysis",
            )
            response = service.respond_to_message(
                question="规则是什么，我要看",
                user_rule_file_id=rule["file_id"],
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("chat", response["answer_type"])
        self.assertEqual("chat_without_dataset", response["debug"]["agent_mode"])
        self.assertTrue(response["debug"]["user_rule_context"]["enabled"])
        self.assertTrue(response["debug"]["answered_from_user_rule_context"])
        self.assertIn("analysis_rules.md", response["answer"])
        self.assertIn("金额保留两位小数", response["answer"])
        self.assertIn("不会被当成数据表", response["answer"])
        self.assertNotIn("当前没有上传数据", response["answer"])

    def test_message_with_dataset_can_inspect_bound_user_rule_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            rule_path = root / "manual.md"
            csv_path.write_text("city,sales\nShanghai,100\n", encoding="utf-8")
            rule_path.write_text("sales 表示成交销售额，城市维度来自 city。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [csv_path, rule_path],
                original_filenames=["sales.csv", "manual.md"],
            )
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="看一下启用的规则文件",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("chat_with_dataset", response["debug"]["agent_mode"])
        self.assertTrue(response["debug"]["user_rule_context"]["enabled"])
        self.assertTrue(response["debug"]["user_rule_context"]["auto_bound"])
        self.assertTrue(response["debug"]["answered_from_user_rule_context"])
        self.assertIn("manual.md", response["answer"])
        self.assertIn("成交销售额", response["answer"])
        self.assertNotIn("当前数据已经上传", response["answer"])

    def test_json_array_user_analysis_rule_uploads_and_applies_to_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            rule_path = root / "analysis_rules.json"
            csv_path.write_text("city,sales\nShanghai,100\nBeijing,150\n", encoding="utf-8")
            rule_path.write_text(
                json.dumps(["回答必须使用中文。", {"rounding": "金额保留两位小数"}], ensure_ascii=False),
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            rule = service.upload_dataset(
                rule_path,
                original_filename="analysis_rules.json",
                file_role="rule",
                rule_scope="user_analysis",
            )
            guidelines, context = service._guidelines_with_user_rule(
                "",
                user_rule_file_id=rule["file_id"],
                dataset_id=upload["dataset_id"],
            )
            response = service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="Which city has the highest sales?",
                execution_mode="dual",
                user_rule_file_id=rule["file_id"],
            )

        self.assertTrue(rule["success"], rule.get("errors"))
        self.assertEqual("rule", rule["file_role"])
        self.assertEqual("user_analysis", rule["rule_scope"])
        self.assertIn("回答必须使用中文", guidelines)
        self.assertIn("金额保留两位小数", guidelines)
        self.assertTrue(context["enabled"])
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual(rule["file_id"], response["debug"]["user_rule_context"]["file_id"])

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

    def test_bound_fee_rule_files_enable_fee_id_lookup_for_uploaded_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payments_path = root / "payments.csv"
            fees_path = root / "fees.json"
            merchant_data_path = root / "merchant_data.json"
            manual_path = root / "manual.md"
            payments_path.write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,"
                "has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "Rafa_AI,2023,335,11,15,18.55,true,false,false,D,GlobalCard,GR,NL\n",
                encoding="utf-8",
            )
            fees_path.write_text(
                json.dumps(
                    [
                        {
                            "ID": 10,
                            "card_scheme": "GlobalCard",
                            "account_type": ["H"],
                            "capture_delay": None,
                            "monthly_fraud_level": None,
                            "monthly_volume": None,
                            "merchant_category_code": [],
                            "is_credit": None,
                            "aci": ["D"],
                            "fixed_amount": 0.10,
                            "rate": 0,
                            "intracountry": None,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            merchant_data_path.write_text(
                json.dumps([{"merchant": "Rafa_AI", "account_type": "H", "capture_delay": "manual", "merchant_category_code": 5411}]),
                encoding="utf-8",
            )
            manual_path.write_text("Fee rules for demo validation.", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(payments_path, original_filename="payments.csv")
            dataset_id = upload["dataset_id"]
            for path in (fees_path, merchant_data_path, manual_path):
                rule = service.upload_dataset(
                    path,
                    original_filename=path.name,
                    file_role="rule",
                    rule_scope="user_analysis",
                    bind_dataset_id=dataset_id,
                )
                self.assertTrue(rule["success"], rule.get("errors"))
            response = service.respond_to_message(
                dataset_id=dataset_id,
                question="What is the fee ID or IDs that apply to account_type = H and aci = D?",
                execution_mode="pandas",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("fee_ids_for_filters", response["logic_form"]["operation"])
        self.assertEqual([10], response["result"]["value"])
        self.assertIn("10", response["answer"])
        self.assertTrue(response["debug"]["rule_augmented_fee_context"])
        self.assertIn("查看这些 Fee ID", response["insight"]["next_step"])

    def test_bound_fee_rule_files_enable_applicable_fee_ids_lookup_for_uploaded_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payments_path = root / "payments.csv"
            fees_path = root / "fees.json"
            merchant_data_path = root / "merchant_data.json"
            manual_path = root / "manual.md"
            payments_path.write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,"
                "has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "Rafa_AI,2023,335,11,15,18.55,true,false,false,D,GlobalCard,GR,NL\n",
                encoding="utf-8",
            )
            fees_path.write_text(
                json.dumps(
                    [
                        {
                            "ID": 10,
                            "card_scheme": "GlobalCard",
                            "account_type": ["H"],
                            "capture_delay": None,
                            "monthly_fraud_level": None,
                            "monthly_volume": None,
                            "merchant_category_code": [],
                            "is_credit": None,
                            "aci": ["D"],
                            "fixed_amount": 0.10,
                            "rate": 0,
                            "intracountry": None,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            merchant_data_path.write_text(
                json.dumps([{"merchant": "Rafa_AI", "account_type": "H", "capture_delay": "manual", "merchant_category_code": 5411}]),
                encoding="utf-8",
            )
            manual_path.write_text("Fee rules for demo validation.", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(payments_path, original_filename="payments.csv")
            dataset_id = upload["dataset_id"]
            for path in (fees_path, merchant_data_path, manual_path):
                rule = service.upload_dataset(
                    path,
                    original_filename=path.name,
                    file_role="rule",
                    rule_scope="user_analysis",
                    bind_dataset_id=dataset_id,
                )
                self.assertTrue(rule["success"], rule.get("errors"))
            response = service.respond_to_message(
                dataset_id=dataset_id,
                question="What were the applicable Fee IDs for Rafa_AI in December 2023?",
                execution_mode="pandas",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("applicable_fee_ids", response["logic_form"]["operation"])
        self.assertEqual([10], response["result"]["value"])
        self.assertIn("10", response["answer"])
        self.assertTrue(response["debug"]["rule_augmented_fee_context"])
        self.assertIn("展开这些 Fee ID", response["insight"]["next_step"])

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

    def test_dabstep_source_file_question_reads_knowledge_files_not_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _write_dabstep_context_package(root)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="还有几个文件是干什么用的",
                execution_mode="dual",
            )
            manual_response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="manual.md 是干什么用的？",
                execution_mode="dual",
            )
            fees_response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="fees.json 是干什么用的？",
                execution_mode="dual",
            )
            form_content_response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这些表单有什么内容",
                execution_mode="dual",
            )
            colloquial_content_response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这里面都装了啥",
                execution_mode="dual",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        for payload in (response, manual_response, fees_response, form_content_response, colloquial_content_response):
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertTrue(payload["success"], payload.get("errors"))
            self.assertEqual("overview", payload["answer_type"])
            self.assertEqual("dataset_source_overview", payload["debug"]["operation"])
            self.assertEqual("dataset_source_overview", payload["debug"]["message_intent"])
            self.assertNotEqual("Not Applicable", payload["answer"])
            self.assertNotIn('"answer": "Not Applicable"', serialized)
            self.assertIn("manual.md", serialized)
            self.assertIn("fees.json", serialized)
            self.assertIn("merchant_data.json", serialized)
            self.assertIn("业务说明手册", serialized)
            self.assertIn("费率规则", serialized)
            self.assertEqual(["文件", "类型", "用途", "读取状态", "关键内容"], payload["result"]["columns"])
            self.assertEqual("dataset_source_overview", payload["process_view_v2"]["mode"])
            self.assertGreaterEqual(len(payload["process_view_v2"]["steps"]), 6)
            self.assertTrue(any("Python / Pandas" in step["title"] for step in payload["process_view_v2"]["steps"]))
            self.assertTrue(payload["execution_artifacts"])
            self.assertIn("import pandas as pd", payload["execution_artifacts"][0]["code"])
            self.assertIn("sql", {item["language"] for item in payload["execution_artifacts"]})
            self.assertTrue(any("source_manifest" in item["code"] for item in payload["execution_artifacts"] if item["language"] == "sql"))

    def test_dabstep_total_fees_question_uses_analysis_not_source_overview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _write_dabstep_context_package(root)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="For the 1st of the year 2023, what is the total fees that SyntheticMerchant should pay?",
                execution_mode="dual",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("total_fees", response["logic_form"]["operation"])
        self.assertEqual("number", response["answer_type"])
        self.assertNotEqual("overview", response["answer_type"])
        self.assertAlmostEqual(0.1, response["result"]["value"])

    def test_dabstep_upload_keeps_extra_common_document_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _write_dabstep_context_package(root)
            docx_path = root / "额外说明.docx"
            _write_simple_docx(docx_path, "额外 Word 说明：ACI 表示交易授权响应代码。")
            file_paths.append(docx_path)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="额外说明.docx 是什么",
                execution_mode="dual",
            )

        serialized = json.dumps(response, ensure_ascii=False)
        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertEqual(7, upload["uploaded_file_count"])
        self.assertIn("额外说明.docx", [file["file_name"] for file in upload["uploaded_files"]])
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("dataset_source_overview", response["debug"]["operation"])
        self.assertIn("额外说明.docx", serialized)
        self.assertIn("ACI 表示交易授权响应代码", serialized)

    def test_generic_dataset_source_files_are_bound_and_answerable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sales_path = root / "tmp_upload_sales.csv"
            manual_path = root / "字段说明.md"
            rule_path = root / "业务口径.txt"
            metadata_path = root / "fee_rules.json"
            docx_path = root / "分析说明.docx"
            sales_path.write_text(
                "订单ID,月份,城市,销售额\n"
                "O1,2026-01,上海,100\n"
                "O2,2026-02,北京,200\n",
                encoding="utf-8",
            )
            manual_path.write_text("# 字段说明\n\n销售额表示订单成交金额，城市表示客户所在城市。", encoding="utf-8")
            rule_path.write_text("业务口径：销售额按订单金额汇总；月份按订单发生月份统计。", encoding="utf-8")
            metadata_path.write_text(json.dumps({"rules": [{"metric": "销售额", "definition": "订单成交金额"}]}, ensure_ascii=False), encoding="utf-8")
            _write_simple_docx(docx_path, "Word 说明：这份文件解释销售数据的分析背景。")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [sales_path, manual_path, rule_path, metadata_path, docx_path],
                original_filenames=["sales.csv", "字段说明.md", "业务口径.txt", "fee_rules.json", "分析说明.docx"],
            )
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这些说明文件是干什么用的？",
                execution_mode="dual",
            )

        serialized = json.dumps(response, ensure_ascii=False)
        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertEqual(5, upload["uploaded_file_count"])
        self.assertEqual(
            ["sales.csv", "字段说明.md", "业务口径.txt", "fee_rules.json", "分析说明.docx"],
            [file["file_name"] for file in upload["uploaded_files"]],
        )
        self.assertIn("auto_bound_rule_files", upload)
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("overview", response["answer_type"])
        self.assertEqual("dataset_source_overview", response["debug"]["operation"])
        self.assertNotEqual("Not Applicable", response["answer"])
        self.assertIn("sales.csv", serialized)
        self.assertNotIn("tmp_upload_sales.csv", serialized)
        self.assertIn("字段说明.md", serialized)
        self.assertIn("业务口径.txt", serialized)
        self.assertIn("fee_rules.json", serialized)
        self.assertIn("分析说明.docx", serialized)
        self.assertIn("销售额表示订单成交金额", serialized)
        self.assertIn("JSON 对象", serialized)
        self.assertIn("Word 说明", serialized)

    def test_standalone_markdown_upload_is_answerable_source_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            note_path = root / "说明.md"
            note_path.write_text("# 业务说明\n\n销售额表示订单成交金额，城市表示客户所在城市。", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(note_path, original_filename="说明.md")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这个文件是什么",
                execution_mode="dual",
            )
            reloaded_service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            restored_response = reloaded_service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这个文件里面有什么",
                execution_mode="dual",
            )

        serialized = json.dumps(response, ensure_ascii=False)
        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertEqual(1, upload["uploaded_file_count"])
        self.assertEqual("说明.md", upload["uploaded_files"][0]["file_name"])
        self.assertEqual("uploaded_sources", upload["dataset_kind"])
        self.assertEqual(1, upload["source_file_count"])
        self.assertEqual([], upload["tables"])
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("overview", response["answer_type"])
        self.assertEqual("dataset_source_overview", response["debug"]["operation"])
        self.assertIn("说明.md", serialized)
        self.assertIn("销售额表示订单成交金额", serialized)
        self.assertTrue(restored_response["success"], restored_response.get("errors"))
        self.assertEqual("dataset_source_overview", restored_response["debug"]["operation"])
        self.assertIn("说明.md", json.dumps(restored_response, ensure_ascii=False))

    def test_standalone_common_document_uploads_are_answerable_source_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx_path = root / "分析说明.docx"
            rtf_path = root / "业务口径.rtf"
            pages_path = root / "Pages说明.pages"
            legacy_doc_path = root / "旧版Word说明.doc"
            _write_simple_docx(docx_path, "Word 说明：销售额表示订单成交金额。")
            rtf_path.write_text(r"{\rtf1\ansi RTF 说明：城市表示客户所在城市。}", encoding="utf-8")
            _write_simple_pages(pages_path, "Pages 说明：月份表示订单发生月份。")
            legacy_doc_path.write_bytes(b"\xd0\xcf\x11\xe0" + "旧版 Word 说明：商品表示销售对象。".encode("utf-8"))
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [docx_path, rtf_path, pages_path, legacy_doc_path],
                original_filenames=["分析说明.docx", "业务口径.rtf", "Pages说明.pages", "旧版Word说明.doc"],
            )
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="这些文件是什么",
                execution_mode="dual",
            )

        serialized = json.dumps(response, ensure_ascii=False)
        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertEqual(4, upload["uploaded_file_count"])
        self.assertEqual(
            ["分析说明.docx", "业务口径.rtf", "Pages说明.pages", "旧版Word说明.doc"],
            [file["file_name"] for file in upload["uploaded_files"]],
        )
        self.assertEqual("uploaded_sources", upload["dataset_kind"])
        self.assertEqual(4, upload["source_file_count"])
        self.assertEqual([], upload["tables"])
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("dataset_source_overview", response["debug"]["operation"])
        self.assertIn("分析说明.docx", serialized)
        self.assertIn("业务口径.rtf", serialized)
        self.assertIn("Pages说明.pages", serialized)
        self.assertIn("旧版Word说明.doc", serialized)
        self.assertIn("销售额表示订单成交金额", serialized)
        self.assertIn("城市表示客户所在城市", serialized)
        self.assertIn("月份表示订单发生月份", serialized)
        self.assertIn("商品表示销售对象", serialized)

    def test_broad_not_applicable_is_rescued_to_overview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "订单ID,月份,城市,销售额\n"
                "O1,2026-01,上海,100\n"
                "O2,2026-02,北京,200\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            tables = service.file_store.get_tables(upload["dataset_id"]) or {}
            profile = service.file_store.get_profile(upload["dataset_id"])
            rescued = service._rescue_unexpected_not_applicable(
                {
                    "success": True,
                    "run_id": "run_bad",
                    "dataset_id": upload["dataset_id"],
                    "question": "这里面都装了啥",
                    "answer_type": "text",
                    "answer": "Not Applicable",
                    "result": {"columns": ["answer"], "rows": [{"answer": "Not Applicable"}], "value": "Not Applicable"},
                    "debug": {"operation": "not_applicable"},
                },
                question="这里面都装了啥",
                tables=tables,
                profile=profile,
                source_manifest=service.file_store.get_dataset_sources(upload["dataset_id"]),
                agent_mode="multi_agent",
            )

        self.assertEqual("overview", rescued["answer_type"])
        self.assertEqual("dataset_overview", rescued["debug"]["message_intent"])
        self.assertTrue(rescued["debug"]["not_applicable_rescue"]["applied"])
        self.assertNotEqual("Not Applicable", rescued["answer"])

    def test_stored_broad_not_applicable_history_is_repaired_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _write_dabstep_context_package(root)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            bad_payload = {
                "success": True,
                "run_id": "run_bad_history",
                "dataset_id": upload["dataset_id"],
                "question": "还有几个文件是干什么用的",
                "answer_type": "table",
                "answer": "Not Applicable",
                "result": {"columns": ["answer"], "rows": [{"answer": "Not Applicable"}], "value": "Not Applicable"},
                "debug": {"operation": "detail_lookup", "agent_mode": "multi_agent"},
            }
            record = service.conversation_store.append_turn(
                question="还有几个文件是干什么用的",
                response=bad_payload,
                dataset_id=upload["dataset_id"],
            )
            unsupported = service.conversation_store.append_turn(
                question="请计算不存在字段的利润率",
                response={**bad_payload, "run_id": "run_real_unsupported", "question": "请计算不存在字段的利润率"},
                dataset_id=upload["dataset_id"],
            )

            repaired = service.get_conversation(record["conversation_id"])
            still_unsupported = service.get_conversation(unsupported["conversation_id"])
            persisted = service.conversation_store.get_conversation(record["conversation_id"])
            stale = service.conversation_store.get_conversation(record["conversation_id"])
            stale["messages"][1]["payload"]["answer"] = "刚才 N/A 的问题还在旧历史文本里。"
            stale["messages"][1]["content"] = "刚才 N/A 的问题还在旧历史文本里。"
            service.conversation_store.save_conversation(stale)
            repaired_stale = service.get_conversation(record["conversation_id"])

        assistant = repaired["conversation"]["messages"][1]
        serialized = json.dumps(assistant, ensure_ascii=False)
        self.assertEqual("overview", assistant["answer_type"])
        self.assertNotIn('"answer": "Not Applicable"', serialized)
        self.assertNotIn("N/A", assistant["content"])
        self.assertIn("manual.md", serialized)
        self.assertIn("fees.json", serialized)
        self.assertTrue(assistant["payload"]["debug"]["stored_not_applicable_repair"]["applied"])
        self.assertEqual("dataset_source_overview", assistant["payload"]["debug"]["stored_not_applicable_repair"]["route"])
        self.assertEqual("overview", persisted["messages"][1]["answer_type"])
        self.assertNotIn("N/A", repaired_stale["conversation"]["messages"][1]["content"])
        self.assertEqual("Not Applicable", still_unsupported["conversation"]["messages"][1]["payload"]["answer"])

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

    def test_mixed_dataset_and_fee_rule_files_do_not_trigger_partial_dab_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payments_path = root / "payments.csv"
            fees_path = root / "fees.json"
            merchant_data_path = root / "merchant_data.json"
            manual_path = root / "manual.md"
            payments_path.write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,"
                "has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "Rafa_AI,2023,335,11,15,18.55,true,false,false,D,GlobalCard,GR,NL\n",
                encoding="utf-8",
            )
            fees_path.write_text(
                json.dumps(
                    [
                        {
                            "ID": 10,
                            "card_scheme": "GlobalCard",
                            "account_type": ["H"],
                            "capture_delay": None,
                            "monthly_fraud_level": None,
                            "monthly_volume": None,
                            "merchant_category_code": [],
                            "is_credit": None,
                            "aci": ["D"],
                            "fixed_amount": 0.10,
                            "rate": 0,
                            "intracountry": None,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            merchant_data_path.write_text(
                json.dumps([{"merchant": "Rafa_AI", "account_type": "H", "capture_delay": "manual", "merchant_category_code": 5411}]),
                encoding="utf-8",
            )
            manual_path.write_text("Fee rules for demo validation.", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [payments_path, fees_path, merchant_data_path, manual_path],
                original_filenames=["payments.csv", "fees.json", "merchant_data.json", "manual.md"],
            )
            response = service.respond_to_message(
                dataset_id=str(upload.get("dataset_id") or ""),
                question="What were the applicable Fee IDs for Rafa_AI in December 2023?",
                execution_mode="pandas",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertEqual("uploaded_tables", upload["dataset_kind"])
        self.assertEqual(3, len(upload["auto_bound_user_rule_file_ids"]))
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual([10], response["result"]["value"])

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
            loaded = service.get_conversation(response["conversation_id"])

        self.assertTrue(response["success"])
        self.assertEqual("overview", response["answer_type"])
        self.assertIn("3 行、6 列", response["answer"])
        self.assertIn("订阅收入", response["answer"])
        self.assertIn("overview_report", response)
        self.assertEqual("overview_report", response["overview_report"]["report_type"])
        self.assertNotEqual("3", response["answer"])
        self.assertEqual(["指标", "数值"], response["result"]["columns"])
        self.assertTrue(response["insight"]["business_suggestions"])
        self.assertLessEqual(len(response["insight"]["business_suggestions"]), 1)
        self.assertIn("依据", response["insight"]["business_suggestions"][0])
        self.assertTrue(response["execution_artifacts"])
        self.assertIn("python", {item["language"] for item in response["execution_artifacts"]})
        self.assertIn("sql", {item["language"] for item in response["execution_artifacts"]})
        self.assertTrue(response["debug"]["user_experience_shaping"]["applied"])
        self.assertEqual("dataset_overview", response["debug"]["message_intent"])
        self.assertEqual("dataset_overview", response["process_view_v2"]["mode"])
        self.assertTrue(response["process_view_v2"]["steps"])
        self.assertEqual("SaaS销售.csv", response["source_references"][0]["file_name"])
        self.assertEqual(response["source_references"], loaded["conversation"]["messages"][1]["payload"]["source_references"])

    def test_fast_dataset_overview_invokes_llm_presentation_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "订单ID,客户ID,月份,销售额\n"
                "O1,C1,2026-01,100\n"
                "O2,C2,2026-01,200\n",
                encoding="utf-8",
            )
            llm_client = PresentationLLMClient()
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=llm_client,
            )

            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="看一下这个数据",
                execution_mode="dual",
            )

        self.assertTrue(response["success"])
        self.assertIn("fast_path_presentation", llm_client.stage_names)
        self.assertGreater(llm_client.temperatures[-1], 0)
        self.assertTrue(response["debug"]["llm_presentation"]["used"])
        self.assertIn("不是单纯行列表", response["answer"])
        self.assertTrue(response["debug"]["llm_presentation"]["updated_answer"])
        self.assertEqual(["指标", "数值"], response["result"]["columns"])
        self.assertEqual("AI 已复核这组表，关键是先确定主事实表和关联边界。", response["insight"]["summary"])
        self.assertEqual(["哪张表适合作为主事实表？", "这些表能按哪些字段关联？"], response["insight"]["next_questions"])
        self.assertIn("下一步先确认订单明细表", response["insight"]["business_suggestions"][0])
        self.assertIn("LLM 表达整理", json.dumps(response["process_view_v2"], ensure_ascii=False))
        self.assertIn("updated_answer=True", json.dumps(response["process_view_v2"], ensure_ascii=False))
        self.assertIn("调用LLM整理表达", response["process_view_v2"]["summary"])

    def test_fast_presentation_rejects_english_insight_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "payments.csv"
            csv_path.write_text(
                "ip_country,eur_amount\n"
                "NL,100\n"
                "IT,90\n"
                "BE,80\n",
                encoding="utf-8",
            )
            llm_client = EnglishInsightPresentationLLMClient()
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=llm_client,
            )

            upload = service.upload_dataset(csv_path, original_filename="payments.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="看一下这个数据",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertIn("fast_path_presentation", llm_client.stage_names)
        presentation_debug = response["debug"]["llm_presentation"]
        self.assertTrue(presentation_debug["updated_answer"])
        self.assertEqual("display_answer", presentation_debug["answer_update_source"])
        self.assertIn("summary", presentation_debug["rejected_language_fields"])
        self.assertIn("next_step", presentation_debug["rejected_language_fields"])
        self.assertIn("next_questions", presentation_debug["rejected_language_fields"])
        insight_payload = json.dumps(response["insight"], ensure_ascii=False)
        self.assertNotIn("The top 10 ranking", insight_payload)
        self.assertNotIn("not a full top 10", insight_payload)
        self.assertNotIn("Compare the top countries", insight_payload)

    def test_fast_dataset_overview_prefaces_answer_when_llm_only_returns_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "订单ID,客户ID,月份,销售额\n"
                "O1,C1,2026-01,100\n"
                "O2,C2,2026-01,200\n",
                encoding="utf-8",
            )
            llm_client = SummaryOnlyPresentationLLMClient()
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=llm_client,
            )

            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="看一下这个数据",
                execution_mode="dual",
        )

        self.assertTrue(response["success"])
        self.assertIn("核心结论是", response["answer"])
        self.assertIn("AI 已把这次概览收敛", response["answer"])
        self.assertIn("已读取这个数据", response["answer"])
        self.assertIn("口径说明：", response["answer"])
        self.assertTrue(response["debug"]["llm_presentation"]["updated_answer"])
        self.assertEqual("summary_preface", response["debug"]["llm_presentation"]["answer_update_source"])
        self.assertIn("answer_update_source=summary_preface", json.dumps(response["process_view_v2"], ensure_ascii=False))

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
            self.assertEqual(["orders.csv", "customers.csv"], [item["file_name"] for item in response["source_references"]])
            self.assertEqual(["表名", "行数", "类型", "主要作用", "关键字段"], response["result"]["columns"])
            payload = json.dumps(response, ensure_ascii=False)
            self.assertIn("orders", response["answer"])
            self.assertIn("customers", response["answer"])
            self.assertLess(len(response["answer"]), 1200)
            self.assertNotIn("1. 多表含义", response["answer"])
            self.assertNotIn("WHITE HANGING HEART T-LIGHT HOLDER,6,2.55", payload)
            self.assertNotIn("WHITE METAL LANTERN,6,3.39", payload)
        self.assertIn("关键字段", field_response["answer"])
        self.assertIn("建议分析方向", story_response["answer"])
        self.assertNotEqual(field_response["answer"], story_response["answer"])

    def test_multi_table_overview_classifies_metadata_workbooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "订单明细.csv"
            glossary_path = root / "数据表结构&表说明.xlsx"
            knowledge_path = root / "初版知识库.xlsx"
            orders_path.write_text(
                "order_id,customer_id,sales\n"
                "O1,C1,100\n"
                "O2,C2,120\n",
                encoding="utf-8",
            )
            pd.DataFrame(
                {
                    "表名": ["订单明细"],
                    "字段名": ["sales"],
                    "字段含义": ["销售额，按订单金额汇总"],
                }
            ).to_excel(glossary_path, index=False)
            pd.DataFrame(
                {
                    "主题": ["销售额口径"],
                    "说明": ["销售额按签收订单金额汇总，城市来自客户维表"],
                }
            ).to_excel(knowledge_path, index=False)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())

            upload = service.upload_datasets(
                [orders_path, glossary_path, knowledge_path],
                original_filenames=["订单明细.csv", "数据表结构&表说明.xlsx", "初版知识库.xlsx"],
            )
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="看一下这几个文件")
            source_response = service.respond_to_message(dataset_id=upload["dataset_id"], question="这些文件分别是什么用途？")

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("multi_table_dataset_overview", response["debug"]["operation"])
        rows_by_name = {row["表名"]: row for row in response["result"]["rows"]}
        self.assertEqual("可计算事实表", rows_by_name["订单明细"]["类型"])
        self.assertEqual("说明或元数据表", rows_by_name["数据表结构&表说明"]["类型"])
        self.assertEqual("说明或元数据表", rows_by_name["初版知识库"]["类型"])
        self.assertIn("说明或元数据表", response["answer"])
        self.assertTrue(source_response["success"], source_response.get("errors"))
        self.assertEqual("dataset_source_overview", source_response["debug"]["operation"])
        source_payload = json.dumps(source_response, ensure_ascii=False)
        self.assertIn("说明或元数据表", source_payload)
        self.assertIn("说明或元数据表", source_response["answer"])
        self.assertNotIn("初版知识库.xlsx（表格数据", source_response["answer"])
        self.assertNotIn("数据表结构&表说明.xlsx（表格数据", source_response["answer"])
        self.assertNotIn("0 个说明/规则来源", source_response["answer"])

    def test_multi_table_browse_questions_are_distinct_overview_not_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "orders.csv"
            customers_path = root / "customers.csv"
            orders_path.write_text(
                "InvoiceNo,StockCode,Description,Quantity,UnitPrice,CustomerID,Country\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2.55,17850,United Kingdom\n"
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
            generic = service.respond_to_message(dataset_id=upload["dataset_id"], question="看一下这几张表")
            story = service.respond_to_message(dataset_id=upload["dataset_id"], question="这几张表讲的什么")
            difference = service.respond_to_message(dataset_id=upload["dataset_id"], question="这些文件有什么区别？")
            content = service.respond_to_message(dataset_id=upload["dataset_id"], question="这些表有什么内容？")

        for response in (generic, story, difference, content):
            self.assertTrue(response["success"], response.get("errors"))
            self.assertEqual("overview", response["answer_type"])
            self.assertEqual("multi_table_dataset_overview", response["debug"]["operation"])
            self.assertNotEqual("Not Applicable", response["answer"])
            self.assertIn("orders", response["answer"])
            self.assertIn("customers", response["answer"])
            self.assertTrue(response["execution_artifacts"])
            self.assertIn("import pandas as pd", response["execution_artifacts"][0]["code"])
            process = response["process_view_v2"]
            self.assertEqual("dataset_overview", process["mode"])
            self.assertGreaterEqual(len(process["steps"]), 6)
            self.assertTrue(any("Python / Pandas" in step["title"] for step in process["steps"]))

        self.assertIn("已读取这组数据", generic["answer"])
        self.assertIn("主要是在描述", story["answer"])
        self.assertIn("区别主要在", difference["answer"])
        self.assertIn("orders", content["answer"])
        self.assertEqual(4, len({generic["answer"], story["answer"], difference["answer"], content["answer"]}))

    def test_multi_file_shape_question_returns_gpt_like_counts_not_value_dump(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jan_path = root / "jan.csv"
            feb_path = root / "feb.csv"
            jan_path.write_text("月份,客户,金额\n2026-01,A,100\n2026-01,B,200\n", encoding="utf-8")
            feb_path.write_text("月份,客户,金额,区域\n2026-02,A,150,华东\n", encoding="utf-8")
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_datasets(
                [jan_path, feb_path],
                original_filenames=["jan.csv", "feb.csv"],
            )
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="每个文件分别有多少行、多少列？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("overview", response["answer_type"])
        self.assertEqual("multi_table_dataset_overview", response["debug"]["operation"])
        self.assertIn("jan", response["answer"])
        self.assertIn("2 行、3 列", response["answer"])
        self.assertIn("feb", response["answer"])
        self.assertIn("1 行、4 列", response["answer"])
        self.assertIn("没有展示原始明细行", response["answer"])
        self.assertNotIn("2026-01-01 00:00:00, 89", response["answer"])
        self.assertLess(len(response["answer"]), 800)

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
            anomaly_policy = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="给我异常规则、数量、占比和样例说明。",
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
        self.assertLess(len(policy["answer"]), 1000)
        self.assertEqual(["表名", "规则", "影响行数", "影响比例", "建议"], policy["result"]["columns"])
        self.assertNotIn("WHITE HANGING HEART T-LIGHT HOLDER,6,2.55", json.dumps(policy, ensure_ascii=False))
        self.assertTrue(policy["debug"]["user_experience_shaping"]["applied"])
        self.assertTrue(anomaly_policy["success"])
        self.assertEqual("cleaning_simulation", anomaly_policy["answer_type"])
        self.assertIn("异常规则", anomaly_policy["answer"])
        self.assertNotEqual("0", str(anomaly_policy["answer"]).strip())
        self.assertTrue(boundary["success"])
        self.assertEqual("chat", boundary["answer_type"])
        self.assertIn("不会直接修改原始数据", boundary["answer"])
        self.assertIn("必须等用户明确确认", boundary["answer"])

    def test_schema_quality_and_cleaning_questions_are_not_template_collapsed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "retail.csv"
            csv_path.write_text(
                "InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2026-01-01,2.55,17850,United Kingdom\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2026-01-01,2.55,17850,United Kingdom\n"
                "536366,22633,HAND WARMER UNION JACK,-1,bad-date,1.85,,United Kingdom\n"
                "536367,22632,HAND WARMER RED POLKA DOT,10000,2026-01-03,0,13047,United Kingdom\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="retail.csv")
            schema = service.respond_to_message(dataset_id=upload["dataset_id"], question="字段是否一致？有没有新增、缺失、类型变化？")
            quality = service.respond_to_message(dataset_id=upload["dataset_id"], question="有没有明显的数据质量问题？")
            numeric = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪些数值字段存在负值、0 值或极端值？")
            temporal = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪些日期字段范围异常或无法解析？")
            roles = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪些字段适合做指标、维度、时间和 ID？")

        self.assertEqual("overview", schema["answer_type"])
        self.assertIn("主要是一张表", schema["answer"])
        self.assertEqual("cleaning_simulation", quality["answer_type"])
        self.assertIn("不能简单说数据完全正常", quality["answer"])
        self.assertIn("CustomerID 缺失", quality["answer"])
        self.assertIn("负值", numeric["answer"])
        self.assertIn("0 值", numeric["answer"])
        self.assertIn("InvoiceDate 范围", temporal["answer"])
        self.assertIn("无法解析", temporal["answer"])
        self.assertEqual("overview", roles["answer_type"])
        self.assertIn("指标=", roles["answer"])
        self.assertIn("ID=", roles["answer"])
        self.assertEqual(5, len({schema["answer"], quality["answer"], numeric["answer"], temporal["answer"], roles["answer"]}))

    def test_quality_and_cleaning_questions_keep_question_specific_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "retail.csv"
            csv_path.write_text(
                "InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2026-01-01,2.55,17850,United Kingdom\n"
                "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2026-01-01,2.55,17850,United Kingdom\n"
                "536366,22633,HAND WARMER UNION JACK,-1,bad-date,1.85,,United Kingdom\n"
                "536367,22632,HAND WARMER RED POLKA DOT,10000,2026-01-03,0,13047,United Kingdom\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path, original_filename="retail.csv")
            questions = [
                "这个数据正常吗？",
                "有没有明显的数据质量问题？",
                "给我异常规则、数量、占比和样例说明。",
                "如果先处理明显异常，结论会不会变？",
                "如果删除明显异常行，核心指标会受什么影响？",
                "给出建议清洗规则、影响行数、影响比例，并说明是否需要用户确认。",
            ]
            responses = [
                service.respond_to_message(dataset_id=upload["dataset_id"], question=question)
                for question in questions
            ]

        answers = [str(response["answer"]) for response in responses]
        self.assertEqual(len(questions), len(set(answers)))
        self.assertIn("不能简单说", answers[0])
        self.assertIn("完全正常", answers[0])
        self.assertIn("数据质量问题", answers[1])
        self.assertIn("规则", answers[2])
        self.assertIn("清洗前后", answers[3])
        self.assertIn("核心指标", answers[4])
        self.assertIn("建议清洗规则", answers[5])

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
        self.assertIn("InvoiceDate", guarded["answer"])
        self.assertIn("完整字段画像", guarded["answer"])
        self.assertLess(len(guarded["answer"]), 1200)
        self.assertNotIn("WHITE HANGING HEART T-LIGHT HOLDER,6,2.55", serialized)

    def test_raw_detail_exit_guard_replaces_compact_date_value_sequence(self) -> None:
        raw_answer = (
            "2025-01-01 00:00:00, 89, 2025-02-01 00:00:00, 95, "
            "2025-03-01 00:00:00, 101, 2025-04-01 00:00:00, 88"
        )
        payload = {
            "response_version": "v1",
            "success": True,
            "run_id": "run_compact_dump",
            "dataset_id": "dataset_compact_dump",
            "question": "每个文件分别有多少行、多少列？",
            "answer_type": "analysis",
            "execution_mode": "dual",
            "answer": raw_answer,
            "result": {"columns": [], "rows": [], "value": None},
            "debug": {"agent_mode": "multi_agent"},
        }
        tables = {
            "monthly_sales": pd.DataFrame(
                [
                    {"月份": "2025-01", "客户": "A", "金额": 89},
                    {"月份": "2025-02", "客户": "B", "金额": 95},
                ]
            )
        }

        guarded = _suppress_raw_detail_answer(
            payload,
            question="每个文件分别有多少行、多少列？",
            tables=tables,
            profile=None,
            agent_mode="multi_agent",
        )

        self.assertEqual("overview", guarded["answer_type"])
        self.assertIn("2 行、3 列", guarded["answer"])
        self.assertNotIn("2025-01-01 00:00:00, 89", guarded["answer"])

    def test_broad_dataset_readiness_questions_do_not_return_row_count_only(self) -> None:
        questions = [
            "这个数据适合做哪些分析？",
            "这个数据正常吗？",
            "这个数据能不能用？",
            "这个数据能不能做趋势、环比或同比？",
            "帮我看看哪里有问题。",
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
            self.assertLess(len(str(response["answer"])), 1200)
            self.assertNotIn("1. 表整体情况", str(response["answer"]))
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
            capability = service.respond_to_message(dataset_id=upload["dataset_id"], question="我能干什么")

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
        self.assertTrue(capability["success"])
        self.assertEqual("chat", capability["answer_type"])
        self.assertEqual("chat_with_dataset", capability["debug"]["agent_mode"])
        self.assertEqual("chat", capability["process_view_v2"]["mode"])
        self.assertIn("当前数据已经上传", capability["answer"])
        self.assertNotIn("Not Applicable", json.dumps(capability, ensure_ascii=False))
        self.assertEqual([], capability["result"]["rows"])

    def test_meta_chat_uses_direct_llm_before_data_analysis_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text("city,sales\nShanghai,100\nBeijing,150\n", encoding="utf-8")
            llm_client = DirectChatLLMClient()
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=llm_client,
            )

            upload = service.upload_dataset(csv_path)
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="我能干什么")

        self.assertTrue(response["success"])
        self.assertEqual("chat", response["answer_type"])
        self.assertEqual("chat", response["process_view_v2"]["mode"])
        self.assertEqual([], response["result"]["rows"])
        self.assertIn("直连 LLM", response["answer"])
        self.assertIn("direct_chat", llm_client.stage_names)
        self.assertGreater(llm_client.temperatures[-1], 0)
        self.assertTrue(response["debug"]["direct_llm_chat"]["used"])
        self.assertTrue(response["debug"]["direct_llm_chat"]["updated_answer"])
        self.assertIn("LLM 直接对话", json.dumps(response["process_view_v2"], ensure_ascii=False))
        self.assertNotIn("Not Applicable", json.dumps(response, ensure_ascii=False))

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
        self.assertIn("started_at", first)
        self.assertIn("responded_at", first)
        self.assertIsInstance(first["thinking_elapsed_ms"], int)
        self.assertTrue(conversation_id.startswith("conv_"))
        self.assertEqual(conversation_id, second["conversation_id"])
        self.assertEqual("VDS 助手介绍", renamed["conversation"]["title"])
        self.assertEqual(conversation_id, listed["conversations"][0]["conversation_id"])
        self.assertEqual("VDS 助手介绍", listed["conversations"][0]["title"])
        self.assertEqual("chat", listed["conversations"][0]["last_answer_type"])
        self.assertEqual(4, len(loaded["conversation"]["messages"]))
        self.assertEqual("user", loaded["conversation"]["messages"][0]["role"])
        self.assertTrue(loaded["conversation"]["messages"][0]["created_at"])
        self.assertEqual("assistant", loaded["conversation"]["messages"][1]["role"])
        self.assertEqual("chat", loaded["conversation"]["messages"][1]["payload"]["answer_type"])
        self.assertIn("thinking_elapsed_ms", loaded["conversation"]["messages"][1]["payload"])
        self.assertEqual("VDS 助手介绍", loaded_after_restart["conversation"]["title"])

    def test_list_conversations_supports_offset_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            first = service.respond_to_message(question="第一条")
            second = service.respond_to_message(question="第二条")
            third = service.respond_to_message(question="第三条")

            listed = service.list_conversations(limit=2, offset=1)

        self.assertTrue(listed["success"])
        self.assertEqual(
            [second["conversation_id"], first["conversation_id"]],
            [item["conversation_id"] for item in listed["conversations"]],
        )
        self.assertNotIn(third["conversation_id"], [item["conversation_id"] for item in listed["conversations"]])
        self.assertEqual(3, listed["total"])
        self.assertEqual(2, listed["limit"])
        self.assertEqual(1, listed["offset"])
        self.assertEqual(2, listed["count"])
        self.assertFalse(listed["has_more"])

    def test_conversation_pin_persists_and_sorts_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            first = service.respond_to_message(question="第一条")
            second = service.respond_to_message(question="第二条")
            pinned = service.update_conversation(first["conversation_id"], pinned=True)
            listed = service.list_conversations()
            reloaded_service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )
            loaded_after_restart = reloaded_service.get_conversation(first["conversation_id"])
            unpinned = reloaded_service.update_conversation(first["conversation_id"], pinned=False)

        self.assertTrue(pinned["conversation"]["pinned"])
        self.assertTrue(pinned["conversation"]["pinned_at"])
        self.assertEqual(first["conversation_id"], listed["conversations"][0]["conversation_id"])
        self.assertTrue(listed["conversations"][0]["pinned"])
        self.assertEqual(second["conversation_id"], listed["conversations"][1]["conversation_id"])
        self.assertTrue(loaded_after_restart["conversation"]["pinned"])
        self.assertFalse(unpinned["conversation"]["pinned"])
        self.assertEqual("", unpinned["conversation"]["pinned_at"])

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
            listed_global_after_move = service.list_conversations()
            listed_project = service.list_conversations(project_id=project_id)
            loaded_project = service.get_project(project_id)
            deleted = service.delete_conversation(conversation_id)
            listed_after_delete = service.list_conversations(project_id=project_id)
            project_after_delete = service.get_project(project_id)

        self.assertTrue(moved["success"], moved.get("errors"))
        self.assertEqual(project_id, moved["conversation"]["project_id"])
        self.assertEqual([], listed_global_after_move["conversations"])
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

    def test_list_projects_returns_stable_pagination_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            service = DataAgentService(
                file_store=TempFileStore(storage_root),
                llm_client=MockLLMClient(),
            )

            first = service.create_project(name="项目一")
            second = service.create_project(name="项目二")
            third = service.create_project(name="项目三")
            listed = service.list_projects(limit=2, offset=1)

        self.assertTrue(listed["success"])
        self.assertEqual(3, listed["total"])
        self.assertEqual(2, listed["limit"])
        self.assertEqual(1, listed["offset"])
        self.assertEqual(2, listed["count"])
        self.assertFalse(listed["has_more"])
        self.assertEqual(
            [second["project"]["project_id"], first["project"]["project_id"]],
            [item["project_id"] for item in listed["projects"]],
        )
        self.assertNotIn(third["project"]["project_id"], [item["project_id"] for item in listed["projects"]])

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

    def test_project_memory_formula_affects_dataset_calculation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "city,sales,discount\n"
                "北京,1000,900\n"
                "上海,900,100\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            project_id = service.create_project(name="项目口径")["project"]["project_id"]
            upload = service.upload_project_sources(project_id, [csv_path], original_filenames=["sales.csv"])
            service.create_project_memory(project_id, title="净销售额口径", content="项目净销售额 = sales - discount")
            response = service.respond_to_message(
                project_id=project_id,
                question="哪个城市项目净销售额最高？",
                execution_mode="pandas",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("上海", response["result"]["rows"][0]["city"])
        self.assertEqual(800, response["result"]["rows"][0]["项目净销售额"])
        self.assertIn("项目净销售额", response["debug"]["project_derived_metrics_applied"])
        self.assertEqual(1, response["debug"]["project_context"]["derived_metric_count"])

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

    def test_card_scheme_steering_monthly_scope_question_2644_passes_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            files = _write_card_scheme_steering_context_package(root)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_dataset(files["payments"], original_filename="payments.csv")
            dataset_id = upload["dataset_id"]
            for path in (files["fees"], files["merchant_data"]):
                rule = service.upload_dataset(
                    path,
                    original_filename=path.name,
                    file_role="rule",
                    rule_scope="user_analysis",
                    bind_dataset_id=dataset_id,
                )
                self.assertTrue(rule["success"], rule.get("errors"))
            response = service.respond_to_message(
                dataset_id=dataset_id,
                question="Looking at the month of July, to which card scheme should the merchant Martinis_Fine_Steakhouse steer traffic in order to pay the minimum fees?",
                execution_mode="pandas",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertTrue(response["success"], response.get("errors"))
        self.assertTrue(response["verification"]["passed"], response["verification"])
        self.assertEqual("card_scheme_steering", response["logic_form"]["operation"])
        self.assertNotEqual("clarification", response["answer_type"])
        self.assertEqual("Martinis_Fine_Steakhouse", response["logic_form"]["filters"]["merchant"])
        self.assertEqual(7, response["logic_form"]["filters"]["month"])
        self.assertIn(
            "Card scheme steering uses month/year language as filter scope, not as a grouped output dimension.",
            response["verification"]["semantic_verification_notes"],
        )

    def test_card_scheme_steering_monthly_scope_with_explicit_year_passes_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            files = _write_card_scheme_steering_context_package(root)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_dataset(files["payments"], original_filename="payments.csv")
            dataset_id = upload["dataset_id"]
            for path in (files["fees"], files["merchant_data"]):
                rule = service.upload_dataset(
                    path,
                    original_filename=path.name,
                    file_role="rule",
                    rule_scope="user_analysis",
                    bind_dataset_id=dataset_id,
                )
                self.assertTrue(rule["success"], rule.get("errors"))
            response = service.respond_to_message(
                dataset_id=dataset_id,
                question="Which card scheme should Martinis_Fine_Steakhouse steer to in July 2023 to pay the lowest fees?",
                execution_mode="pandas",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertTrue(response["success"], response.get("errors"))
        self.assertTrue(response["verification"]["passed"], response["verification"])
        self.assertEqual("card_scheme_steering", response["logic_form"]["operation"])
        self.assertNotEqual("clarification", response["answer_type"])
        self.assertEqual("Martinis_Fine_Steakhouse", response["logic_form"]["filters"]["merchant"])
        self.assertEqual(2023, response["logic_form"]["filters"]["year"])
        self.assertEqual(7, response["logic_form"]["filters"]["month"])

    def test_card_scheme_steering_annual_scope_still_passes_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            files = _write_card_scheme_steering_context_package(root)
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_dataset(files["payments"], original_filename="payments.csv")
            dataset_id = upload["dataset_id"]
            for path in (files["fees"], files["merchant_data"]):
                rule = service.upload_dataset(
                    path,
                    original_filename=path.name,
                    file_role="rule",
                    rule_scope="user_analysis",
                    bind_dataset_id=dataset_id,
                )
                self.assertTrue(rule["success"], rule.get("errors"))
            response = service.respond_to_message(
                dataset_id=dataset_id,
                question="Looking at the year 2023, to which card scheme should the merchant Martinis_Fine_Steakhouse steer traffic to in order to pay the minimum fees?",
                execution_mode="pandas",
            )

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertTrue(response["success"], response.get("errors"))
        self.assertTrue(response["verification"]["passed"], response["verification"])
        self.assertEqual("card_scheme_steering", response["logic_form"]["operation"])
        self.assertNotEqual("clarification", response["answer_type"])
        self.assertEqual("Martinis_Fine_Steakhouse", response["logic_form"]["filters"]["merchant"])
        self.assertEqual(2023, response["logic_form"]["filters"]["year"])

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


def _write_card_scheme_steering_context_package(root: Path) -> dict[str, Path]:
    file_contents = {
        "payments.csv": (
            "merchant,year,month,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,"
            "has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
            "Martinis_Fine_Steakhouse,2023,1,12,0,0,100.0,true,false,false,A,GlobalCard,NL,NL\n"
            "Martinis_Fine_Steakhouse,2023,7,182,0,0,34781.2825,true,false,false,A,GlobalCard,NL,NL\n"
            "Martinis_Fine_Steakhouse,2023,8,213,0,0,2000000.0,true,false,false,A,GlobalCard,NL,NL\n"
        ),
        "merchant_category_codes.csv": "mcc,description\n5411,Grocery Stores\n",
        "fees.json": json.dumps(
            [
                _service_fee_rule(1, "GlobalCard", fixed_amount=500.0, rate=0),
                _service_fee_rule(2, "NexPay", fixed_amount=0.0, rate=100),
                _service_fee_rule(3, "SwiftCharge", fixed_amount=200.0, rate=400),
                _service_fee_rule(4, "TransactPlus", fixed_amount=100.0, rate=700),
            ]
        ),
        "merchant_data.json": json.dumps(
            [{"merchant": "Martinis_Fine_Steakhouse", "account_type": "A", "capture_delay": "manual", "merchant_category_code": 5411}]
        ),
    }
    paths: dict[str, Path] = {}
    for filename, content in file_contents.items():
        path = root / filename
        path.write_text(content, encoding="utf-8")
        stem = filename.split(".", 1)[0]
        paths[stem] = path
    return paths


def _service_fee_rule(fee_id: int, card_scheme: str, *, fixed_amount: float, rate: int) -> dict[str, object]:
    return {
        "ID": fee_id,
        "card_scheme": card_scheme,
        "account_type": [],
        "capture_delay": None,
        "monthly_fraud_level": None,
        "monthly_volume": None,
        "merchant_category_code": [],
        "is_credit": True,
        "aci": ["A"],
        "fixed_amount": fixed_amount,
        "rate": rate,
        "intracountry": None,
    }


def _write_simple_docx(path: Path, text: str) -> None:
    escaped = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{escaped}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "")
        archive.writestr("_rels/.rels", "")
        archive.writestr("word/document.xml", document_xml)


def _write_simple_pages(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("QuickLook/Preview.txt", text)


if __name__ == "__main__":
    unittest.main()
