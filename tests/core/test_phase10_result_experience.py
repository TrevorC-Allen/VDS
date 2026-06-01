"""Phase 10 tests for visualization, insight, quality, and trace UX."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.core.data_quality import build_data_quality_report
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.output.activity_trace import build_activity_trace_v2
from data_agent_core.output.chart_planner import build_chart_spec
from data_agent_core.output.chart_renderer import attach_rendered_chart
from data_agent_core.output.execution_artifacts import build_execution_artifacts
from data_agent_core.output.insight_generator import generate_insight
from data_agent_core.output.process_narrative import build_process_view_v2, process_view_monitor_payload
from data_agent_core.output.reasoning_trace_view import build_reasoning_trace_view
from data_agent_core.output.response_builder import build_response
from data_agent_core.tracing.live_monitor import sanitize_monitor_payload
from data_agent_core.tracing.run_trace import RunTrace


class Phase10ResultExperienceTest(unittest.TestCase):
    def test_chart_planner_selects_bar_line_pie_and_kpi(self) -> None:
        ranking_plan = AnalysisPlan(
            plan_id="plan_rank",
            logic_form=LogicForm(task_type="ranking", operation="ranking"),
        )
        ranking_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["城市", "销售额"],
            rows=[{"城市": "上海", "销售额": 300}, {"城市": "北京", "销售额": 200}],
        )
        self.assertEqual("bar", build_chart_spec(plan=ranking_plan, execution_result=ranking_result, verification_passed=True).chart_type)

        trend_plan = AnalysisPlan(plan_id="plan_trend", logic_form=LogicForm(task_type="trend", operation="trend"))
        trend_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份", "销售额"],
            rows=[{"月份": "2026-01", "销售额": 100}, {"月份": "2026-02", "销售额": 160}],
        )
        self.assertEqual("line", build_chart_spec(plan=trend_plan, execution_result=trend_result, verification_passed=True).chart_type)

        share_plan = AnalysisPlan(plan_id="plan_share", logic_form=LogicForm(task_type="aggregation", operation="boolean_percentage"))
        share_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["渠道", "占比"],
            rows=[{"渠道": "线上", "占比": 60}, {"渠道": "线下", "占比": 40}],
        )
        self.assertEqual("pie", build_chart_spec(plan=share_plan, execution_result=share_result, verification_passed=True).chart_type)

        scalar_result = ExecutionResult(backend="pandas", success=True, value=42, columns=["answer"], rows=[{"answer": 42}])
        self.assertEqual("kpi", build_chart_spec(plan=ranking_plan, execution_result=scalar_result, verification_passed=True).chart_type)

    def test_chart_planner_emits_combo_chart_for_target_actual_with_rate(self) -> None:
        plan = AnalysisPlan(
            plan_id="plan_combo",
            logic_form=LogicForm(
                task_type="trend",
                operation="retail_target_actual_monthly_comparison",
                output_format={"chart_type": "combo_column_line"},
            ),
        )
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份", "实际分销金额", "目标金额", "达成率"],
            rows=[
                {"月份": "2026年1月", "实际分销金额": 50000.0, "目标金额": 70000.0, "达成率": 71.43},
                {"月份": "2026年2月", "实际分销金额": 82000.0, "目标金额": 76000.0, "达成率": 107.89},
            ],
        )

        chart = build_chart_spec(plan=plan, execution_result=result, verification_passed=True)

        self.assertEqual("combo_column_line", chart.chart_type)
        self.assertEqual("月份", chart.x)
        self.assertEqual(["实际分销金额", "目标金额"], chart.encoding["y_left"])
        self.assertEqual(["达成率"], chart.encoding["y_right"])
        self.assertEqual(["bar", "bar", "line"], [series["type"] for series in chart.series])

    def test_chart_planner_respects_explicit_horizontal_bar_request(self) -> None:
        plan = AnalysisPlan(
            plan_id="plan_horizontal",
            logic_form=LogicForm(
                task_type="ranking",
                operation="retail_distribution_topn_chart",
                output_format={"chart_type": "horizontal_bar"},
            ),
        )
        rows = [{"SKU": f"超长SKU-{index}", "分销金额": float(100 - index)} for index in range(10)]
        result = ExecutionResult(backend="pandas", success=True, columns=["SKU", "分销金额"], rows=rows)

        chart = build_chart_spec(plan=plan, execution_result=result, verification_passed=True)

        self.assertEqual("horizontal_bar", chart.chart_type)
        self.assertEqual("explicit_horizontal_ranking", chart.selection_reason)

    def test_chart_planner_prefers_table_for_payment_detail_rows(self) -> None:
        plan = AnalysisPlan(
            plan_id="plan_detail",
            logic_form=LogicForm(task_type="detail_lookup", operation="detail_lookup"),
        )
        rows = [
            {
                "psp_reference": 20034594130 + index,
                "merchant": "Belles_cookbook_store" if index % 2 else "Crossfit_Hanna",
                "card_scheme": "GlobalCard",
                "year": 2023,
                "hour_of_day": index,
                "minute_of_hour": index + 10,
                "day_of_year": 30 + index,
                "eur_amount": 10.0 + index,
                "card_bin": 4556 + index,
                "aci": "F",
            }
            for index in range(8)
        ]
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=list(rows[0]),
            rows=rows,
        )

        chart = build_chart_spec(plan=plan, execution_result=result, verification_passed=True)

        self.assertIsNone(chart.chart_type)
        self.assertEqual("detail_rows_prefer_table", chart.fallback_reason)

    def test_execution_artifacts_are_safe_reproducibility_cards(self) -> None:
        plan = AnalysisPlan(
            plan_id="plan_safe_code",
            logic_form=LogicForm(
                task_type="ranking",
                operation="ranking",
                metric="Sales_TASK_ID_raw_prompt",
                group_by="city",
                source_tables=["orders"],
            ),
        )
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["city", "Sales_TASK_ID_raw_prompt"],
            rows=[{"city": "Shanghai", "Sales_TASK_ID_raw_prompt": 300}],
        )

        artifacts = build_execution_artifacts(plan=plan, execution_result=result, verification_passed=True)
        payload = str(artifacts).lower()

        self.assertTrue(artifacts)
        self.assertIn("python", {item["language"] for item in artifacts})
        self.assertNotIn("task_id", payload)
        self.assertNotIn("raw_prompt", payload)
        self.assertNotIn("chain_of_thought", payload)

    def test_activity_trace_v2_exposes_real_execution_without_raw_cot(self) -> None:
        trace = RunTrace(
            run_id="run_trace",
            dataset_id="dataset_1",
            question="哪个城市销售额最高？",
            logic_form={
                "operation": "ranking",
                "metric": "sales",
                "group_by": "city",
                "source_tables": ["orders"],
                "parameters": {"metric": "sales", "dimension": "city"},
            },
            source_tables=["orders"],
            pandas_result_summary={"success": True, "backend": "pandas", "value": [{"city": "上海", "sales": 300}]},
            sql_result_summary={"skipped": True, "reason": "Current native SQL path does not cover this capability family."},
            verification_result={"passed": True, "pandas_sql_consistent": None, "chain_of_thought": "hidden"},
            tool_call_summary=[
                {
                    "requested_by": "pandas_executor",
                    "tool_name": "execute_pandas_plan",
                    "success": True,
                    "arguments_summary": {"analysis_plan": "ranking", "task_id": "secret"},
                    "result_summary": {"rows": 1},
                }
            ],
            final_response={"answer": "上海", "success": True, "output_contract_passed": True},
        )
        response = {
            "success": True,
            "answer_type": "text",
            "verification": {"passed": True},
            "execution_artifacts": [
                {
                    "language": "python",
                    "title": "Python / Pandas 复现片段",
                    "code": "import pandas as pd\n# task_id raw_prompt",
                    "purpose": "安全复现",
                }
            ],
        }

        activity = build_activity_trace_v2(trace, response)
        payload = str(activity).lower()

        self.assertTrue(any(item["role"] == "pandas_executor" for item in activity))
        self.assertTrue(any(item["role"] == "sql_executor" and "skipped" in " ".join(item["actions"]).lower() for item in activity))
        self.assertTrue(any(item["role"] == "verifier" for item in activity))
        self.assertTrue(any(item.get("artifacts") for item in activity))
        artifact_code = next(node["artifacts"][0]["code"] for node in activity if node.get("artifacts"))
        self.assertIn("\n", artifact_code)
        self.assertIn("[redacted]", artifact_code)
        self.assertIn("execute_pandas_plan", payload)
        self.assertNotIn("chain_of_thought", payload)
        self.assertNotIn("raw_prompt", payload)
        self.assertNotIn("task_id", payload)

    def test_backend_chart_renderer_attaches_svg_image_data_uri(self) -> None:
        chart = build_chart_spec(
            plan=AnalysisPlan(plan_id="plan_rank", logic_form=LogicForm(task_type="ranking", operation="ranking")),
            execution_result=ExecutionResult(
                backend="pandas",
                success=True,
                columns=["城市", "销售额"],
                rows=[{"城市": "上海", "销售额": 300}, {"城市": "北京", "销售额": 200}, {"城市": "深圳", "销售额": 120}],
            ),
            verification_passed=True,
        )

        rendered = attach_rendered_chart(chart)

        self.assertTrue(rendered.image_data_uri.startswith("data:image/svg+xml;base64,"))
        self.assertEqual("svg", rendered.image_format)
        self.assertEqual("python_svg", rendered.render_engine)

    def test_backend_chart_renderer_uses_series_when_llm_y_label_is_not_a_column(self) -> None:
        chart = ChartSpec(
            chart_type="line",
            x="月份",
            y="成功率",
            title="多系列趋势",
            data=[
                {"月份": "2026年1月", "张三": 50.0, "李四": 80.0},
                {"月份": "2026年2月", "张三": 75.0, "李四": 60.0},
            ],
            series=[
                {"type": "line", "x": "月份", "y": "张三"},
                {"type": "line", "x": "月份", "y": "李四"},
            ],
        )

        rendered = attach_rendered_chart(chart)

        self.assertTrue(rendered.image_data_uri.startswith("data:image/svg+xml;base64,"))
        self.assertEqual("python_svg", rendered.render_engine)

    def test_response_builder_attaches_display_rows_with_formatted_numbers(self) -> None:
        response = build_response(
            run_id="run_display_rows",
            user_question=UserQuestion(dataset_id="ds_display_rows", question="请展示目标和达成率"),
            plan=AnalysisPlan(
                plan_id="plan_display_rows",
                logic_form=LogicForm(
                    task_type="trend",
                    operation="retail_target_actual_monthly_comparison",
                    output_format={"answer_type": "text", "decimals": 2},
                ),
            ),
            execution_result=ExecutionResult(
                backend="pandas",
                success=True,
                columns=["月份", "实际分销金额", "目标金额", "达成率"],
                rows=[{"月份": "2026年5月", "实际分销金额": 99020.96399999999, "目标金额": 256900.48692, "达成率": 32.42676508344031}],
                value={"answer": "已生成结果"},
            ),
            verification=VerificationResult(passed=True),
        )

        display_rows = response.result["display_rows"]

        self.assertEqual("99,020.96", display_rows[0]["实际分销金额"])
        self.assertEqual("256,900.49", display_rows[0]["目标金额"])
        self.assertEqual("32.43%", display_rows[0]["达成率"])

    def test_insight_generator_reports_anomaly_and_suggestion_from_verified_rows(self) -> None:
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["城市", "销售额"],
            rows=[
                {"城市": "A", "销售额": 100},
                {"城市": "B", "销售额": 105},
                {"城市": "C", "销售额": 98},
                {"城市": "D", "销售额": 102},
                {"城市": "E", "销售额": 900},
            ],
        )

        insight = generate_insight(
            question="哪个城市销售额异常？",
            execution_result=result,
            verification_passed=True,
        )

        self.assertTrue(insight.anomaly_findings)
        self.assertTrue(insight.business_suggestions)
        self.assertLessEqual(len(insight.business_suggestions), 1)
        self.assertIn("下一步", insight.business_suggestions[0])
        self.assertNotIn("客户、城市、产品或渠道", insight.business_suggestions[0])
        self.assertGreater(insight.confidence, 0)

    def test_insight_generator_tailors_next_questions_to_plan_context(self) -> None:
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["城市", "销售额"],
            rows=[{"城市": "上海", "销售额": 300}, {"城市": "北京", "销售额": 200}],
        )
        plan = AnalysisPlan(
            plan_id="plan_rank",
            logic_form=LogicForm(task_type="ranking", operation="ranking", metric="销售额", group_by="城市"),
        )

        insight = generate_insight(
            question="哪个城市销售额最高？",
            plan=plan,
            execution_result=result,
            verification_passed=True,
        )

        joined = " ".join(insight.next_questions)
        self.assertIn("销售额", joined)
        self.assertIn("城市", joined)
        self.assertNotIn("异常值来自哪些明细记录", joined)

    def test_retail_trend_next_questions_are_executable_followups(self) -> None:
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份", "天然水", "东方树叶"],
            rows=[
                {"月份": "2025年1月", "天然水": 100, "东方树叶": 40},
                {"月份": "2025年2月", "天然水": 120, "东方树叶": 60},
            ],
        )
        plan = AnalysisPlan(
            plan_id="plan_retail_trend",
            logic_form=LogicForm(
                task_type="trend",
                operation="retail_category_distribution_monthly_trend",
                parameters={"start_ym": 202501, "end_ym": 202505},
            ),
        )

        insight = generate_insight(
            question="请展示2025年1月至5月分品类历史分销金额趋势，选总金额最高的5个品类，生成折线图。",
            plan=plan,
            execution_result=result,
            verification_passed=True,
        )

        joined = " ".join(insight.next_questions)
        self.assertEqual(
            [
                "2025年1月至2025年5月分品类历史分销金额趋势，标出峰值、低点和最大波动期？",
                "2025年1月至2025年5月历史分销金额按客户拆分来源 Top 排名？",
                "2025年1月至2025年5月历史分销金额按产品拆分来源 Top 排名？",
            ],
            insight.next_questions,
        )
        self.assertEqual(
            [
                "retail_category_distribution_monthly_trend",
                "retail_distribution_topn_chart",
                "retail_distribution_topn_chart",
            ],
            [action["operation"] for action in insight.next_actions],
        )
        self.assertEqual(["ctg_name", "cust_name", "sku_name"], [action["dimension"] for action in insight.next_actions])
        self.assertTrue(all(action["status"] == "executable" for action in insight.next_actions))
        self.assertTrue(all(action["capability_family"] == "chinese_retail_business_metric" for action in insight.next_actions))
        self.assertNotIn("累计金额和占比", joined)
        self.assertNotIn("最近一期", joined)
        self.assertNotIn("城市", joined)

    def test_data_quality_report_scans_missing_duplicates_and_outliers(self) -> None:
        df = pd.DataFrame(
            [
                {"客户ID": "C1", "销售额": 100, "日期": "2026-01-01"},
                {"客户ID": "C1", "销售额": 100, "日期": "2026-01-01"},
                {"客户ID": "C2", "销售额": None, "日期": "bad-date"},
                {"客户ID": "C3", "销售额": 9999, "日期": "2026-01-03"},
            ]
        )

        report = build_data_quality_report({"销售表": df})
        issue_types = {issue.issue_type for issue in report.issues}

        self.assertIn("duplicate_rows", issue_types)
        self.assertIn("missing_values", issue_types)
        self.assertIn("invalid_dates", issue_types)
        self.assertLess(report.quality_score, 100)

    def test_data_quality_report_skips_boolean_outlier_quantiles(self) -> None:
        df = pd.DataFrame(
            {
                "is_credit": [True, False, True, True, False, True, False, True],
                "has_fraudulent_dispute": [False, False, True, False, False, True, False, False],
            }
        )

        report = build_data_quality_report({"payments": df})

        self.assertGreaterEqual(report.quality_score, 0)
        self.assertNotIn("numeric_outliers", {issue.issue_type for issue in report.issues})

    def test_reasoning_trace_view_redacts_chain_of_thought_keys(self) -> None:
        steps = build_reasoning_trace_view(
            {
                "dataset_id": "ds_test",
                "intent_summary": {"reasoning_summary": "safe summary", "chain_of_thought": "secret"},
                "verification_result": {"passed": True, "confidence": 0.9},
                "final_response": {"answer": "上海"},
            }
        )
        payload = str([step.__dict__ for step in steps])

        self.assertIn("safe summary", payload)
        self.assertNotIn("secret", payload)
        self.assertNotIn("chain_of_thought", payload)

    def test_process_view_v2_builds_distinct_safe_modes(self) -> None:
        cases = [
            ("chat", {}, {"answer_type": "chat", "execution_mode": "chat"}),
            ("dataset_overview", {"logic_form": {"operation": "dataset_overview"}}, {"answer_type": "overview", "result": {"value": {"table": "销售表", "row_count": 3, "column_count": 2}}}),
            ("metric_lookup", {"logic_form": {"operation": "sum", "metric": "销售额"}}, {"answer_type": "text", "success": True}),
            ("ranking_topn", {"logic_form": {"operation": "top_count", "metric": "订单数", "group_by": "城市"}}, {"answer_type": "text", "success": True}),
            ("comparison_or_trend", {"logic_form": {"operation": "vds_period_growth_count_share", "metric": "ARR"}}, {"answer_type": "text", "success": True}),
            ("comparison_or_trend", {"logic_form": {"operation": "detail_lookup", "metric": "销售额"}, "question": "按月份看销售额趋势"}, {"answer_type": "text", "success": True}),
            (
                "multi_table_join",
                {"logic_form": {"operation": "sum", "source_tables": ["订单表", "客户表"], "join_plan": {"trusted": True, "left_table": "订单表", "right_table": "客户表", "left_key": "客户ID", "right_key": "客户ID"}}},
                {"answer_type": "text", "success": True},
            ),
            ("multi_table_join", {"logic_form": {"operation": "ranking"}, "question": "哪个大区销售额最高？需要结合城市和大区映射。"}, {"answer_type": "text", "success": True}),
            ("diagnostic_or_anomaly", {"logic_form": {"operation": "outlier_count"}, "question": "哪个城市异常？"}, {"answer_type": "text", "success": True}),
            ("clarification_or_not_applicable", {"logic_form": {"operation": "detail_lookup"}, "question": "请计算不存在字段的利润率"}, {"answer_type": "text", "success": True}),
            ("clarification_or_not_applicable", {"logic_form": {"operation": "not_applicable"}}, {"answer_type": "text", "success": False, "warnings": ["缺少字段"]}),
        ]
        titles_by_mode = {}
        for expected_mode, trace, response in cases:
            view = build_process_view_v2(trace, response)
            titles_by_mode[expected_mode] = [step["title"] for step in view["steps"]]
            self.assertEqual("v2", view["version"])
            self.assertEqual(expected_mode, view["mode"])
            self.assertTrue(view["steps"])
            for step in view["steps"]:
                self.assertEqual(
                    {"title", "summary", "status", "evidence", "assumptions", "caveats", "confidence", "source"},
                    set(step),
                )

        self.assertNotEqual(titles_by_mode["chat"], titles_by_mode["ranking_topn"])
        self.assertIn("判断关联方式", titles_by_mode["multi_table_join"])
        self.assertIn("给出安全边界", titles_by_mode["clarification_or_not_applicable"])

    def test_process_view_v2_redacts_forbidden_raw_material(self) -> None:
        view = build_process_view_v2(
            {
                "question": "show task_id and standard answer",
                "intent_summary": {
                    "reasoning_summary": "safe summary with raw prompt and public proxy",
                    "chain_of_thought": "secret",
                    "api_key": "sk-secret",
                },
                "logic_form": {
                    "operation": "top_count",
                    "metric_definition": {"hidden_answer": "secret"},
                    "candidate_set": {"scorer": "leak"},
                },
            },
            {"answer_type": "text", "success": True, "answer": "debug: trace: tool_call"},
        )
        payload = str(view).lower()

        for token in [
            "chain_of_thought",
            "cot",
            "hidden_reasoning",
            "full_reasoning",
            "api_key",
            "hidden_answer",
            "task_id",
            "standard answer",
            "public proxy",
            "scorer",
            "raw prompt",
        ]:
            self.assertNotIn(token, payload)

    def test_process_view_v2_explains_retail_product_share_scope(self) -> None:
        view = build_process_view_v2(
            {
                "question": "张三在2026年5月的历史分销金额中，天然水占比是多少？",
                "intent_summary": {"reasoning_summary": "safe summary", "confidence": 0.9},
                "logic_form": {
                    "task_type": "ratio",
                    "operation": "retail_distribution_product_share",
                    "parameters": {
                        "person": "张三",
                        "ym": 202605,
                        "metric": "sign_amt",
                        "product": "天然水",
                        "role": "employee",
                        "table": "v_trd_dist_ord_dtl",
                    },
                },
                "pandas_result_summary": {"success": True},
                "verification_result": {"passed": True, "confidence": 0.9},
            },
            {
                "answer_type": "percentage",
                "success": True,
                "insight": {"summary": "张三在2026年5月的历史分销金额中，天然水占比约为25.00%。"},
            },
        )
        titles = [step["title"] for step in view["steps"]]
        payload = str(view)

        self.assertEqual("comparison_or_trend", view["mode"])
        self.assertIn("识别占比问题", titles)
        self.assertIn("锁定筛选口径", titles)
        self.assertIn("确认分子分母", titles)
        self.assertIn("业代：张三", payload)
        self.assertIn("月份：2026年5月", payload)
        self.assertIn("产品：天然水", payload)
        self.assertIn("分母：2026年5月 + 业代=张三 + 全部产品 的历史分销金额", payload)
        self.assertIn("分子：2026年5月 + 业代=张三 + 天然水 的历史分销金额", payload)
        self.assertNotIn("chain_of_thought", payload)
        self.assertNotIn("task_id", payload)

    def test_process_view_monitor_payload_keeps_only_safe_step_schema(self) -> None:
        payload = process_view_monitor_payload(
            {
                "run_id": "run_safe",
                "dataset_id": "ds_safe",
                "success": True,
                "answer_type": "text",
                "execution_mode": "dual",
                "process_view_v2": {
                    "version": "v2",
                    "summary": "safe summary with task_id and raw prompt",
                    "mode": "ranking_topn",
                    "steps": [
                        {
                            "title": "safe title",
                            "summary": "uses standard answer and scorer",
                            "status": "completed",
                            "raw_prompt": "secret",
                            "task_id": "bench_1",
                            "evidence": ["public proxy should be hidden"],
                        }
                    ],
                },
            }
        )
        serialized = str(payload).lower()

        self.assertEqual("ranking_topn", payload["process_view_v2"]["mode"])
        self.assertEqual(
            {"title", "summary", "status", "evidence", "assumptions", "caveats", "confidence", "source"},
            set(payload["process_view_v2"]["steps"][0]),
        )
        for forbidden in ("task_id", "raw prompt", "standard answer", "public proxy", "scorer", "secret"):
            self.assertNotIn(forbidden, serialized)

    def test_monitor_payload_sanitizer_blocks_cot_prompts_keys_and_scorer_material(self) -> None:
        payload = sanitize_monitor_payload(
            {
                "safe": "我先检查文件结构",
                "chain_of_thought": "hidden reasoning",
                "raw_prompt": "system prompt",
                "reasoning_tokens": [1, 2, 3],
                "api_key": "sk-secret",
                "task_id": "abc",
                "standard_answer": "gold",
                "hidden_answer": "hidden",
                "public_proxy": "score",
                "scorer": "judge",
                "nested": {"authorization": "Bearer token", "summary": "safe note"},
            }
        )
        serialized = str(payload).lower()

        self.assertIn("safe note", serialized)
        for forbidden in (
            "chain_of_thought",
            "hidden reasoning",
            "raw_prompt",
            "system prompt",
            "reasoning_tokens",
            "api_key",
            "sk-secret",
            "task_id",
            "standard_answer",
            "hidden_answer",
            "public_proxy",
            "scorer",
            "authorization",
            "bearer token",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_backend_returns_quality_chart_insight_and_trace_for_quality_question(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "客户ID,城市,销售额,日期\n"
                "C1,上海,100,2026-01-01\n"
                "C1,上海,100,2026-01-01\n"
                "C2,北京,,bad-date\n"
                "C3,深圳,9999,2026-01-03\n",
                encoding="utf-8",
            )
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            upload = service.upload_dataset(csv_path)
            response = service.analyze_dataset(
                dataset_id=upload["dataset_id"],
                question="我的文件有什么问题？",
                execution_mode="dual",
            )

        self.assertTrue(upload["quality_report"]["issue_count"] > 0)
        self.assertTrue(response["success"])
        self.assertIn("quality_report", response)
        self.assertGreater(response["quality_report"]["issue_count"], 0)
        self.assertIn("chart", response)
        self.assertIn("insight", response)
        self.assertTrue(response["reasoning_trace_view"])
        self.assertTrue(response["process_view_v2"]["steps"])
        self.assertNotIn("chain_of_thought", str(response["reasoning_trace_view"]))


if __name__ == "__main__":
    unittest.main()
