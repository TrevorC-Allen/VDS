from __future__ import annotations

import unittest

from data_agent_core.oracle_results import oracle_topn_followup_gap


class OracleRankingFollowupGapTest(unittest.TestCase):
    def test_oracle_gap_case_1_exact_match_and_passes(self) -> None:
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
            "adjacent_gaps": [186, 287],
            "gap_to_leader": [0, 186, 473],
        }

        result = oracle_topn_followup_gap(expected, actual, answer="深圳相比上海差距186，北京相比上海差距287。")

        self.assertTrue(result.oracle_available)
        self.assertTrue(result.passed)
        self.assertEqual([], result.issue_codes)
        self.assertEqual([186, 287], (result.actual_result or {}).get("adjacent_gaps"))
        self.assertEqual([0, 186, 473], (result.actual_result or {}).get("gap_to_leader"))

    def test_oracle_gap_case_2_only_top1_reports_insufficient_objects(self) -> None:
        expected = {
            "top_objects": [{"rank": 1, "value": "深圳", "metric_value": 749}],
            "adjacent_gaps": [],
            "gap_to_leader": [0],
        }
        actual = {
            "top_objects": [{"rank": 1, "value": "深圳", "metric_value": 749}],
            "adjacent_gaps": [],
            "gap_to_leader": [0],
        }

        result = oracle_topn_followup_gap(expected, actual, answer="只有深圳一条，没法算相邻差距。")

        self.assertFalse(result.passed)
        self.assertIn("insufficient_objects_for_gap", result.issue_codes)

    def test_oracle_gap_case_3_metric_value_missing_flags_issue(self) -> None:
        expected = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": 563},
            ],
            "adjacent_gaps": [186],
            "gap_to_leader": [0, 186],
        }
        actual = {
            "top_objects": [
                {"rank": 1, "value": "深圳", "metric_value": 749},
                {"rank": 2, "value": "上海", "metric_value": None},
            ],
            "adjacent_gaps": [186],
            "gap_to_leader": [0, 186],
        }

        result = oracle_topn_followup_gap(expected, actual, answer="Top1和Top2之间差距需要再算。")

        self.assertFalse(result.passed)
        self.assertIn("gap_metric_value_missing", result.issue_codes)


if __name__ == "__main__":
    unittest.main()
