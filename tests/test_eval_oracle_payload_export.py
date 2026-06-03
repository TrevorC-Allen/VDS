from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_agent_random_conversation_eval import (
    ScenarioResult,
    TurnEvidence,
    _coverage_summary,
    write_eval_artifacts,
)


class EvalOraclePayloadExportTest(unittest.TestCase):
    def _build_report(self, *, oracle_available: bool, expected_result, actual_result, oracle_issue_codes: list[str]) -> dict[str, object]:
        turn = TurnEvidence(
            index=1,
            question="哪个城市销售额最高？",
            expected_kind="analysis",
            capability_family="ranking",
            required_operation="ranking",
            success=True,
            answer_type="table",
            operation="ranking",
            conversation_id="conv_oracle_payload",
            state_name="analysis_ready",
            semantic_status="passed",
            contract_satisfied=True,
            contract_family="topn",
            contract_checked=True,
            oracle_available=oracle_available,
            oracle_passed=True if oracle_available and expected_result is not None else None,
            oracle_issue_codes=list(oracle_issue_codes),
            expected_result=expected_result,
            actual_result=actual_result,
            answer_preview="mocked answer",
        )
        result = ScenarioResult(
            scenario_id="oracle_payload_scenario",
            capability_family="ranking",
            run_index=1,
            passed=True,
            simulator_source="mock",
            turns=[turn],
            issues=[],
        )
        coverage = _coverage_summary([result])
        return {
            "passed": True,
            "pass_rate": 1.0,
            "passed_count": 1,
            "name": "agent_random_conversation_eval",
            "seed": 20260601,
            "scenario_count": 1,
            "conversation_count": 1,
            "runs_per_scenario": 1,
            "global_issues": [],
            "thresholds": {},
            "coverage": coverage,
            "results": [
                {
                    **result.__dict__,
                    "turns": [turn.__dict__],
                }
            ],
        }

    def _read_jsonl_turns(self, path: Path) -> list[dict[str, object]]:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows.extend(row.get("turns") or [])
        return rows

    def test_case1_full_expected_and_actual_payload_is_exported(self) -> None:
        report = self._build_report(
            oracle_available=True,
            expected_result={"rows": [{"city": "深圳", "sales": 586}]},
            actual_result={"rows": [{"city": "深圳", "sales": 586}]},
            oracle_issue_codes=[],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            artifacts = write_eval_artifacts(report, output)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            turn_rows = list(csv.DictReader((output / "turn_records.csv").open(encoding="utf-8", newline="")) )
            conversation_turns = self._read_jsonl_turns(output / "conversation_records.jsonl")

        self.assertEqual(1, len(turn_rows))
        self.assertEqual("True", turn_rows[0]["expected_result_present"])
        self.assertEqual("True", turn_rows[0]["actual_result_present"])
        self.assertEqual(1, summary["coverage"]["oracle_expected_result_present_turns"])
        self.assertEqual(1, summary["coverage"]["oracle_actual_result_present_turns"])
        self.assertEqual(0, summary["coverage"]["oracle_expected_result_missing_turns"])
        self.assertEqual(0, summary["coverage"]["oracle_actual_result_missing_turns"])

        self.assertEqual(1, len(conversation_turns))
        self.assertEqual({"rows": [{"city": "深圳", "sales": 586}]}, conversation_turns[0]["expected_result"])
        self.assertEqual({"rows": [{"city": "深圳", "sales": 586}]}, conversation_turns[0]["actual_result"])
        self.assertEqual(artifacts["summary_json"], str(output / "summary.json"))

    def test_case2_missing_expected_result_keeps_null_and_updates_missing_stats(self) -> None:
        report = self._build_report(
            oracle_available=False,
            expected_result=None,
            actual_result={"rows": [{"city": "深圳", "sales": 586}]},
            oracle_issue_codes=["oracle_expected_result_missing"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_eval_artifacts(report, output)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            turn_rows = list(csv.DictReader((output / "turn_records.csv").open(encoding="utf-8", newline="")) )
            conversation_turns = self._read_jsonl_turns(output / "conversation_records.jsonl")

        self.assertEqual(1, len(turn_rows))
        self.assertEqual("False", turn_rows[0]["expected_result_present"])
        self.assertEqual("True", turn_rows[0]["actual_result_present"])
        self.assertEqual(1, summary["coverage"]["oracle_expected_result_missing_turns"])
        self.assertEqual(0, summary["coverage"]["oracle_expected_result_present_turns"])
        self.assertIn("oracle_expected_result_missing", turn_rows[0]["oracle_issue_codes"])
        self.assertIsNone(conversation_turns[0]["expected_result"])
        self.assertNotEqual(True, summary["coverage"]["oracle_passed_turns"])


if __name__ == "__main__":
    unittest.main()
