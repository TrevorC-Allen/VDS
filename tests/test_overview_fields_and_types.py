from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.output.dataset_overview import build_dataset_overview_response


class OverviewFieldsAndTypesTest(unittest.TestCase):
    def test_single_table_overview_lists_all_fields_and_types_and_analysis_directions(self) -> None:
        tables = {
            "service_metrics": pd.DataFrame(
                [
                    {
                        "month": "2026-01",
                        "city": "Shanghai",
                        "service_line": "installation",
                        "sales": 1000,
                        "profit": 220,
                        "tickets": 11,
                    },
                    {
                        "month": "2026-02",
                        "city": "Beijing",
                        "service_line": "repair",
                        "sales": 900,
                        "profit": 210,
                        "tickets": 10,
                    },
                ]
            )
        }
        response = build_dataset_overview_response(
            run_id="unit-test-single",
            dataset_id="service_metrics_dataset",
            question="帮我概览上传的服务区域经营数据结构和可分析方向。",
            tables=tables,
            profile=None,
        )

        overview = response["overview_report"]
        answer = response["answer"]

        self.assertEqual("overview", response["answer_type"])
        self.assertTrue(response["success"])
        self.assertEqual("service_metrics", overview["table"])

        fields = overview["field_meanings"]
        field_names = {str(item.get("field")) for item in fields if isinstance(item, dict)}
        field_types = {
            str(item.get("field")): str(item.get("type") or "")
            for item in fields
            if isinstance(item, dict) and item.get("field") is not None
        }

        expected_fields = ("month", "city", "service_line", "sales", "profit", "tickets")
        for field in expected_fields:
            self.assertIn(field, field_names, f"字段 {field} 应在 field_meanings 中出现")
            self.assertIn(field, field_types, f"字段 {field} 应有 type 字段")
            self.assertTrue(field_types[field], f"字段 {field} 的 type 不能为空")

        for field in expected_fields:
            self.assertIn(field, answer, f"回答文本应包含字段 {field}")

        self.assertIn("字段 | 类型 | 角色 | 可用于什么分析", answer)
        for token in ("sales", "profit", "tickets", "city", "service_line", "month"):
            self.assertIn(token, answer)

    def test_multi_table_overview_lists_all_fields_join_keys_and_analysis_directions(self) -> None:
        tables = {
            "orders": pd.DataFrame(
                [
                    {
                        "month": "2026-01",
                        "amount": 1000,
                        "profit": 220,
                        "customer_id": "C1",
                    },
                    {
                        "month": "2026-02",
                        "amount": 1500,
                        "profit": 300,
                        "customer_id": "C2",
                    },
                ]
            ),
            "customers": pd.DataFrame(
                [
                    {
                        "city": "Shanghai",
                        "segment": "enterprise",
                        "customer_id": "C1",
                    },
                    {
                        "city": "Beijing",
                        "segment": "smb",
                        "customer_id": "C2",
                    },
                ]
            ),
        }
        response = build_dataset_overview_response(
            run_id="unit-test-multi",
            dataset_id="orders_customers_dataset",
            question="帮我概览这批客户订单收入上传文件能支持哪些分析。",
            tables=tables,
            profile=None,
        )

        overview = response["overview_report"]
        answer = response["answer"]
        table_summaries = overview["tables_summary"]

        self.assertEqual("multi_table", overview.get("overview_scope"))
        self.assertIn("candidate_join_keys", overview)

        by_name = {
            str(summary.get("table") or ""): summary
            for summary in table_summaries
            if isinstance(summary, dict)
        }

        orders = by_name.get("orders")
        customers = by_name.get("customers")
        self.assertIsNotNone(orders)
        self.assertIsNotNone(customers)

        orders_fields = {str(item.get("field")) for item in orders.get("field_meanings", []) if isinstance(item, dict)}
        customers_fields = {str(item.get("field")) for item in customers.get("field_meanings", []) if isinstance(item, dict)}

        for field in ("month", "amount", "profit", "customer_id"):
            self.assertIn(field, orders_fields, f"orders 表应包含字段 {field}")
        for field in ("city", "segment", "customer_id"):
            self.assertIn(field, customers_fields, f"customers 表应包含字段 {field}")

        join_keys = [str(item.get("text")) for item in overview.get("candidate_join_keys", []) if isinstance(item, dict)]
        self.assertIn("orders.customer_id -> customers.customer_id", join_keys)

        for token in ("amount", "profit", "city", "segment", "month"):
            self.assertIn(token, answer)
        self.assertIn("可分析方向", answer)


if __name__ == "__main__":
    unittest.main()
