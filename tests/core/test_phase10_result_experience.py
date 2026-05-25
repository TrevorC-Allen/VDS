"""Phase 10 tests for visualization, insight, quality, and trace UX."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.data_quality import build_data_quality_report
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.output.chart_planner import build_chart_spec
from data_agent_core.output.chart_renderer import attach_rendered_chart
from data_agent_core.output.insight_generator import generate_insight
from data_agent_core.output.reasoning_trace_view import build_reasoning_trace_view


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
        self.assertGreater(insight.confidence, 0)

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
        self.assertNotIn("chain_of_thought", str(response["reasoning_trace_view"]))


if __name__ == "__main__":
    unittest.main()
