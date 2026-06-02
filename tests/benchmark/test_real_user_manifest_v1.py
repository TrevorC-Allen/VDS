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


if __name__ == "__main__":
    unittest.main()
