"""Phase 7.3 benchmark-runner contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from data_agent_core.benchmark.benchmark_runner import run_dabstep_benchmark
from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.output.response_builder import build_response
from data_agent_core.tracing.run_trace import RunTrace


class Phase73BenchmarkRunnerTest(unittest.TestCase):
    def test_dabstep_runner_writes_safe_prediction_provenance_and_risk_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset_root = root / "dataset"
            tasks_dir = dataset_root / "data" / "tasks"
            (dataset_root / "data" / "context").mkdir(parents=True)
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "dev.jsonl").write_text(
                json.dumps(
                    {
                        "task_id": "synthetic_1",
                        "question": "What is the amount?",
                        "guidelines": "Return only the number.",
                        "answer": "4811.76",
                    }
                )
                + "\n"
            )
            output_dir = root / "outputs"

            summary = run_dabstep_benchmark(
                dataset_root=dataset_root,
                split="dev",
                limit=1,
                output_dir=output_dir,
                agent_factory=lambda _context_dir: _FakeAgent(),
            )

            predictions = (output_dir / "dev_1_to_1_predictions.jsonl").read_text().splitlines()
            prediction = json.loads(predictions[0])
            report = json.loads(Path(summary["report_path"]).read_text())

            self.assertEqual("4811.76", prediction["agent_answer"])
            self.assertIsInstance(prediction["agent_answer"], str)
            self.assertTrue(report["details"][0]["output_contract_passed"])
            self.assertIn("provenance", report)
            self.assertIn("sha256", report["provenance"]["prediction_file"])
            self.assertIn("report_content_sha256", report["provenance"])
            self.assertIn("risk_taxonomy", report)
            self.assertFalse(report["risk_taxonomy"]["public_proxy_observation"]["used_in_core_chain"])


class _FakeAgent:
    def analyze(self, question: str, guidelines: str = "", execution_mode: str = "auto"):
        logic = LogicForm(
            task_type="generic",
            operation="aggregation",
            output_format={"answer_type": "number", "guidelines": guidelines},
        )
        response = build_response(
            run_id="run_fake",
            user_question=UserQuestion(dataset_id="synthetic", question=question, guidelines=guidelines, execution_mode=execution_mode),
            plan=AnalysisPlan(plan_id="plan_fake", logic_form=logic),
            execution_result=ExecutionResult(
                backend="pandas",
                success=True,
                value=[{"psp_reference": "PSP-1", "eur_amount": 4811.76}],
            ),
            verification=VerificationResult(passed=True),
            debug={"operation": "aggregation", "agent_mode": "fake"},
        )
        trace = RunTrace(
            run_id="run_fake",
            dataset_id="synthetic",
            question=question,
            logic_form=response.logic_form,
            final_response={"answer": response.answer, "success": response.success},
            latency_ms=12.0,
        )
        return response, trace


if __name__ == "__main__":
    unittest.main()
