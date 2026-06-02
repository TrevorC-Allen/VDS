from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any
import unittest

from scripts.real_user_eval.manifest import load_manifest, validate_manifest
from scripts.real_user_eval.oracle import evaluate_oracle
from scripts.real_user_eval.runner import run_manifest
from scripts.real_user_eval.targets import AgentResult, TargetRequest
from scripts.score_comparison_answers import load_comparison_rows


class FakeTarget:
    target_name = "fake"

    def __init__(self) -> None:
        self.requests: list[TargetRequest] = []

    def run(self, request: TargetRequest, **_kwargs: Any) -> AgentResult:
        self.requests.append(request)
        dataset_id = request.dataset_id or "ds_fake"
        return AgentResult(
            target="fake",
            success=True,
            status="completed",
            answer_text="上海 sales 是 100，服务没有泄露 oracle。",
            run_id=f"run_{len(self.requests)}",
            conversation_id=request.conversation_id,
            dataset_id=dataset_id,
        )


class RealUserCaseRunnerTest(unittest.TestCase):
    def test_manifest_rejects_empty_variants_and_prompt_leaks(self) -> None:
        manifest = _manifest()
        manifest["cases"][0]["question_variants"] = ["raw_prompt 里是什么"]

        with self.assertRaisesRegex(ValueError, "forbidden token"):
            validate_manifest(manifest)

    def test_duckdb_oracle_computes_source_fact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sales.csv"
            csv_path.write_text("city,sales\n上海,100\n北京,80\n", encoding="utf-8")

            oracle = evaluate_oracle(
                oracle_type="duckdb_sql",
                oracle_query_or_formula='SELECT city, sales FROM {table_0} ORDER BY sales DESC LIMIT 1',
                file_paths=[csv_path],
            )

        self.assertEqual([{"city": "上海", "sales": 100}], oracle["rows"])
        self.assertIn("上海", oracle["answer"])

    def test_runner_outputs_comparison_artifacts_and_reuses_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            csv_path = temp_path / "sales.csv"
            csv_path.write_text("city,sales\n上海,100\n北京,80\n", encoding="utf-8")
            manifest_path = temp_path / "manifest.json"
            manifest_path.write_text(_manifest_json(csv_path), encoding="utf-8")
            manifest = load_manifest(manifest_path)
            target = FakeTarget()
            output_dir = temp_path / "out"

            summary = run_manifest(manifest, target, output_dir=output_dir)

            self.assertEqual(4, summary["case_count"])
            self.assertTrue((output_dir / "comparison.md").exists())
            self.assertTrue((output_dir / "comparison.jsonl").exists())
            self.assertTrue((output_dir / "comparison_scored.md").exists())
            self.assertTrue((output_dir / "failure_index.jsonl").exists())
            self.assertEqual(4, len(load_comparison_rows(output_dir / "comparison.md")))
            conversation_requests = [request for request in target.requests if request.conversation_id == "conv_sales_followup"]
            self.assertNotEqual((), target.requests[0].file_paths)
            self.assertEqual((), target.requests[1].file_paths)
            self.assertEqual(2, len(conversation_requests))
            self.assertEqual("conv_sales_followup", conversation_requests[0].conversation_id)
            self.assertEqual("conv_sales_followup", conversation_requests[1].conversation_id)
            self.assertEqual((), conversation_requests[1].file_paths)
            self.assertEqual("ds_fake", conversation_requests[1].dataset_id)


def _manifest() -> dict[str, Any]:
    return {
        "name": "fixture_real_user_cases",
        "datasets": {"sales": {"files": ["sales.csv"]}},
        "cases": [
            {
                "case_id": "sales_top_city",
                "dataset": "sales",
                "capability_family": "topn_single_table",
                "canonical_question": "销售额最高的城市是哪个？",
                "question_variants": ["哪个城市卖得最好？", "帮我看 top 城市"],
                "expected_contract": "回答销售额最高城市及销售额。",
                "oracle_type": "duckdb_sql",
                "oracle_query_or_formula": "SELECT city, sales FROM {table_0} ORDER BY sales DESC LIMIT 1",
                "answer_requirements": {"required_terms": ["上海"], "expected_numbers": [100]},
                "severity": "p0",
                "tags": ["topn", "single_table"],
            }
        ],
    }


def _manifest_json(csv_path: Path) -> str:
    return f"""{{
  "name": "fixture_real_user_cases",
  "datasets": {{
    "sales": {{
      "files": ["{csv_path}"],
      "table_names": ["sales"]
    }}
  }},
  "cases": [
    {{
      "case_id": "sales_top_city",
      "dataset": "sales",
      "capability_family": "topn_single_table",
      "canonical_question": "销售额最高的城市是哪个？",
      "question_variants": ["哪个城市卖得最好？", "帮我看 top 城市"],
      "expected_contract": "回答销售额最高城市及销售额。",
      "oracle_type": "duckdb_sql",
      "oracle_query_or_formula": "SELECT city, sales FROM {{table_0}} ORDER BY sales DESC LIMIT 1",
      "answer_requirements": {{"required_terms": ["上海"], "expected_numbers": [100]}},
      "severity": "p0",
      "tags": ["topn", "single_table"]
    }}
  ],
  "conversations": [
    {{
      "conversation_id": "conv_sales_followup",
      "dataset": "sales",
      "capability_family": "followup_context",
      "severity": "p0",
      "tags": ["conversation"],
      "turns": [
        {{
          "turn_id": "turn_01",
          "question": "销售最高的城市是哪一个？",
          "expected_contract": "回答销售额最高城市及销售额。",
          "oracle_type": "duckdb_sql",
          "oracle_query_or_formula": "SELECT city, sales FROM {{table_0}} ORDER BY sales DESC LIMIT 1",
          "answer_requirements": {{"required_terms": ["上海"], "expected_numbers": [100]}}
        }},
        {{
          "turn_id": "turn_02",
          "question": "这个城市是多少销售额？",
          "expected_contract": "复用上文城市，回答销售额。",
          "oracle_type": "duckdb_sql",
          "oracle_query_or_formula": "SELECT 100 AS sales",
          "answer_requirements": {{"required_terms": ["100"], "expected_numbers": [100]}}
        }}
      ]
    }}
  ]
}}"""


if __name__ == "__main__":
    unittest.main()
