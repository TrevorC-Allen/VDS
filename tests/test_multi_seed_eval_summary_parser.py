from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_agent_random_conversation_eval_multi_seed import (
    _collect_seed_summary,
    _normalize_top_violation_codes,
    _parse_seeds,
)


class MultiSeedEvalSummaryParserTest(unittest.TestCase):
    def test_parse_seeds_from_csv_string(self) -> None:
        self.assertEqual([20260603, 20260604, 20260605], _parse_seeds("20260603,20260604,20260605"))
        self.assertEqual([20260603, 20260605], _parse_seeds("20260603,  ,20260605"))

    def test_collect_seed_summary_prefers_coverage_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "seed_20260603"
            summary_path = output_dir / "summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "pass_rate": 0.6667,
                        "coverage": {
                            "turn_count": 12,
                            "contract_checked_turns": 4,
                            "contract_satisfied_turns": 3,
                            "semantic_passed_turns": 5,
                            "semantic_failed_turns": 1,
                            "oracle_result_turns": 8,
                            "oracle_passed_turns": 2,
                            "oracle_failed_turns": 3,
                            "oracle_expected_result_missing_turns": 1,
                            "oracle_actual_result_missing_turns": 2,
                            "top_contract_violation_codes": [
                                {"code": "TOPN_RESULT_ROWS_SHORT", "count": 3},
                                {"code": "TABLE_DIMENSION_MISSING", "count": 1},
                            ],
                        },
                        "llm_judge_failed_turns": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            row = _collect_seed_summary(seed=20260603, output_dir=output_dir, summary_path=summary_path)

        self.assertEqual(20260603, row["seed"])
        self.assertEqual(0.6667, row["pass_rate"])
        self.assertEqual(12, row["total_turns"])
        self.assertEqual(4, row["contract_checked_turns"])
        self.assertEqual(3, row["contract_satisfied_turns"])
        self.assertEqual(5, row["semantic_passed_turns"])
        self.assertEqual(1, row["semantic_failed_turns"])
        self.assertEqual(8, row["oracle_result_turns"])
        self.assertEqual(2, row["oracle_passed"])
        self.assertEqual(3, row["oracle_failed"])
        self.assertEqual(1, row["oracle_expected_missing"])
        self.assertEqual(2, row["oracle_actual_missing"])
        self.assertEqual(0, row["llm_judge_failed_turns"])
        self.assertEqual(
            [{"code": "TOPN_RESULT_ROWS_SHORT", "count": 3}, {"code": "TABLE_DIMENSION_MISSING", "count": 1}],
            row["top_violation_codes"],
        )
        self.assertIn("seed_20260603", row["output_dir"])

    def test_collect_seed_summary_fallbacks_when_top_codes_and_aliases_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary_path = root / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "pass_rate": 0.5,
                        "coverage": {
                            "turn_count": 9,
                            "oracle_passed": 1,
                            "oracle_failed": 0,
                            "oracle_expected_missing": 2,
                            "oracle_actual_missing": 3,
                            "top_contract_violation_codes": [{"code": "SEMANTIC_MISMATCH", "count": 2}],
                            "llm_judge_failed_turns": 4,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            row = _collect_seed_summary(seed=20260604, summary_path=summary_path)

        self.assertEqual(0.5, row["pass_rate"])
        self.assertEqual(9, row["total_turns"])
        self.assertEqual(1, row["oracle_passed"])
        self.assertEqual(0, row["oracle_failed"])
        self.assertEqual(2, row["oracle_expected_missing"])
        self.assertEqual(3, row["oracle_actual_missing"])
        self.assertEqual(4, row["llm_judge_failed_turns"])
        self.assertEqual([{"code": "SEMANTIC_MISMATCH", "count": 2}], row["top_violation_codes"])
        self.assertEqual(str(summary_path.parent), row["output_dir"])


class NormalizeViolationCodesTest(unittest.TestCase):
    def test_normalize_violation_codes_accepts_dicts_and_strings(self) -> None:
        raw_codes = [
            {"code": "TOPN_RESULT_ROWS_SHORT", "count": 3},
            "TABLE_DIMENSION_MISSING",
            {"count": 2},
            123,
        ]
        normalized = _normalize_top_violation_codes(raw_codes)
        self.assertEqual(
            [
                {"code": "TOPN_RESULT_ROWS_SHORT", "count": 3},
                {"code": "TABLE_DIMENSION_MISSING", "count": 1},
            ],
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
