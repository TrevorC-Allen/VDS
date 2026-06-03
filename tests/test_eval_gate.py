from __future__ import annotations

import unittest

from scripts.eval_gate import EvalGateConfig, EvalGateMetrics, build_eval_gate_result, metrics_from_coverage


class EvalGateTest(unittest.TestCase):
    def test_pass_rate_one_but_semantic_failed_turns_fails_gate(self) -> None:
        result = build_eval_gate_result(
            EvalGateMetrics(
                total_turns=10,
                transport_success_turns=10,
                semantic_contract_turns=10,
                semantic_passed_turns=9,
                semantic_failed_turns=1,
                oracle_available_turns=10,
                oracle_passed_turns=10,
                contract_satisfied_turns=9,
            )
        )

        self.assertFalse(result["gate_passed"])
        self.assertIn("semantic_failed_turns_above_threshold:1>0", result["gate_failed_reasons"])

    def test_pass_rate_one_but_legacy_unverified_rate_too_high_fails_gate(self) -> None:
        result = build_eval_gate_result(
            EvalGateMetrics(
                total_turns=10,
                transport_success_turns=10,
                semantic_contract_turns=6,
                semantic_passed_turns=6,
                oracle_available_turns=6,
                oracle_passed_turns=6,
                contract_satisfied_turns=6,
                legacy_unverified_turns=4,
            ),
            EvalGateConfig(max_legacy_unverified_rate=0.2),
        )

        self.assertFalse(result["gate_passed"])
        self.assertIn("legacy_unverified_rate_above_threshold:0.4000>0.2000", result["gate_failed_reasons"])

    def test_oracle_failed_turns_fail_gate(self) -> None:
        result = build_eval_gate_result(
            EvalGateMetrics(
                total_turns=3,
                transport_success_turns=3,
                semantic_contract_turns=3,
                semantic_passed_turns=3,
                oracle_available_turns=3,
                oracle_passed_turns=2,
                oracle_failed_turns=1,
                contract_satisfied_turns=3,
            )
        )

        self.assertFalse(result["gate_passed"])
        self.assertIn("oracle_failed_turns_above_threshold:1>0", result["gate_failed_reasons"])

    def test_expected_contract_failed_turns_fail_gate(self) -> None:
        result = build_eval_gate_result(
            EvalGateMetrics(
                total_turns=2,
                transport_success_turns=2,
                semantic_contract_turns=2,
                semantic_passed_turns=2,
                oracle_available_turns=2,
                oracle_passed_turns=2,
                contract_satisfied_turns=2,
                expected_contract_checked_turns=2,
                expected_contract_passed_turns=1,
                expected_contract_failed_turns=1,
                expected_contract_missing_evidence_turns=1,
                expected_contract_issue_codes=({"code": "EXPECTED_GAP_EVIDENCE_MISSING", "count": 1},),
            )
        )

        self.assertFalse(result["gate_passed"])
        self.assertIn("expected_contract_failed_turns_above_threshold:1>0", result["gate_failed_reasons"])
        self.assertEqual(0.5, result["expected_contract_pass_rate"])
        self.assertEqual(1, result["expected_contract_missing_evidence_turns"])
        self.assertEqual([{"code": "EXPECTED_GAP_EVIDENCE_MISSING", "count": 1}], result["expected_contract_issue_codes"])

    def test_all_metrics_pass_with_required_family_coverage(self) -> None:
        result = build_eval_gate_result(
            EvalGateMetrics(
                total_turns=4,
                transport_success_turns=4,
                semantic_contract_turns=4,
                semantic_passed_turns=4,
                oracle_available_turns=4,
                oracle_passed_turns=4,
                contract_satisfied_turns=4,
                covered_families=("topn", "gap"),
            ),
            EvalGateConfig(required_families=("topn", "gap")),
        )

        self.assertTrue(result["gate_passed"])
        self.assertEqual([], result["gate_failed_reasons"])
        self.assertEqual(1.0, result["semantic_pass_rate"])
        self.assertTrue(result["family_coverage"]["passed"])

    def test_missing_fields_are_not_available_and_do_not_crash(self) -> None:
        result = build_eval_gate_result(EvalGateMetrics())

        self.assertFalse(result["gate_passed"])
        self.assertEqual("not_available", result["transport_pass_rate"])
        self.assertEqual("not_available", result["semantic_pass_rate"])
        self.assertEqual("not_available", result["oracle_pass_rate"])
        self.assertIn("no_turns_available", result["gate_failed_reasons"])

    def test_legacy_summary_without_semantic_counters_is_unverified(self) -> None:
        result = build_eval_gate_result(metrics_from_coverage({"turn_count": 5}))

        self.assertFalse(result["gate_passed"])
        self.assertEqual("not_available", result["semantic_pass_rate"])
        self.assertEqual(1.0, result["legacy_unverified_rate"])
        self.assertIn("legacy_unverified_rate_above_threshold:1.0000>0.2000", result["gate_failed_reasons"])


if __name__ == "__main__":
    unittest.main()
