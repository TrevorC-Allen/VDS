from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.run_agent_random_conversation_eval import _report_html, _turn_markdown_lines, _write_turn_records_csv


class EvalViolationFieldCompatTest(unittest.TestCase):
    def _build_failed_report(self) -> dict[str, object]:
        return {
            "passed": False,
            "pass_rate": 0.0,
            "conversation_count": 1,
            "scenario_count": 1,
            "runs_per_scenario": 1,
            "seed": 20260601,
            "simulator_source": "mock",
            "name": "agent_random_conversation_eval",
            "global_issues": ["unit-test-compat"],
            "thresholds": {"min_pass_rate": 1.0},
            "coverage": {
                "turn_count": 1,
                "contextualized_post_initial_turns": 0,
                "semantic_contract_turns": 1,
                "contract_checked_turns": 1,
                "contract_satisfied_turns": 0,
                "semantic_passed_turns": 0,
                "semantic_failed_turns": 1,
            },
            "results": [
                {
                    "scenario_id": "synthetic_violation_case",
                    "run_index": 1,
                    "passed": False,
                    "capability_family": "ranking",
                    "issues": [],
                    "turns": [
                        {
                            "index": 1,
                            "question": "TOP10 里哪个城市销售额最高？",
                            "expected_kind": "analysis",
                            "capability_family": "ranking",
                            "required_operation": "ranking",
                            "operation": "ranking",
                            "success": True,
                            "answer_type": "table",
                            "turn_role": "初始问题",
                            "conversation_turn": True,
                            "semantic_status": "failed",
                            "contract_satisfied": False,
                            "contract_family": "topn",
                            "contract_checked": True,
                            "contract_violation_codes": ["TOPN_RESULT_ROWS_SHORT"],
                            "oracle_available": True,
                            "oracle_passed": False,
                            "oracle_issue_codes": ["TOPN_RESULT_ROWS_SHORT"],
                            "context_status": "新会话入口",
                            "followup_reason": "测试失败样本",
                            "action_count": 0,
                            "section_count": 1,
                            "answer_preview": "",
                            "next_action_questions": [],
                        }
                    ],
                }
            ],
        }

    def test_turn_records_contains_violations_alias_with_failed_turn(self) -> None:
        report = self._build_failed_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "turn_records.csv"
            _write_turn_records_csv(report, path)

            rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertIn("contract_violation_codes", row)
        self.assertIn("violations", row)
        self.assertEqual("TOPN_RESULT_ROWS_SHORT", row["contract_violation_codes"])
        self.assertEqual("TOPN_RESULT_ROWS_SHORT", row["violations"])
        self.assertEqual("failed", row["semantic_status"])
        self.assertEqual("False", row["contract_satisfied"])
        self.assertNotEqual("passed", row["semantic_status"])

    def test_failed_turn_is_rendered_as_failed_in_report_markdown_and_html(self) -> None:
        report = self._build_failed_report()
        turn = report["results"][0]["turns"][0]  # type: ignore[index]

        markdown = "\n".join(_turn_markdown_lines(turn))
        self.assertIn("status=failed", markdown)
        self.assertIn("contract_satisfied=False", markdown)
        self.assertNotIn("status=passed", markdown)
        self.assertNotIn("solved", markdown.lower())

        html = _report_html(report)
        self.assertIn("semantic=failed", html)
        self.assertIn('chip fail">semantic=failed', html)
        self.assertNotIn("solved answer", html.lower())


if __name__ == "__main__":
    unittest.main()
