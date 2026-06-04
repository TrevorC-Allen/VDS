"""Regression tests for trend summary and renderer behavior on full series data."""

from __future__ import annotations

import unittest

from data_agent_core.output.text_answer_framework import apply_text_answer_framework, describe_trend


class TrendDescriptionSequenceTest(unittest.TestCase):
    def assert_has_peak_or_wave(self, text: str) -> None:
        self.assertTrue(
            any(token in text for token in ("先升后降", "波动", "回落")),
            f"Expected peak or wave wording in: {text!r}",
        )

    def test_renderer_uses_full_sequence_for_up_then_down(self) -> None:
        sequence_description = describe_trend({"2026-01": 396, "2026-02": 550, "2026-03": 482})
        self.assertNotIn("整体上升", sequence_description)
        self.assertNotIn("单调上升", sequence_description)
        self.assertNotIn("持续上升", sequence_description)
        self.assert_has_peak_or_wave(sequence_description)

        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "",
                "logic_form": {"operation": "trend", "parameters": {"metric": "销售额", "dimension": "月份"}},
                "result": {
                    "columns": ["月份", "销售额"],
                    "rows": [{"月份": "2026-01", "销售额": 396}, {"月份": "2026-02", "销售额": 550}, {"月份": "2026-03", "销售额": 482}],
                },
            },
            question="按月份看销售额趋势？",
        )

        self.assertNotIn("整体上升", response["answer"])
        self.assertNotIn("单调上升", response["answer"])
        self.assertNotIn("持续上升", response["answer"])
        self.assert_has_peak_or_wave(response["answer"])

    def test_trend_summary_uses_full_sequence_when_no_period_field(self) -> None:
        response = apply_text_answer_framework(
            {
                "success": True,
                "answer_type": "table",
                "answer": "",
                "logic_form": {"operation": "trend", "parameters": {"metric": "销售额", "dimension": "时点"}},
                "result": {
                    "columns": ["时点", "销售额"],
                    "rows": [
                        {"时点": "2026-01", "销售额": 396},
                        {"时点": "2026-02", "销售额": 550},
                        {"时点": "2026-03", "销售额": 482},
                    ],
                },
            },
            question="该时点销售额趋势？",
        )
        self.assertIn("销售额", response["answer"])
        self.assertNotIn("整体上升", response["answer"])
        self.assertNotIn("单调上升", response["answer"])
        self.assertNotIn("持续上升", response["answer"])
        self.assert_has_peak_or_wave(response["answer"])

    def test_sequence_rising(self) -> None:
        description = describe_trend([100, 200, 300])
        self.assertIn("上升", description)

    def test_sequence_falling(self) -> None:
        description = describe_trend([300, 200, 100])
        self.assertIn("下降", description)

    def test_single_period_description(self) -> None:
        description = describe_trend([276])
        self.assertEqual("只有一个周期，无法判断趋势", description)
        self.assertIn("无法判断趋势", description)
        self.assertTrue(description.startswith("只有一个周期"))


if __name__ == "__main__":
    unittest.main()
