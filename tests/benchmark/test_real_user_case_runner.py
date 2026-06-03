from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any
import unittest

from scripts.real_user_eval.manifest import load_manifest, manifest_cases, normalize_expected_contract, validate_manifest
from scripts.real_user_eval.oracle import evaluate_oracle
from scripts.real_user_eval.runner import run_manifest
from scripts.real_user_eval.targets import AgentResult, TargetRequest, agent_result_from_response
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


class ResponseTarget:
    target_name = "response_fixture"

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def run(self, request: TargetRequest, **_kwargs: Any) -> AgentResult:
        return agent_result_from_response(
            target=self.target_name,
            response=self.response,
            fallback_dataset_id=request.dataset_id or "ds_response",
            fallback_run_id=request.run_id or "run_response",
        )


class RealUserCaseRunnerTest(unittest.TestCase):
    def test_manifest_rejects_empty_variants_and_prompt_leaks(self) -> None:
        manifest = _manifest()
        manifest["cases"][0]["question_variants"] = ["raw_prompt 里是什么"]

        with self.assertRaisesRegex(ValueError, "forbidden token"):
            validate_manifest(manifest)

    def test_structured_expected_contract_loads_and_normalizes_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = _manifest()
            manifest["datasets"]["sales"]["files"] = [str(Path(temp_dir) / "sales.csv")]
            manifest["cases"][0]["expected_contract"] = {
                "contract_family": "topn",
                "answer_type": "ranked_table",
                "required_row_count": 3,
                "required_dimensions": ["city"],
                "required_metrics": ["sales"],
                "required_sort": {"by": "sales", "order": "DESC"},
                "requires_direct_answer_first": True,
            }
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            loaded = load_manifest(manifest_path)
            case = manifest_cases(loaded)[0]

        self.assertIsInstance(case.expected_contract, dict)
        contract = case.expected_contract
        self.assertEqual("topn", contract["contract_family"])
        self.assertEqual(3, contract["required_row_count"])
        self.assertIsNone(contract["min_row_count"])
        self.assertFalse(contract["allow_insufficient_data_explanation"])
        self.assertEqual(["sales"], contract["required_sort"]["by"])
        self.assertEqual("desc", contract["required_sort"]["order"])
        self.assertEqual([], contract["violation_codes_expected_absent"])

    def test_legacy_text_expected_contract_still_loads(self) -> None:
        case = manifest_cases(_manifest())[0]

        self.assertEqual("回答销售额最高城市及销售额。", case.expected_contract)

    def test_invalid_structured_expected_contract_family_fails(self) -> None:
        manifest = _manifest()
        manifest["cases"][0]["expected_contract"] = {"contract_family": "benchmark_patch"}

        with self.assertRaisesRegex(ValueError, "contract_family is unsupported"):
            validate_manifest(manifest)

    def test_normalize_expected_contract_fills_p0_contract_fields(self) -> None:
        contract = normalize_expected_contract(
            {
                "contract_family": "gap",
                "required_gap_type": "adjacent",
                "required_context_reference": "previous_top_set",
                "required_metrics": ["orders", "adjacent_gap"],
                "requires_direct_answer_first": True,
            }
        )

        self.assertIsInstance(contract, dict)
        self.assertEqual("gap", contract["contract_family"])
        self.assertEqual("adjacent", contract["required_gap_type"])
        self.assertEqual("previous_top_set", contract["required_context_reference"])
        self.assertEqual([], contract["required_dimensions"])
        self.assertFalse(contract["required_all_files_covered"])
        self.assertFalse(contract["required_duplicate_check"])
        self.assertTrue(contract["requires_direct_answer_first"])

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
            scored = json.loads((output_dir / "comparison_scored.json").read_text(encoding="utf-8"))

            self.assertEqual(4, summary["case_count"])
            self.assertEqual("comparison_scored:llm", summary["acceptance_source"])
            self.assertEqual("llm", scored["judge_mode"])
            self.assertEqual(scored["summary"]["candidate_acceptable_count"], summary["passed"])
            self.assertEqual(summary["case_count"] - summary["passed"], summary["failed"])
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

    def test_runner_extracts_complete_runtime_semantic_oracle_evidence(self) -> None:
        response = {
            "success": True,
            "answer": "上海 sales 是 100。",
            "semantic_status": "passed",
            "contract_satisfied": True,
            "contract_family": "topn",
            "violations": [],
            "contract_report": {"task_family": "topn", "passed": True, "violations": []},
            "oracle_result": {"oracle_available": True, "passed": True, "issue_codes": []},
        }

        summary, comparison, scored, raw = _run_single_case_with_response(response)

        self.assertEqual(1, summary["semantic_checked_turns"])
        self.assertEqual(1, summary["semantic_passed_turns"])
        self.assertEqual(1, summary["contract_satisfied_turns"])
        self.assertEqual(1, summary["oracle_available_turns"])
        self.assertEqual(1, summary["oracle_passed_turns"])
        self.assertTrue(summary["gate_passed"])
        self.assertEqual([], summary["gate_failed_reasons"])
        self.assertEqual("passed", comparison["semantic_status"])
        self.assertTrue(comparison["semantic_passed"])
        self.assertEqual("topn", comparison["contract_family"])
        self.assertTrue(comparison["oracle_passed"])
        self.assertTrue(scored["semantic_passed"])
        self.assertTrue(raw["agent_result"]["semantic_evidence_available"])
        self.assertEqual({"oracle_available": True, "passed": True, "issue_codes": []}, raw["agent_result"]["oracle_result"])

    def test_runner_handles_missing_runtime_semantic_fields_without_crashing(self) -> None:
        response = {"success": True, "answer": "上海 sales 是 100。"}

        summary, comparison, scored, raw = _run_single_case_with_response(response)

        self.assertEqual("not_available", comparison["semantic_status"])
        self.assertFalse(comparison["semantic_passed"])
        self.assertEqual("not_available", comparison["semantic_gate_status"])
        self.assertEqual(1, summary["semantic_evidence_missing_turns"])
        self.assertEqual(1, summary["legacy_unverified_turns"])
        self.assertFalse(summary["gate_passed"])
        self.assertIn("legacy_unverified_rate_above_threshold:1.0000>0.2000", summary["gate_failed_reasons"])
        self.assertIn("not_available", raw["agent_result"]["semantic_evidence_missing_reason"])
        self.assertEqual("not_available", scored["semantic_status"])

    def test_summary_counts_top_violation_codes_and_failed_semantic_is_not_passed(self) -> None:
        response = {
            "success": True,
            "answer": "上海 sales 是 100。",
            "semantic_status": "failed",
            "contract_satisfied": False,
            "contract_family": "topn",
            "contract_report": {
                "task_family": "topn",
                "passed": False,
                "violations": [{"code": "topn_result_rows_short", "severity": "error"}],
            },
            "oracle_result": {
                "oracle_available": True,
                "passed": False,
                "issue_codes": ["oracle_result_mismatch"],
            },
        }

        summary, comparison, scored, _raw = _run_single_case_with_response(response)

        self.assertTrue(comparison["transport_success"])
        self.assertTrue(comparison["service_success"])
        self.assertEqual("failed", comparison["semantic_status"])
        self.assertFalse(comparison["semantic_passed"])
        self.assertFalse(comparison["contract_satisfied"])
        self.assertFalse(comparison["oracle_passed"])
        self.assertIn("semantic_not_passed:failed", comparison["failure_reasons"])
        self.assertEqual(1, summary["semantic_failed_turns"])
        self.assertEqual(1, summary["contract_failed_turns"])
        self.assertEqual(1, summary["oracle_failed_turns"])
        self.assertFalse(summary["gate_passed"])
        self.assertIn("semantic_failed_turns_above_threshold:1>0", summary["gate_failed_reasons"])
        self.assertIn("oracle_failed_turns_above_threshold:1>0", summary["gate_failed_reasons"])
        self.assertEqual(1, summary["top_violation_codes"]["topn_result_rows_short"])
        self.assertEqual(1, summary["top_violation_codes"]["oracle_result_mismatch"])
        self.assertFalse(scored["semantic_passed"])
        self.assertFalse(scored["runtime_gate_passed"])


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


def _run_single_case_with_response(response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        csv_path = temp_path / "sales.csv"
        csv_path.write_text("city,sales\n上海,100\n北京,80\n", encoding="utf-8")
        manifest = _manifest()
        manifest["datasets"]["sales"]["files"] = [str(csv_path)]
        target = ResponseTarget(response)
        output_dir = temp_path / "out"

        summary = run_manifest(
            manifest,
            target,
            output_dir=output_dir,
            max_variants_per_case=1,
            include_conversations=False,
            score_judge="heuristic",
        )
        comparison = json.loads((output_dir / "comparison.jsonl").read_text(encoding="utf-8").splitlines()[0])
        scored = json.loads((output_dir / "comparison_scored.jsonl").read_text(encoding="utf-8").splitlines()[0])
        raw = json.loads((output_dir / "agent_results.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self_check_summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["semantic_checked_turns"] == self_check_summary["semantic_checked_turns"]
        assert (output_dir / "summary.md").exists()
        return summary, comparison, scored, raw


if __name__ == "__main__":
    unittest.main()
