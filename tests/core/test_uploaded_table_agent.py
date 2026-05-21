"""Core tests for uploaded CSV / Excel-style single-table analysis."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from data_agent_core.agent.single_agent import UploadedDatasetAgent
from data_agent_core.core.file_parser import parse_dataset_file
from data_agent_core.llm.client import MockLLMClient


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


if __name__ == "__main__":
    unittest.main()
