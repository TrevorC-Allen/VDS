from __future__ import annotations

import unittest

from data_agent_core.oracle_results import (
    oracle_overview_schema_field_coverage,
    oracle_quality_field_counts,
    oracle_topn_followup_gap,
)
from scripts.run_agent_random_conversation_eval import (
    _deterministic_fixture_oracle_result_trend_followup,
    TurnPlan,
)


class OracleNegativeCasesTest(unittest.TestCase):
    def _trend_turn(self) -> TurnPlan:
        return TurnPlan(
            question="按月份看趋势",
            expected_kind="followup_analysis",
            capability_family="trend_followup",
            required_operation="aggregation",
        )

    def _trend_logic(self) -> dict[str, object]:
        return {
            "operation": "aggregation",
            "parameters": {
                "metric": "sales",
                "dimension": "month",
            },
        }

    def _trend_response(self, answer: str) -> dict[str, object]:
        rows = [
            {"month": "2026-01", "sales": 396},
            {"month": "2026-02", "sales": 550},
            {"month": "2026-03", "sales": 482},
        ]
        return {
            "answer": answer,
            "result": {"rows": rows},
        }

    def test_case1_trend_wrong_shape_and_forbidden_description(self) -> None:
        result = _deterministic_fixture_oracle_result_trend_followup(
            self._trend_logic(),
            self._trend_response(answer="整体上升"),
        )

        self.assertFalse(result["passed"], result)
        issue_codes = [str(code) for code in result.get("issue_codes", [])]
        self.assertTrue(
            any("trend_shape_mismatch" in code or "forbidden_trend_description" in code for code in issue_codes),
            issue_codes,
        )

    def test_case2_gap_adjacent_values_mismatch(self) -> None:
        expected = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": 563},
                {"rank": 3, "value": "北京", "metric_value": 276},
            ],
            "adjacent_gaps": [186, 287],
            "gap_to_leader": [0, 186, 473],
        }
        actual = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": 563},
                {"rank": 3, "value": "北京", "metric_value": 276},
            ],
            "adjacent_gaps": [100, 200],
            "gap_to_leader": [0, 186, 473],
        }

        result = oracle_topn_followup_gap(expected, actual, answer="深圳相比上海差距100，北京相比上海差距200。")

        self.assertFalse(result.passed, result)
        issue_codes = [str(code) for code in result.issue_codes]
        self.assertTrue(any("gap_mismatch" in code for code in issue_codes), issue_codes)

    def test_case3_overview_missing_required_field(self) -> None:
        expected = {
            "tables": [
                {
                    "name": "orders",
                    "fields": [
                        {"name": "month", "role": "time"},
                        {"name": "city", "role": "dimension"},
                        {"name": "profit", "role": "metric"},
                    ],
                    "required_fields": ["month", "city", "profit", "segment"],
                }
            ],
            "required_fields": ["month", "city", "profit", "segment"],
            "metric_candidates": ["profit"],
            "dimension_candidates": ["city", "segment"],
            "time_columns": ["month"],
            "analysis_directions": ["按月和城市看利润与客群。"],
        }
        actual = {
            "tables": [
                {
                    "name": "orders",
                    "fields": [
                        {"name": "month", "role": "time", "type": "datetime"},
                        {"name": "city", "role": "dimension", "type": "string"},
                        {"name": "service_line", "role": "dimension", "type": "string"},
                    ],
                }
            ],
            "metric_candidates": ["sales"],
            "dimension_candidates": ["city"],
            "time_columns": ["month"],
            "analysis_directions": ["按月和城市看销售额。"],
        }

        result = oracle_overview_schema_field_coverage(expected, actual)

        self.assertFalse(result.passed, result)
        issue_codes = [str(code) for code in result.issue_codes]
        self.assertTrue(any(code.startswith("overview_required_field_missing") for code in issue_codes), issue_codes)

    def test_case4_quality_missing_field_level_table(self) -> None:
        expected = {
            "fields": [
                {"name": "month", "missing_count": 0, "missing_rate": "0%", "type_issue_count": 0, "outlier_count": 0},
                {"name": "city", "missing_count": 0, "missing_rate": "0%", "type_issue_count": 0, "outlier_count": 0},
            ],
            "duplicate_checks": {"full_row_duplicate_count": 0},
            "outlier_rules": ["numeric IQR rule"],
        }
        actual = {
            "total_issue_count": 0,
            "summary": "未发现问题",
        }

        result = oracle_quality_field_counts(expected, actual)

        self.assertFalse(result.passed, result)
        issue_codes = [str(code) for code in result.issue_codes]
        self.assertIn("quality_field_level_missing", issue_codes)


if __name__ == "__main__":
    unittest.main()
