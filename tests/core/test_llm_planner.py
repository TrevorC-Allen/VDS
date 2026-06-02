"""LLM planner safety and fallback tests."""

from __future__ import annotations

import unittest

from data_agent_core.llm.planner import SUPPORTED_OPERATIONS, complete_stage_with_llm, plan_with_llm


class LLMPlannerTest(unittest.TestCase):
    def test_direct_llm_json_failure_falls_back_without_provider_content(self) -> None:
        client = _BadJsonLLMClient()

        stage = complete_stage_with_llm(
            llm_client=client,
            stage_name="verifier",
            stage_goal="verify fallback",
            question="本周PSD与上周相比，排名下降最多的Top10门店？",
            guidelines="",
            context_summary={},
            payload={},
            required_output={"reasoning_summary": "string"},
        )
        plan = plan_with_llm(
            llm_client=client,
            question="本周PSD与上周相比，排名下降最多的Top10门店？",
            guidelines="",
            context_summary={},
        )

        self.assertEqual(0.0, stage.confidence)
        self.assertTrue(stage.raw["fallback"])
        self.assertEqual("ValueError", stage.raw["error_type"])
        self.assertEqual("not_applicable", plan.logic_form.operation)
        self.assertNotIn("not-json-provider-content", str(stage.raw))
        self.assertNotIn("not-json-provider-content", plan.reasoning_summary)

    def test_supported_operations_cover_current_vds_bi_operations(self) -> None:
        expected = {
            "vds_current_category_share_top",
            "vds_current_filtered_metric_top",
            "vds_current_rank_with_period_change",
            "vds_current_share_top",
            "vds_current_top",
            "vds_group_top_entities",
            "vds_period_group_comparison",
            "vds_status_impact_top",
            "vds_three_period_top",
        }

        self.assertLessEqual(expected, SUPPORTED_OPERATIONS)


class _BadJsonLLMClient:
    def complete_json(self, messages, temperature=0.0):
        raise ValueError("not-json-provider-content")


if __name__ == "__main__":
    unittest.main()
