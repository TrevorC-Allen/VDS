"""Core algorithm smoke tests for DABstep-style uploaded data."""

from __future__ import annotations

import unittest
import os
from pathlib import Path

from data_agent_core.agent.single_agent import DataAnalysisAgent
from data_agent_core.benchmark.benchmark_runner import run_dabstep_benchmark
from data_agent_core.llm.client import MockLLMClient


DATASET_ROOT = Path("/Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep")


@unittest.skipUnless(DATASET_ROOT.exists(), "Local DABstep dataset is not available.")
class DabstepCoreTest(unittest.TestCase):
    def test_core_agent_answers_simple_aggregation(self) -> None:
        agent = DataAnalysisAgent(DATASET_ROOT / "data" / "context", llm_client=MockLLMClient())
        response, _trace = agent.analyze(
            "Which issuing country has the highest number of transactions?",
            "Answer must be just the country code.",
        )
        self.assertTrue(response.success)
        self.assertEqual(response.answer, "NL")
        self.assertTrue(response.debug["llm_used"])
        self.assertIn("llm_intent_parser", response.debug["single_agent_chain"])
        self.assertIn("verifier_critic", response.debug["llm_stage_summaries"])

    def test_dev_first_ten_reaches_minimum_accuracy(self) -> None:
        previous_provider = os.environ.get("VDS_LLM_PROVIDER")
        os.environ["VDS_LLM_PROVIDER"] = "mock"
        self.addCleanup(self._restore_provider, previous_provider)
        summary = run_dabstep_benchmark(
            dataset_root=DATASET_ROOT,
            split="dev",
            limit=10,
            offset=0,
            output_dir="outputs/dabstep_core_mvp_unittest",
        )
        self.assertEqual(summary["total"], 10)
        self.assertGreaterEqual(summary["accuracy"], 0.8)

    def test_all_split_offset_loads_eleventh_to_twentieth_tasks(self) -> None:
        previous_provider = os.environ.get("VDS_LLM_PROVIDER")
        os.environ["VDS_LLM_PROVIDER"] = "mock"
        self.addCleanup(self._restore_provider, previous_provider)
        summary = run_dabstep_benchmark(
            dataset_root=DATASET_ROOT,
            split="all",
            limit=10,
            offset=10,
            output_dir="outputs/dabstep_core_mvp_unittest_offset",
        )
        self.assertEqual(summary["total"], 10)
        self.assertEqual(summary["task_range"], [11, 20])
        self.assertEqual(summary["scored"], 0)

    @staticmethod
    def _restore_provider(previous_provider: str | None) -> None:
        if previous_provider is None:
            os.environ.pop("VDS_LLM_PROVIDER", None)
        else:
            os.environ["VDS_LLM_PROVIDER"] = previous_provider


if __name__ == "__main__":
    unittest.main()
