from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.eval_gate import EvalGateConfig
from scripts.eval_report import (
    build_pr_eval_summary,
    write_pr_eval_summary,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


class EvalPrSummaryTest(unittest.TestCase):
    def test_random_input_all_pass_and_generates_markdown_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "summary.json",
                {
                    "case_count": 2,
                    "pass_rate": 1.0,
                    "conversation_count": 2,
                    "coverage": {
                        "turn_count": 2,
                        "transport_success_turns": 2,
                        "semantic_contract_turns": 2,
                        "contract_checked_turns": 2,
                        "contract_satisfied_turns": 2,
                        "semantic_passed_turns": 2,
                        "semantic_failed_turns": 0,
                        "legacy_unverified_turns": 0,
                        "oracle_available_turns": 2,
                        "oracle_passed_turns": 2,
                        "oracle_failed_turns": 0,
                        "llm_judge_failed_turns": 0,
                    },
                    "results": [
                        {
                            "scenario_id": "topn_case",
                            "turns": [
                                {
                                    "case_id": "case_a",
                                    "index": 1,
                                    "question": "问法1",
                                    "scenario_family": "single_file_overview_topn_gap",
                                    "capability_family": "topn",
                                    "semantic_status": "passed",
                                    "contract_violation_codes": ["TOPN_RESULT_ROWS_SHORT"],
                                    "oracle_passed": True,
                                },
                                {
                                    "case_id": "case_a",
                                    "index": 2,
                                    "question": "问法2",
                                    "scenario_family": "single_file_overview_topn_gap",
                                    "capability_family": "topn",
                                    "semantic_status": "passed",
                                    "contract_violation_codes": [],
                                    "oracle_passed": True,
                                },
                            ],
                        }
                    ],
                },
            )

            report = build_pr_eval_summary(output_dir)
            paths = write_pr_eval_summary(output_dir, report)
            json_payload = json.loads((output_dir / "pr_eval_summary.json").read_text(encoding="utf-8"))
            markdown = (output_dir / "pr_eval_summary.md").read_text(encoding="utf-8")

            self.assertEqual("random_agent", report["eval_type"])
            self.assertTrue(report["gate_result"]["gate_passed"])
            self.assertFalse(report["evidence_coverage"]["semantic_evidence_missing_turns"])
            self.assertEqual("available", report["family_summary"]["status"])
            self.assertTrue(json_payload["family_summary"]["families"])
            self.assertEqual("single_file_overview_topn_gap", json_payload["family_summary"]["families"][0]["family"])
            self.assertIn("Gate Result", markdown)
            self.assertIn("Eval Summary", markdown)
            self.assertIn("# Scenario Family Summary", markdown)
            self.assertTrue(Path(paths["pr_eval_summary_json"]).exists())
            self.assertTrue(Path(paths["pr_eval_summary_md"]).exists())

    def test_random_input_required_scenario_family_missing_is_gate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "summary.json",
                {
                    "pass_rate": 1.0,
                    "coverage": {
                        "turn_count": 1,
                        "transport_success_turns": 1,
                        "semantic_contract_turns": 1,
                        "semantic_passed_turns": 1,
                        "semantic_failed_turns": 0,
                        "legacy_unverified_turns": 0,
                        "oracle_available_turns": 1,
                        "oracle_passed_turns": 1,
                        "scenario_families": ["single_file_overview_topn_gap"],
                    },
                    "results": [
                        {
                            "scenario_id": "scenario",
                            "scenario_family": "single_file_overview_topn_gap",
                            "turns": [
                                {
                                    "case_id": "case_a",
                                    "index": 1,
                                    "scenario_family": "single_file_overview_topn_gap",
                                    "semantic_status": "passed",
                                    "oracle_passed": True,
                                }
                            ],
                        }
                    ],
                },
            )

            report = build_pr_eval_summary(
                output_dir,
                gate_config=EvalGateConfig(required_families=("multi_file_overview_join_analysis",)),
            )

        self.assertFalse(report["gate_result"]["gate_passed"])
        self.assertIn("missing_required_family:multi_file_overview_join_analysis", report["gate_result"]["gate_failed_reasons"])

    def test_random_input_semantic_failed_is_gate_fail_even_when_pass_rate_1(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "summary.json",
                {
                    "pass_rate": 1.0,
                    "coverage": {
                        "turn_count": 2,
                        "transport_success_turns": 2,
                        "semantic_contract_turns": 2,
                        "semantic_passed_turns": 1,
                        "semantic_failed_turns": 1,
                        "legacy_unverified_turns": 0,
                        "oracle_available_turns": 2,
                        "oracle_passed_turns": 2,
                        "oracle_failed_turns": 0,
                    },
                    "results": [
                        {
                            "scenario_id": "scenario",
                            "turns": [
                                {"case_id": "case_a", "index": 1, "semantic_status": "passed", "capability_family": "topn"},
                                {"case_id": "case_a", "index": 2, "semantic_status": "failed", "capability_family": "topn"},
                            ],
                        }
                    ],
                },
            )
            report = build_pr_eval_summary(output_dir)

            self.assertFalse(report["gate_result"]["gate_passed"])
            self.assertIn("semantic_failed_turns_above_threshold:1>0", report["gate_result"]["gate_failed_reasons"])
            self.assertEqual(1, report["eval_summary"]["semantic_failed_turns"])

    def test_random_input_oracle_failed_is_gate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "summary.json",
                {
                    "pass_rate": 1.0,
                    "coverage": {
                        "turn_count": 2,
                        "transport_success_turns": 2,
                        "semantic_contract_turns": 2,
                        "semantic_passed_turns": 2,
                        "semantic_failed_turns": 0,
                        "legacy_unverified_turns": 0,
                        "oracle_available_turns": 2,
                        "oracle_passed_turns": 1,
                        "oracle_failed_turns": 1,
                    },
                    "results": [
                        {
                            "scenario_id": "scenario",
                            "turns": [
                                {"case_id": "case_a", "index": 1, "semantic_status": "passed", "oracle_passed": True, "capability_family": "topn"},
                                {"case_id": "case_b", "index": 2, "semantic_status": "passed", "oracle_passed": False, "capability_family": "topn"},
                            ],
                        }
                    ],
                },
            )
            report = build_pr_eval_summary(output_dir)

            self.assertFalse(report["gate_result"]["gate_passed"])
            self.assertIn("oracle_failed_turns_above_threshold:1>0", report["gate_result"]["gate_failed_reasons"])

    def test_random_input_legacy_unverified_rate_too_high_is_gate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "summary.json",
                {
                    "pass_rate": 1.0,
                    "coverage": {
                        "turn_count": 5,
                        "transport_success_turns": 5,
                        "semantic_contract_turns": 5,
                        "semantic_passed_turns": 3,
                        "semantic_failed_turns": 0,
                        "legacy_unverified_turns": 3,
                        "oracle_available_turns": 2,
                        "oracle_passed_turns": 2,
                        "oracle_failed_turns": 0,
                    },
                    "results": [
                        {
                            "scenario_id": "scenario",
                            "turns": [
                                {"case_id": f"case_{index}", "index": index, "semantic_status": "not_available", "capability_family": "topn"}
                                for index in range(1, 6)
                            ],
                        }
                    ],
                },
            )
            report = build_pr_eval_summary(output_dir)

            self.assertFalse(report["gate_result"]["gate_passed"])
            self.assertIn("legacy_unverified_rate_above_threshold:", report["gate_result"]["gate_failed_reasons"][0])
            self.assertEqual(5, report["evidence_coverage"]["legacy_unverified_turns"])

    def test_random_input_missing_family_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "summary.json",
                {
                    "pass_rate": 0.5,
                    "coverage": {
                        "turn_count": 1,
                        "transport_success_turns": 1,
                        "semantic_contract_turns": 0,
                        "semantic_passed_turns": 0,
                        "semantic_failed_turns": 1,
                        "legacy_unverified_turns": 1,
                    },
                    "results": [
                        {
                            "scenario_id": "scenario",
                            "turns": [
                                {"case_id": "case_no_family", "index": 1, "semantic_status": "failed", "oracle_passed": True},
                            ],
                        }
                    ],
                },
            )
            report = build_pr_eval_summary(output_dir)

            self.assertEqual("not_available", report["family_summary"]["status"])

    def test_real_user_input_missing_oracle_fields_and_has_top_violation_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_jsonl(
                output_dir / "comparison_scored.jsonl",
                [
                    {
                        "case_id": "case_oracle_missing",
                        "llm_judge_passed": True,
                        "answers": {"candidate": {"answer": "ans"}},
                    }
                ],
            )
            _write_json(
                output_dir / "summary.json",
                {
                    "case_count": 1,
                    "pass_rate": 1.0,
                    "transport_success_turns": 1,
                    "service_success_turns": 1,
                    "comparison": [
                        {
                            "case_id": "case_oracle_missing",
                            "turn_id": "1",
                            "question": "问题",
                            "semantic_status": "not_available",
                            "semantic_passed": False,
                            "violation_codes": ["SEMANTIC_MISMATCH"],
                        }
                    ],
                    "llm_judge_passed": 1,
                },
            )
            report = build_pr_eval_summary(output_dir)

            self.assertEqual("real_user", report["eval_type"])
            self.assertEqual("not_available", report["family_summary"]["status"])
            self.assertEqual([], report["evidence_coverage"]["missing_evidence_reason"])
            self.assertEqual(1, report["evidence_coverage"]["semantic_evidence_missing_turns"])
            self.assertEqual(1, report["evidence_coverage"]["oracle_evidence_missing_turns"])
            self.assertEqual([{"code": "SEMANTIC_MISMATCH", "count": 1, "example_case_ids": ["case_oracle_missing"], "example_turn_ids": ["1"]}], report["top_violation_codes"])

    def test_real_user_expected_contract_evidence_is_reported_and_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_jsonl(
                output_dir / "comparison_scored.jsonl",
                [
                    {
                        "case_id": "case_expected_contract_missing",
                        "llm_judge_passed": True,
                        "answers": {"candidate": {"answer": "ans"}},
                    }
                ],
            )
            _write_json(
                output_dir / "summary.json",
                {
                    "case_count": 1,
                    "transport_success_turns": 1,
                    "service_success_turns": 1,
                    "semantic_checked_turns": 1,
                    "semantic_passed_turns": 1,
                    "oracle_available_turns": 1,
                    "oracle_passed_turns": 1,
                    "contract_satisfied_turns": 1,
                    "expected_contract_checked_turns": 1,
                    "expected_contract_passed_turns": 0,
                    "expected_contract_failed_turns": 1,
                    "expected_contract_missing_evidence_turns": 1,
                    "expected_contract_issue_codes": {"EXPECTED_GAP_EVIDENCE_MISSING": 1},
                    "comparison": [
                        {
                            "case_id": "case_expected_contract_missing",
                            "turn_id": "1",
                            "question": "差距如何？",
                            "capability_family": "gap",
                            "semantic_status": "passed",
                            "semantic_passed": True,
                            "contract_satisfied": True,
                            "oracle_available": True,
                            "oracle_passed": True,
                            "expected_contract_check": {
                                "checked": True,
                                "passed": False,
                                "issue_codes": ["EXPECTED_GAP_EVIDENCE_MISSING"],
                                "missing_evidence": ["gap_evidence"],
                                "details": {},
                            },
                            "expected_contract_issue_codes": ["EXPECTED_GAP_EVIDENCE_MISSING"],
                            "expected_contract_missing_evidence": ["gap_evidence"],
                        }
                    ],
                },
            )

            report = build_pr_eval_summary(output_dir)
            write_pr_eval_summary(output_dir, report)
            markdown = (output_dir / "pr_eval_summary.md").read_text(encoding="utf-8")

            self.assertFalse(report["gate_result"]["gate_passed"])
            self.assertIn("expected_contract_failed_turns_above_threshold:1>0", report["gate_result"]["gate_failed_reasons"])
            self.assertEqual(1, report["eval_summary"]["expected_contract_checked_turns"])
            self.assertEqual(1, report["eval_summary"]["expected_contract_failed_turns"])
            self.assertEqual(1, report["evidence_coverage"]["expected_contract_missing_evidence_turns"])
            self.assertEqual("EXPECTED_GAP_EVIDENCE_MISSING", report["top_violation_codes"][0]["code"])
            self.assertIn("expected_contract_failed_turns", markdown)

    def test_random_input_insufficient_data_pass_is_not_failed_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "summary.json",
                {
                    "pass_rate": 1.0,
                    "coverage": {
                        "turn_count": 1,
                        "transport_success_turns": 1,
                        "semantic_contract_turns": 1,
                        "semantic_passed_turns": 1,
                        "semantic_failed_turns": 0,
                        "legacy_unverified_turns": 0,
                        "oracle_available_turns": 1,
                        "oracle_passed_turns": 1,
                        "oracle_failed_turns": 0,
                    },
                    "results": [
                        {
                            "scenario_id": "topn_insufficient_case",
                            "scenario_family": "typical",
                            "turns": [
                                {
                                    "index": 1,
                                    "question": "按城市看金额排名前 5。",
                                    "semantic_status": "passed_with_insufficient_data",
                                    "contract_satisfied": True,
                                    "oracle_available": True,
                                    "oracle_passed": True,
                                    "capability_family": "multi_table_join_ranking",
                                    "scenario_family": "typical",
                                }
                            ],
                        }
                    ],
                },
            )

            report = build_pr_eval_summary(output_dir)

            self.assertTrue(report["gate_result"]["gate_passed"])
            self.assertEqual([], report["failed_cases"])
            self.assertEqual(1.0, report["family_summary"]["families"][0]["semantic_pass_rate"])

    def test_multi_seed_input_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            _write_json(
                output_dir / "multi_seed_summary.json",
                {
                    "count": 1,
                    "families_run": ["single_file_overview_topn_gap"],
                    "per_family_pass_rate": {"single_file_overview_topn_gap": 1.0},
                    "per_family_semantic_pass_rate": {"single_file_overview_topn_gap": 1.0},
                    "per_family_oracle_pass_rate": {"single_file_overview_topn_gap": 1.0},
                    "per_family_expected_contract_pass_rate": {"single_file_overview_topn_gap": "not_available"},
                    "top_violation_codes_by_family": {
                        "single_file_overview_topn_gap": [{"code": "TOPN_RESULT_ROWS_SHORT", "count": 2}]
                    },
                    "rows": [
                        {
                            "seed": 20260603,
                            "gate_passed": True,
                            "pass_rate": 1.0,
                            "total_turns": 2,
                            "transport_success_turns": 2,
                            "semantic_contract_turns": 2,
                            "semantic_passed_turns": 2,
                            "semantic_failed_turns": 0,
                            "legacy_unverified_turns": 0,
                            "oracle_available_turns": 2,
                            "oracle_passed": 2,
                            "oracle_failed": 0,
                            "top_violation_codes": [{"code": "TOPN_RESULT_ROWS_SHORT", "count": 2}],
                            "scenario_families": ["single_file_overview_topn_gap"],
                        }
                    ],
                },
            )
            report = build_pr_eval_summary(output_dir)

            self.assertEqual("multi_seed_random_agent", report["eval_type"])
            self.assertTrue(report["gate_result"]["gate_passed"])
            self.assertEqual([], report["failed_cases"])
            self.assertEqual("available", report["family_summary"]["status"])
            self.assertEqual("single_file_overview_topn_gap", report["family_summary"]["families"][0]["family"])


if __name__ == "__main__":
    unittest.main()
