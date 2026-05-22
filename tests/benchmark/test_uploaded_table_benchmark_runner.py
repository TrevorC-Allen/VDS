"""Tests for generic uploaded-table benchmark runner scoring."""

from __future__ import annotations

import unittest

from multi_agent_workflows.uploaded_table_benchmark_runner import _score_expected


class UploadedTableBenchmarkRunnerTest(unittest.TestCase):
    def test_scores_structured_raw_value_after_safe_final_answer(self) -> None:
        expected = "[{'区域': '华北', 'count': 255}, {'区域': '华中', 'count': 250}]"
        predicted = "华北, 255, 华中, 250"
        raw_value = [{"区域": "华北", "count": 255}, {"区域": "华中", "count": 250}]

        self.assertTrue(_score_expected(expected, predicted, raw_value))

    def test_scores_string_answer_before_structured_fallback(self) -> None:
        self.assertTrue(_score_expected("14, 38.89%", "14, 38.89%", {"answer": "14, 38.89%"}))


if __name__ == "__main__":
    unittest.main()
