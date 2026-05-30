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

    def test_message_explicit_file_product_question_returns_product_not_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "qa_store_a.csv"
            b_path = root / "qa_store_b.csv"
            a_path.write_text("store,product,sales\nA店,苹果,80\nA店,香蕉,70\n", encoding="utf-8")
            b_path.write_text("store,product,sales\nB店,苹果,80\nB店,香蕉,90\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([a_path, b_path], original_filenames=["qa_store_a.csv", "qa_store_b.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="qa_store_b.csv里面哪个产品销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"product": "香蕉", "sales": 90}], response["result"]["rows"])
        self.assertEqual(["qa_store_b"], response["debug"]["source_tables"])
        self.assertEqual("product", response["logic_form"]["parameters"]["dimension"])
        self.assertNotIn("当前结果表只返回", response["answer"])

    def test_message_profit_margin_uses_derived_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city_profit.csv"
            csv_path.write_text("city,sales,profit\n上海,100,40\n北京,280,56\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city_profit.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市利润率最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"city": "上海", "利润率": 0.4}], response["result"]["rows"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertNotEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertIn("sum(profit)/sum(sales)", response["answer"])
        self.assertNotIn("当前结果表只返回", response["answer"])
        self.assertNotIn("仍需按当前数据范围和指标口径解读", response["answer"])

    def test_message_correction_reruns_with_revised_formula_from_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city_profit.csv"
            csv_path.write_text("city,sales,profit\n上海,100,40\n北京,300,60\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city_profit.csv")
            first = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市利润最高？")
            response = service.respond_to_message(
                conversation_id=first["conversation_id"],
                question="不是这个口径，用利润率=sum利润/sum销售重新算",
            )

        self.assertTrue(first["success"], first["errors"])
        self.assertEqual([{"city": "北京", "profit": 60}], first["result"]["rows"])
        self.assertTrue(response["success"], response["errors"])
        self.assertEqual(first["conversation_id"], response["conversation_id"])
        self.assertEqual([{"city": "上海", "利润率": 0.4}], response["result"]["rows"])
        self.assertTrue(response["correction_context"]["is_correction"])
        self.assertEqual(first["run_id"], response["correction_context"]["previous_run_id"])
        self.assertEqual(["metric_formula"], response["correction_context"]["changed_scope"])
        self.assertIn("sum(profit)/sum(sales)", response["answer"])
        self.assertIn("首行结果", response["correction_context"]["difference_summary"])

    def test_message_incomplete_correction_asks_for_formula_without_reusing_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city_profit.csv"
            csv_path.write_text("city,sales,profit\n上海,100,40\n北京,300,60\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city_profit.csv")
            first = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市利润最高？")
            response = service.respond_to_message(
                conversation_id=first["conversation_id"],
                question="不是这个口径，重新算",
            )

        self.assertFalse(response["success"])
        self.assertEqual("clarification", response["answer_type"])
        self.assertEqual("missing_revised_formula", response["correction_context"]["reason"])
        self.assertEqual([], response["result"]["rows"])
        self.assertIn("利润率=sum利润/sum销售", response["answer"])

    def test_message_trusted_join_returns_joined_city_top1_without_audit_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "orders.csv"
            customers_path = root / "customers.csv"
            orders_path.write_text("customer_id,sales\nC1,100\nC2,120\nC3,70\n", encoding="utf-8")
            customers_path.write_text("customer_id,city\nC1,北京\nC2,上海\nC3,北京\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([orders_path, customers_path], original_filenames=["orders.csv", "customers.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市总销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"city": "北京", "sales": 170}], response["result"]["rows"])
        self.assertIn("orders.customer_id", response["answer"])
        self.assertIn("customers.customer_id", response["answer"])
        self.assertNotIn("当前结果表只返回", response["answer"])
        self.assertNotIn("仍需按当前数据范围和指标口径解读", response["answer"])

    def test_message_untrusted_join_key_explains_candidate_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "orders.csv"
            customers_path = root / "customers.csv"
            orders_path.write_text("customer_id,sales\nC1,100\nC2,120\n", encoding="utf-8")
            customers_path.write_text("customer_id,city\nX1,北京\nX2,上海\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([orders_path, customers_path], original_filenames=["orders.csv", "customers.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市总销售额最高？")

        self.assertFalse(response["success"])
        self.assertFalse(response["verification"]["passed"])
        self.assertIn("orders.customer_id", response["answer"])
        self.assertIn("customers.customer_id", response["answer"])
        self.assertIn("关联", response["answer"])

    def test_message_same_schema_union_product_ranking_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "qa_store_a.csv"
            b_path = root / "qa_store_b.csv"
            a_path.write_text("store,product,sales\nA店,苹果,100\nA店,香蕉,70\n", encoding="utf-8")
            b_path.write_text("store,product,sales\nB店,苹果,80\nB店,香蕉,90\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([a_path, b_path], original_filenames=["qa_store_a.csv", "qa_store_b.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="A店和B店合起来哪个产品销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertTrue(response["verification"]["passed"], response["verification"])
        self.assertEqual([{"product": "苹果", "sales": 180}], response["result"]["rows"])
        self.assertEqual(["qa_store_a", "qa_store_b"], response["debug"]["source_tables"])
        self.assertIn("same_schema_union", response["debug"]["table_selection_reason"])
        self.assertNotIn("__same_schema_union__", response["answer"])

    def test_message_monthly_trend_uses_month_dimension_for_chart_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "month,city,sales\n"
                "2026-01,上海,100\n"
                "2026-01,北京,250\n"
                "2026-02,广州,180\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="按月份展示销售额趋势，生成折线图。")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("month", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"2026-01": 350, "2026-02": 180}, {row["month"]: row["sales"] for row in response["result"]["rows"]})
        self.assertEqual("line", response["chart"]["chart_type"])
        self.assertEqual("month", response["chart"]["x"])
        self.assertEqual({"2026-01": 350, "2026-02": 180}, {row["month"]: row["sales"] for row in response["chart"]["data"]})
        self.assertNotIn("city", response["chart"]["data"][0])

    def test_message_missing_channel_dimension_does_not_fallback_to_city(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text("city,sales\n北京,280\n上海,100\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个渠道销售额最高？")

        self.assertFalse(response["success"])
        self.assertFalse(response["verification"]["passed"])
        self.assertNotEqual("city", response["logic_form"]["parameters"].get("dimension"))
        self.assertIn("渠道", response["answer"])
        self.assertNotIn("北京 280", response["answer"])

    def test_message_category_join_uses_products_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path, products_path, customers_path = _write_order_product_customer_files(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(
                [orders_path, products_path, customers_path],
                original_filenames=["orders.csv", "products.csv", "customers.csv"],
            )
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个品类总销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"category": "水果", "sales": 180}], response["result"]["rows"])
        self.assertEqual("category", response["logic_form"]["parameters"]["dimension"])
        self.assertIn("products", response["debug"]["source_tables"])
        self.assertTrue(response["debug"]["join_plan"]["trusted"])

    def test_message_category_join_with_city_filter_uses_customers_and_products(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path, products_path, customers_path = _write_order_product_customer_files(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(
                [orders_path, products_path, customers_path],
                original_filenames=["orders.csv", "products.csv", "customers.csv"],
            )
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="北京哪个品类销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"category": "零食", "sales": 120}], response["result"]["rows"])
        self.assertEqual({"city": "北京"}, response["logic_form"]["filters"])
        self.assertEqual({"orders", "products", "customers"}, set(response["debug"]["source_tables"]))
        self.assertTrue(response["debug"]["join_plan"]["trusted"])
        self.assertEqual(2, len(response["debug"]["join_plan"]["steps"]))


def _write_order_product_customer_files(root: Path) -> tuple[Path, Path, Path]:
    orders_path = root / "orders.csv"
    products_path = root / "products.csv"
    customers_path = root / "customers.csv"
    orders_path.write_text(
        "order_id,customer_id,product_id,sales\n"
        "O1,C1,P1,100\n"
        "O2,C2,P2,80\n"
        "O3,C1,P3,120\n",
        encoding="utf-8",
    )
    products_path.write_text("product_id,category\nP1,水果\nP2,水果\nP3,零食\n", encoding="utf-8")
    customers_path.write_text("customer_id,city\nC1,北京\nC2,上海\n", encoding="utf-8")
    return orders_path, products_path, customers_path


if __name__ == "__main__":
    unittest.main()
