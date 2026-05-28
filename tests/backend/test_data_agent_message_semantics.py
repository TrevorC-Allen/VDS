"""Service-level semantic checks for /message analysis flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


class DataAgentMessageSemanticsTest(unittest.TestCase):
    def test_message_grouped_chart_request_returns_aggregated_chart_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city.csv"
            csv_path.write_text(
                "city,sales\n"
                "上海,100\n"
                "北京,120\n"
                "上海,140\n"
                "北京,160\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="按城市展示销售额，生成柱状图。")

        rows_by_city = {row["city"]: row["sales"] for row in response["result"]["rows"]}
        self.assertTrue(response["success"])
        self.assertEqual("aggregation", response["debug"]["operation"])
        self.assertEqual({"上海": 240, "北京": 280}, rows_by_city)
        self.assertTrue(response["verification"]["passed"])
        self.assertEqual("bar", response["chart"]["chart_type"])
        self.assertEqual(rows_by_city, {row["city"]: row["sales"] for row in response["chart"]["data"]})

    def test_message_same_schema_multi_file_uses_all_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "a.csv"
            b_path = root / "b.csv"
            a_path.write_text("门店,产品,sales\nA店,苹果,150\n", encoding="utf-8")
            b_path.write_text("门店,产品,sales\nB店,苹果,170\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([a_path, b_path], original_filenames=["a.csv", "b.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="A店和B店哪个门店总销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("ranking", response["debug"]["operation"])
        self.assertEqual([{"门店": "B店", "sales": 170}], response["result"]["rows"])
        self.assertEqual(["a", "b"], response["debug"]["source_tables"])
        self.assertIn("same_schema_union", response["debug"]["table_selection_reason"])
        self.assertTrue(response["verification"]["passed"])


if __name__ == "__main__":
    unittest.main()
