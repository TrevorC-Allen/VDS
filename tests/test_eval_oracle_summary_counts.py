from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_agent_random_conversation_eval import ScenarioResult, TurnEvidence, _coverage_summary, _report_html, _report_markdown


class EvalOracleSummaryCountsTest(unittest.TestCase):
    def _build_fake_result(self) -> ScenarioResult:
        return ScenarioResult(
            scenario_id="oracle_summary_counts",
            capability_family="ranking",
            run_index=1,
            passed=True,
            simulator_source="mock",
            issues=[],
            turns=[
                TurnEvidence(
                    index=1,
                    question="Turn 1",
                    expected_kind="analysis",
                    capability_family="ranking",
                    required_operation="ranking",
                    success=True,
                    answer_type="table",
                    operation="ranking",
                    conversation_id="conv_oracle_summary",
                    state_name="analysis_ready",
                    semantic_status="passed",
                    contract_satisfied=True,
                    contract_family="topn",
                    contract_checked=True,
                    oracle_available=True,
                    oracle_passed=True,
                    expected_result={"rows": [{"city": "广州"}]},
                    actual_result={"rows": [{"city": "广州"}]},
                ),
                TurnEvidence(
                    index=2,
                    question="Turn 2",
                    expected_kind="analysis",
                    capability_family="ranking",
                    required_operation="ranking",
                    success=True,
                    answer_type="table",
                    operation="ranking",
                    conversation_id="conv_oracle_summary",
                    state_name="analysis_ready",
                    semantic_status="failed",
                    contract_satisfied=False,
                    contract_family="topn",
                    contract_checked=True,
                    oracle_available=True,
                    oracle_passed=False,
                    expected_result={"rows": [{"city": "深圳"}]},
                    actual_result={"rows": [{"city": "北京"}]},
                    oracle_issue_codes=["TOPN_RESULT_ROWS_SHORT"],
                ),
                TurnEvidence(
                    index=3,
                    question="Turn 3",
                    expected_kind="analysis",
                    capability_family="ranking",
                    required_operation="ranking",
                    success=True,
                    answer_type="table",
                    operation="ranking",
                    conversation_id="conv_oracle_summary",
                    state_name="analysis_ready",
                    semantic_status="needs_clarification",
                    contract_satisfied=False,
                    contract_family="topn",
                    contract_checked=False,
                    oracle_available=False,
                    oracle_passed=None,
                    expected_result=None,
                    actual_result={"rows": [{"city": "杭州"}]},
                    oracle_issue_codes=["oracle_expected_result_missing"],
                ),
                TurnEvidence(
                    index=4,
                    question="Turn 4",
                    expected_kind="analysis",
                    capability_family="ranking",
                    required_operation="ranking",
                    success=True,
                    answer_type="table",
                    operation="ranking",
                    conversation_id="conv_oracle_summary",
                    state_name="analysis_ready",
                    semantic_status="needs_clarification",
                    contract_satisfied=False,
                    contract_family="topn",
                    contract_checked=False,
                    oracle_available=False,
                    oracle_passed=None,
                    expected_result={"rows": [{"city": "上海"}]},
                    actual_result=None,
                    oracle_issue_codes=["oracle_actual_result_missing"],
                ),
            ],
        )

    def test_oracle_summary_counts_distinguish_pass_fail_and_missing(self) -> None:
        result = self._build_fake_result()
        coverage = _coverage_summary([result])

        self.assertEqual(4, coverage["oracle_result_turns"])
        self.assertEqual(1, coverage["oracle_passed"])
        self.assertEqual(1, coverage["oracle_failed"])
        self.assertEqual(1, coverage["oracle_expected_missing"])
        self.assertEqual(1, coverage["oracle_actual_missing"])
        self.assertEqual(2, coverage["oracle_passed_turns"] + coverage["oracle_failed_turns"])

    def test_report_markdown_and_html_show_oracle_summary_fields(self) -> None:
        result = self._build_fake_result()
        report = {
            "passed": True,
            "pass_rate": 1.0,
            "scenario_count": 1,
            "conversation_count": 1,
            "runs_per_scenario": 1,
            "seed": 20260601,
            "simulator_source": "mock",
            "global_issues": [],
            "thresholds": {},
            "coverage": _coverage_summary([result]),
            "results": [
                {
                    **result.__dict__,
                    "turns": [turn.__dict__ for turn in result.turns],
                }
            ],
        }

        markdown = _report_markdown(report)
        html = _report_html(report)

        self.assertIn("- Oracle passed: 1", markdown)
        self.assertIn("- Oracle failed: 1", markdown)
        self.assertIn("- Oracle expected missing: 1", markdown)
        self.assertIn("- Oracle actual missing: 1", markdown)
        self.assertIn("Oracle passed</div>", html)
        self.assertIn("Oracle failed</div>", html)
        self.assertIn("Oracle expected missing</div>", html)
        self.assertIn("Oracle actual missing</div>", html)


if __name__ == "__main__":
    unittest.main()
