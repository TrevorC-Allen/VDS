from __future__ import annotations

from pathlib import Path
import unittest

from scripts.real_user_eval.manifest import load_manifest, validate_v1_coverage


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "configs" / "eval_gate" / "real_user_case_manifest_v1.json"


class RealUserManifestV1Test(unittest.TestCase):
    def test_manifest_meets_v1_acceptance_coverage(self) -> None:
        manifest = load_manifest(MANIFEST)

        summary = validate_v1_coverage(manifest)

        self.assertGreaterEqual(summary["dataset_count"], 6)
        self.assertGreaterEqual(summary["min_cases_per_dataset"], 8)
        self.assertGreaterEqual(summary["min_variants_per_case"], 5)
        self.assertGreaterEqual(summary["conversation_count"], 20)
        self.assertGreaterEqual(summary["min_turns_per_conversation"], 3)

    def test_manifest_keeps_answer_oracle_fields_out_of_questions(self) -> None:
        text = MANIFEST.read_text(encoding="utf-8").lower()

        self.assertNotIn("raw_prompt", text)
        self.assertNotIn("standard_answer", text)
        self.assertNotIn("task_id", text)

    def test_manifest_has_structured_p0_expected_contract_examples(self) -> None:
        manifest = load_manifest(MANIFEST)
        cases = {case["case_id"]: case for case in manifest["cases"]}
        conversations = {conversation["conversation_id"]: conversation for conversation in manifest["conversations"]}

        topn = cases["brazilian_ecommerce__top_state_orders"]["expected_contract"]
        self.assertEqual("topn", topn["contract_family"])
        self.assertEqual(10, topn["required_row_count"])
        self.assertTrue(topn["requires_direct_answer_first"])

        quality = cases["uk_retail__cancelled_orders"]["expected_contract"]
        self.assertEqual("data_quality", quality["contract_family"])
        self.assertTrue(quality["required_field_level_quality"])
        self.assertTrue(quality["required_duplicate_check"])
        self.assertTrue(quality["required_outlier_check"])

        overview = cases["brazilian_ecommerce__multi_file_keys"]["expected_contract"]
        self.assertEqual("multi_file_overview", overview["contract_family"])
        self.assertTrue(overview["required_all_files_covered"])
        self.assertIn("order_id", overview["required_join_keys"])

        turns = {turn["turn_id"]: turn for turn in conversations["brazilian_ecommerce_top_state_followup_contract"]["turns"]}
        referent = turns["turn_02"]["expected_contract"]
        self.assertEqual("followup_referent", referent["contract_family"])
        self.assertEqual("previous_top_set", referent["required_context_reference"])

        gap = turns["turn_03"]["expected_contract"]
        self.assertEqual("gap", gap["contract_family"])
        self.assertEqual("pairwise", gap["required_gap_type"])
        self.assertIn("gap_to_leader", gap["required_metrics"])


if __name__ == "__main__":
    unittest.main()
