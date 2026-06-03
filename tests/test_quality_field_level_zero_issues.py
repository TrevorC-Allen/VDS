"""Tests for zero-issue quality reporting and field-level rendering."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


class QualityFieldLevelZeroIssuesTest(unittest.TestCase):
    def test_zero_issue_quality_question_returns_field_level_metrics_and_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "service_metrics.csv"
            csv_path.write_text(
                "month,city,service_line,sales,profit,tickets\n"
                "2026-01,Shanghai,installation,1000,220,11\n"
                "2026-02,Beijing,repair,850,160,9\n"
                "2026-03,Guangzhou,support,1200,260,13\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="service_metrics.csv")

            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="做分析前先看数据质量，重点查缺失、重复和异常值。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertEqual("passed", response.get("semantic_status"))
        quality = response.get("quality_report")
        self.assertIsInstance(quality, dict)
        self.assertIn("field_level_table", quality)

        expected_fields = {"month", "city", "service_line", "sales", "profit", "tickets"}
        field_rows = quality["field_level_table"]
        actual_fields = {
            str(row.get("字段") or row.get("field") or row.get("column") or row.get("column_name") or "").strip()
            for row in field_rows
            if (row.get("字段") or row.get("field") or row.get("column") or row.get("column_name"))
        }
        self.assertTrue(expected_fields.issubset(actual_fields), actual_fields)

        indexed_rows = {}
        for row in field_rows:
            field = str(row.get("字段") or row.get("field") or row.get("column") or row.get("column_name") or "").strip()
            if field in expected_fields:
                indexed_rows[field] = row
        for field in expected_fields:
            self.assertIn(field, indexed_rows, indexed_rows)
            row = indexed_rows[field]
            missing = row.get("missing_count", row.get("缺失数"))
            missing_rate = row.get("missing_rate", row.get("缺失率"))
            outlier_count = row.get("outlier_count", row.get("anomaly_count", row.get("异常值数")))
            type_issue = row.get("type_issue_count", row.get("parse_failure_count", row.get("类型异常数")))
            self.assertIsNotNone(missing, f"{field}: missing count missing")
            self.assertIsNotNone(missing_rate, f"{field}: missing rate missing")
            self.assertIsNotNone(outlier_count, f"{field}: outlier/anomaly count missing")
            self.assertIsNotNone(type_issue, f"{field}: type issue count missing")
            self.assertEqual(0, int(missing))
            self.assertEqual(0, int(outlier_count))
            self.assertEqual(0, int(type_issue))

        duplicate_rules = quality.get("duplicate_rules")
        self.assertIsInstance(duplicate_rules, list)
        self.assertTrue(duplicate_rules)
        has_rule = any(
            isinstance(rule, dict)
            and ("full_row_duplicate_count" in rule or ("key_duplicate_count" in rule and rule.get("key_duplicate_count") is not None))
            for rule in duplicate_rules
        )
        self.assertTrue(has_rule, quality.get("duplicate_rules"))
        self.assertEqual(0, int((duplicate_rules[0].get("full_row_duplicate_count") or 0) if isinstance(duplicate_rules[0], dict) else 0))

        answer = str(response.get("answer") or "")
        self.assertIn("| 字段 | 缺失数 | 缺失率 | 类型异常数 | 异常值数 | 检测规则 | 备注 |", answer)
        for field in expected_fields:
            self.assertIn(f"| {field} |", answer)
        self.assertTrue("full_row_duplicate_count" in answer or "key_duplicate_count" in answer)

        payload = json.dumps(response, ensure_ascii=False)
        self.assertNotIn("列出每类质量问题影响字段和行数", payload)
        self.assertNotIn("列出每类质量问题影响的字段和行数", payload)


if __name__ == "__main__":
    unittest.main()
