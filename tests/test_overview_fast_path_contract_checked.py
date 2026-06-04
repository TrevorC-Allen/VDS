from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


class OverviewFastPathContractCheckedTest(unittest.TestCase):
    def _assert_overview_contract_tracking(self, response: dict[str, object]) -> None:
        contract_report = response.get("contract_report")
        is_checked = isinstance(contract_report, dict) and bool(contract_report)
        semantic_status = str(response.get("semantic_status") or "")
        self.assertTrue(response.get("success"), response.get("errors"))
        self.assertNotEqual((False, "passed"), (is_checked, semantic_status), "contract_checked=false 且 semantic_status=passed 不允许")
        if is_checked:
            self.assertIn(response.get("contract_family"), {"overview", "multi_file_overview"})
            self.assertIsInstance(response.get("contract_report"), dict)
            self.assertIn("task_family", response.get("contract_report"))
            self.assertIsInstance(response.get("contract_satisfied"), bool)
            self.assertEqual(response.get("contract_family"), response["contract_report"]["task_family"])
        else:
            self.assertEqual("legacy_unverified", semantic_status)
            self.assertIn("overview fast-path", str(response.get("unverified_reason") or ""))

    def test_single_table_overview_fast_path_has_contract_check_status(self) -> None:
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
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_dataset(csv_path, original_filename="service_metrics.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="帮我概览上传的服务区域经营数据结构和可分析方向。",
                execution_mode="dual",
            )

        self._assert_overview_contract_tracking(response)

    def test_multi_table_overview_fast_path_has_contract_check_status(self) -> None:
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
            service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            upload = service.upload_datasets([orders_path, customers_path], original_filenames=["orders.csv", "customers.csv"])
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="帮我概览这批客户订单收入上传文件能支持哪些分析。",
                execution_mode="dual",
            )

        self._assert_overview_contract_tracking(response)


if __name__ == "__main__":
    unittest.main()
