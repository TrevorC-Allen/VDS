from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_agent_random_conversation_eval import (
    ScenarioResult,
    TurnEvidence,
    _coverage_summary,
    _report_markdown,
    write_eval_artifacts,
)
from scripts.eval_gate import EvalGateConfig, build_eval_gate_result, metrics_from_coverage


class EvalSemanticContractSummaryTest(unittest.TestCase):
    def _build_fake_result(self) -> ScenarioResult:
        turns = [
            TurnEvidence(
                index=1,
                question="哪个城市销售额最高？",
                expected_kind="analysis",
                capability_family="ranking",
                required_operation="ranking",
                success=True,
                answer_type="table",
                operation="ranking",
                conversation_id="conv-1",
                state_name="analysis_ready",
                semantic_status="passed",
                contract_satisfied=True,
                contract_family="topn",
                contract_checked=True,
                oracle_available=True,
                oracle_passed=True,
                contract_violation_codes=[],
            ),
            TurnEvidence(
                index=2,
                question="继续比较这些城市之间的差距。",
                expected_kind="followup_analysis",
                capability_family="ranking_followup",
                required_operation="ranking",
                success=True,
                answer_type="table",
                operation="ranking",
                conversation_id="conv-1",
                state_name="analysis_ready",
                semantic_status="failed",
                contract_satisfied=False,
                contract_family="gap",
                contract_checked=True,
                oracle_available=True,
                oracle_passed=False,
                oracle_issue_codes=["TOPN_RESULT_ROWS_SHORT"],
                contract_violation_codes=["TOPN_RESULT_ROWS_SHORT"],
                followup_reason="请比较差距",
            ),
            TurnEvidence(
                index=3,
                question="Top 结果要排除异常城市。",
                expected_kind="followup_analysis",
                capability_family="ranking_followup",
                required_operation="ranking",
                success=True,
                answer_type="table",
                operation="ranking",
                conversation_id="conv-1",
                state_name="analysis_ready",
                semantic_status="corrected_passed",
                contract_satisfied=True,
                contract_family="topn",
                contract_checked=True,
                oracle_available=False,
                oracle_passed=None,
                contract_violation_codes=[],
                followup_reason="修正口径后重新运行",
            ),
            TurnEvidence(
                index=4,
                question="这个口径能不能补一句总结。",
                expected_kind="followup_analysis",
                capability_family="analysis",
                required_operation="aggregation",
                success=True,
                answer_type="text",
                operation="aggregation",
                conversation_id="conv-1",
                state_name="analysis_ready",
                semantic_status="needs_clarification",
                contract_satisfied=False,
                contract_family="gap",
                contract_checked=False,
                oracle_available=False,
                oracle_passed=None,
                contract_violation_codes=[],
            ),
        ]
        return ScenarioResult(
            scenario_id="synthetic_contract_summary",
            capability_family="ranking",
            run_index=1,
            passed=True,
            simulator_source="mock",
            turns=turns,
            issues=[],
        )

    def test_coverage_counts_contract_and_oracle_layers(self) -> None:
        coverage = _coverage_summary([self._build_fake_result()])

        self.assertEqual(4, coverage["semantic_contract_turns"])
        self.assertEqual(2, coverage["oracle_result_turns"])
        self.assertEqual(3, coverage["contract_checked_turns"])
        self.assertEqual(2, coverage["contract_satisfied_turns"])
        self.assertEqual(2, coverage["semantic_passed_turns"])
        self.assertEqual(1, coverage["semantic_failed_turns"])
        self.assertEqual(1, coverage["corrected_passed_turns"])
        self.assertEqual(1, coverage["needs_clarification_turns"])

        top_codes = coverage["top_contract_violation_codes"]
        self.assertIsInstance(top_codes, list)
        self.assertEqual([{"code": "TOPN_RESULT_ROWS_SHORT", "count": 1}], top_codes)

    def test_report_output_includes_semantic_contract_summary_fields(self) -> None:
        report = {
            "passed": False,
            "pass_rate": 1.0,
            "conversation_count": 1,
            "scenario_count": 1,
            "runs_per_scenario": 1,
            "seed": 20260601,
            "simulator_source": "mock",
            "global_issues": [],
            "thresholds": {},
            "coverage": _coverage_summary([self._build_fake_result()]),
            "results": [],
        }
        report["gate_result"] = build_eval_gate_result(metrics_from_coverage(report["coverage"]), EvalGateConfig())
        report["gate_passed"] = report["gate_result"]["gate_passed"]
        report["gate_failed_reasons"] = report["gate_result"]["gate_failed_reasons"]

        markdown = _report_markdown(report)
        self.assertIn("## Coverage", markdown)
        self.assertIn("- Semantic contract turns: 4", markdown)
        self.assertIn("- Oracle result turns: 2", markdown)
        self.assertIn("- Contract checked turns: 3", markdown)
        self.assertIn("- Contract satisfied turns: 2", markdown)
        self.assertIn("- Semantic passed turns: 2", markdown)
        self.assertIn("- Semantic failed turns: 1", markdown)
        self.assertIn("- Corrected passed turns: 1", markdown)
        self.assertIn("- Needs clarification turns: 1", markdown)
        self.assertIn("- Top contract violation codes: TOPN_RESULT_ROWS_SHORT=1", markdown)
        self.assertIn("## Multi-metric Eval Gate", markdown)
        self.assertIn("- Gate passed: False", markdown)
        self.assertIn("semantic_failed_turns_above_threshold:1>0", markdown)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts = write_eval_artifacts(report, root)
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(str(root / "summary.json"), artifacts["summary_json"])
        self.assertEqual(4, summary["coverage"]["semantic_contract_turns"])
        self.assertEqual(2, summary["coverage"]["oracle_result_turns"])
        self.assertEqual(3, summary["coverage"]["contract_checked_turns"])
        self.assertEqual(2, summary["coverage"]["contract_satisfied_turns"])
        self.assertEqual(2, summary["coverage"]["semantic_passed_turns"])
        self.assertEqual(1, summary["coverage"]["semantic_failed_turns"])
        self.assertFalse(summary["gate_passed"])
        self.assertEqual(1, summary["coverage"]["corrected_passed_turns"])
        self.assertEqual(1, summary["coverage"]["needs_clarification_turns"])
