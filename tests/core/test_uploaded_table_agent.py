"""Core tests for uploaded CSV / Excel-style single-table analysis."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_agent_core.agent.single_agent import UploadedDatasetAgent
from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec
from data_agent_core.core.file_parser import parse_dataset_file
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.llm.planner import LLMStageResult


class UploadedTableAgentTest(unittest.TestCase):
    def test_parse_csv_profile_and_rank_city_sales(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sales.csv"
            csv_path.write_text(
                "city,sales,category\n"
                "Shanghai,100,A\n"
                "Beijing,150,A\n"
                "Shanghai,200,B\n",
                encoding="utf-8",
            )

            parsed = parse_dataset_file(csv_path, dataset_id="ds_test_sales")
            self.assertEqual(parsed.profile.dataset_id, "ds_test_sales")
            self.assertEqual(parsed.profile.tables[0].row_count, 3)
            agent = UploadedDatasetAgent(parsed.tables, parsed.profile.dataset_id, llm_client=MockLLMClient())
            response, trace = agent.analyze("Which city has the highest sales?", execution_mode="dual")

        self.assertTrue(response.success)
        self.assertEqual(response.run_id, trace.run_id)
        self.assertEqual(response.debug["operation"], "ranking")
        self.assertTrue(response.verification["pandas_sql_consistent"])
        self.assertEqual(response.result["rows"][0]["city"], "Shanghai")
        self.assertEqual(response.result["rows"][0]["sales"], 300)

    def test_grouped_aggregation_uses_uploaded_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sales.csv"
            csv_path.write_text(
                "city,sales\n"
                "Shanghai,100\n"
                "Beijing,150\n"
                "Shanghai,200\n",
                encoding="utf-8",
            )

            parsed = parse_dataset_file(csv_path, dataset_id="ds_test_grouped")
            agent = UploadedDatasetAgent(parsed.tables, parsed.profile.dataset_id, llm_client=MockLLMClient())
            response, _trace = agent.analyze("What is the total sales by city?", execution_mode="dual")

        rows = sorted(response.result["rows"], key=lambda row: row["city"])
        self.assertTrue(response.success)
        self.assertEqual(rows, [{"city": "Beijing", "sales": 150}, {"city": "Shanghai", "sales": 300}])

    def test_llm_chart_override_cannot_reference_columns_missing_from_data(self) -> None:
        agent = UploadedDatasetAgent({"sales": pd.DataFrame({"answer": [4]})}, "ds_test_chart_guard", llm_client=MockLLMClient())
        rule_chart = ChartSpec(chart_type="kpi", data=[{"answer": 4}], encoding={"value": "answer"})
        llm_stage = LLMStageResult(
            stage_name="chart_planner",
            raw={"chart_type": "bar", "x": "city", "y": "total_sales", "confidence": 0.9},
            confidence=0.9,
            reasoning_summary="Mocked unsafe chart override.",
        )

        chart = agent._chart_from_stage(rule_chart, llm_stage, trusted=True)

        self.assertEqual("kpi", chart.chart_type)
        self.assertEqual([{"answer": 4}], chart.data)

    def test_llm_insight_stage_filters_english_user_facing_text(self) -> None:
        agent = UploadedDatasetAgent({"sales": pd.DataFrame({"answer": [4]})}, "ds_test_insight_guard", llm_client=MockLLMClient())
        llm_stage = LLMStageResult(
            stage_name="insight_generator",
            raw={
                "summary": "The result shows NL leading by eur_amount.",
                "suggestions": ["The result includes only 8 countries, not a full top 10."],
                "caveats": ["Compare the top countries by eur_amount."],
            },
            confidence=0.8,
            reasoning_summary="Mocked English insight leakage.",
        )

        insight = agent._insight_from_stage("第 1 位是 NL。", True, llm_stage)

        self.assertEqual("第 1 位是 NL。", insight.summary)
        self.assertEqual([], insight.suggestions)
        self.assertEqual([], insight.business_suggestions)
        self.assertEqual([], insight.caveats)

    def test_llm_insight_stage_keeps_base_multi_series_trend_summary_when_llm_only_mentions_one_series(self) -> None:
        agent = UploadedDatasetAgent({"sales": pd.DataFrame({"answer": [4]})}, "ds_test_multi_series_guard", llm_client=MockLLMClient())
        llm_stage = LLMStageResult(
            stage_name="insight_generator",
            raw={"summary": "水溶C100 在前几个月表现突出。"},
            confidence=0.8,
            reasoning_summary="Mocked narrow summary.",
        )
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份", "天然水", "纯净水", "东方树叶", "水溶C100", "茶π"],
            rows=[
                {"月份": "2026年1月", "天然水": 300000, "纯净水": 120000, "东方树叶": 180000, "水溶C100": 150000, "茶π": 90000},
                {"月份": "2026年2月", "天然水": 320000, "纯净水": 110000, "东方树叶": 190000, "水溶C100": 140000, "茶π": 95000},
                {"月份": "2026年3月", "天然水": 330000, "纯净水": 130000, "东方树叶": 210000, "水溶C100": 135000, "茶π": 98000},
                {"月份": "2026年4月", "天然水": 340000, "纯净水": 150000, "东方树叶": 260000, "水溶C100": 125000, "茶π": 102000},
                {"月份": "2026年5月", "天然水": 345000, "纯净水": 240000, "东方树叶": 220000, "水溶C100": 120000, "茶π": 110000},
            ],
        )
        plan = AnalysisPlan(plan_id="plan_multi_series", logic_form=LogicForm(task_type="trend", operation="retail_category_distribution_monthly_trend"))

        insight = agent._insight_from_stage(
            "已生成趋势图。",
            True,
            llm_stage,
            question="请展示2026年1月至5月Top5品类历史分销金额趋势。",
            plan=plan,
            execution_result=result,
        )

        self.assertIn("天然水", insight.summary)
        self.assertIn("纯净水", insight.summary)
        self.assertIn("东方树叶", insight.summary)
        self.assertNotEqual("水溶C100 在前几个月表现突出。", insight.summary)


if __name__ == "__main__":
    unittest.main()
