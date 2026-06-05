"""Tests for randomized multi-turn Agent conversation evals."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient
from scripts.run_agent_random_conversation_eval import (
    OLD_DEMO_QUESTION_TOKENS,
    ConversationScenario,
    TurnEvidence,
    TurnPlan,
    build_dynamic_scenarios,
    builtin_scenarios,
    run_agent_random_conversation_eval,
    run_scenario,
    scenario_family_catalog,
    scenario_family_scenarios,
    simulate_user_turns,
    write_eval_artifacts,
    _report_html,
    _report_markdown,
    _scenarios_for_requested_families,
    _scenario_issues,
    _scenario_file_paths,
    _expected_dimension_from_question,
    _expected_dimensions_from_question,
    _expected_metric_from_question,
    _deterministic_fixture_oracle_result,
    _llm_generated_conversation_issues,
    _turn_evidence,
    _turn_plan_from_generated_question,
    _turn_plan_from_llm_item,
    _turn_issues,
)


class FakeUserSimulatorClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {
            "initial_question": "哪个城市销售额最高？",
            "followups": ["比较 Top 城市之间的差距", "利润率也重新看一下", "按月份看这个指标的趋势"],
        }


class EmptyUserSimulatorClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {"initial_question": "", "followups": []}


class StructuredFakeUserSimulatorClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {
            "turns": [
                {"question": "哪个城市销售额最高？", "expected_kind": "analysis", "capability_family": "ranking", "required_operation": "ranking"},
                {
                    "question": "按月份看这个指标的趋势",
                    "expected_kind": "followup_analysis",
                    "capability_family": "trend_followup",
                    "required_operation": "aggregation",
                },
            ]
        }


class MislabelledStructuredUserSimulatorClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {
            "turns": [
                {"question": "哪个城市销售额最高？", "expected_kind": "analysis", "capability_family": "ranking", "required_operation": "ranking"},
                {
                    "question": "按月份看这个指标的趋势",
                    "expected_kind": "followup_analysis",
                    "capability_family": "ranking_followup",
                    "required_operation": "ranking",
                },
            ]
        }


class GenericDimensionSwitchSimulatorClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {
            "turns": [
                {"question": "哪个城市销售额最高？", "expected_kind": "analysis", "capability_family": "ranking", "required_operation": "ranking"},
                {
                    "question": "那按产品拆一下",
                    "expected_kind": "followup_analysis",
                    "capability_family": "generic_dimension_switch",
                    "required_operation": "ranking",
                },
                {
                    "question": "继续比较 Top 结果之间的差距",
                    "expected_kind": "followup_analysis",
                    "capability_family": "ranking_followup",
                    "required_operation": "ranking",
                },
            ]
        }


class RealisticGeneratedFollowupClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {
            "initial_question": "哪个城市销售额最高？",
            "followups": [
                "Top 5 城市销售额占比是多少？",
                "这些城市按月份销售额趋势怎么样？",
                "按季度看前两名城市销售额差距变化",
            ],
        }


class CapturingUserSimulatorClient:
    def __init__(self) -> None:
        self.messages = []

    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        self.messages = messages
        return {
            "turns": [
                {"question": "按团队看销售额最高的是谁？", "capability_family": "ranking", "required_operation": "ranking"},
                {"question": "继续按月份看刚才口径的趋势", "capability_family": "trend_followup", "required_operation": "aggregation"},
            ]
        }


class OverviewRankingQualitySimulatorClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {
            "turns": [
                {
                    "question": "请先概览这批服务区域经营数据。",
                    "expected_kind": "overview",
                    "capability_family": "overview",
                    "required_operation": "dataset_overview",
                },
                {
                    "question": "基于上一步，哪个城市销售额最高？",
                    "expected_kind": "analysis",
                    "capability_family": "ranking",
                    "required_operation": "ranking",
                },
                {
                    "question": "这些数据有没有缺失或异常？",
                    "expected_kind": "quality",
                    "capability_family": "quality",
                    "required_operation": "cleaning_policy",
                },
            ]
        }


class MultiFileCustomerIdDrilldownSimulatorClient:
    def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
        return {
            "turns": [
                {
                    "question": "2026年第一季度各城市的订单总额是多少？",
                    "expected_kind": "analysis",
                    "capability_family": "aggregation",
                    "required_operation": "aggregation",
                },
                {
                    "question": "哪个城市的订单总额最高？",
                    "expected_kind": "followup_analysis",
                    "capability_family": "ranking_followup",
                    "required_operation": "ranking",
                },
                {
                    "question": "该城市2026年1月到3月的月度订单总额趋势如何？",
                    "expected_kind": "followup_analysis",
                    "capability_family": "trend_followup",
                    "required_operation": "aggregation",
                },
                {
                    "question": "在这个城市中，哪个客户贡献的订单总额最多？",
                    "expected_kind": "followup_analysis",
                    "capability_family": "ranking_followup",
                    "required_operation": "ranking",
                },
            ]
        }


class AgentRandomConversationEvalTest(unittest.TestCase):
    def test_llm_user_simulator_questions_drive_multi_turn_eval(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=42,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=FakeUserSimulatorClient(),
                simulator_source="fake_llm",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(result.passed, result.issues)
        self.assertEqual("fake_llm", result.simulator_source)
        self.assertEqual(["ranking", "ranking", "ranking", "aggregation"], [turn.operation for turn in result.turns])
        self.assertEqual(["ranking", "ranking_followup", "derived_metric_followup", "trend_followup"], [turn.capability_family for turn in result.turns])
        self.assertEqual(["analysis", "followup_analysis", "followup_analysis", "followup_analysis"], [turn.expected_kind for turn in result.turns])
        self.assertTrue(all(turn.conversation_id == result.turns[0].conversation_id for turn in result.turns))
        self.assertTrue(any(turn.followup_reason == "structured_followup_action" for turn in result.turns[1:]))
        self.assertTrue(all(turn.section_count >= 0 for turn in result.turns))

    def test_structured_llm_user_simulator_can_label_turn_capabilities(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        turns = simulate_user_turns(
            scenario,
            seed=42,
            max_followups=3,
            simulator_client=StructuredFakeUserSimulatorClient(),
        )

        self.assertEqual(["ranking", "trend_followup"], [turn.capability_family for turn in turns])
        self.assertEqual(["ranking", "aggregation"], [turn.required_operation for turn in turns])
        self.assertEqual(["analysis", "followup_analysis"], [turn.expected_kind for turn in turns])

    def test_realistic_llm_generated_followups_keep_context_and_pass(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=20260601,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=RealisticGeneratedFollowupClient(),
                simulator_source="fake_llm",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(result.passed, result.issues)
        self.assertEqual(
            ["ranking", "share_followup", "trend_followup", "trend_followup"],
            [turn.capability_family for turn in result.turns],
        )
        self.assertEqual(["ranking", "top_k_share", "aggregation", "aggregation"], [turn.operation for turn in result.turns])
        self.assertTrue(all(turn.answer_preview for turn in result.turns))
        self.assertTrue(all(turn.semantic_status not in {"failed", "needs_clarification"} for turn in result.turns))
        self.assertTrue(all(turn.followup_reason for turn in result.turns[1:]))

    def test_llm_generated_eval_infers_operation_from_question_not_bad_simulator_label(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=20260601,
                max_followups=2,
                output_dir=Path(temp_dir),
                simulator_client=MislabelledStructuredUserSimulatorClient(),
                simulator_source="fake_llm",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(result.passed, result.issues)
        self.assertEqual("aggregation", result.turns[1].required_operation)
        self.assertEqual("aggregation", result.turns[1].operation)

    def test_llm_generated_operation_gate_still_catches_agent_mismatch(self) -> None:
        issues = _llm_generated_conversation_issues(
            [
                TurnEvidence(
                    index=1,
                    question="哪个城市销售额最高？",
                    expected_kind="analysis",
                    capability_family="ranking",
                    required_operation="ranking",
                    success=True,
                    answer_type="table",
                    operation="aggregation",
                    conversation_id="conv_1",
                    state_name="analysis_ready",
                    action_count=1,
                    issue_count=0,
                ),
                TurnEvidence(
                    index=2,
                    question="继续比较 Top 结果。",
                    expected_kind="followup_analysis",
                    capability_family="ranking_followup",
                    required_operation="ranking",
                    success=True,
                    answer_type="list",
                    operation="ranking",
                    conversation_id="conv_1",
                    state_name="analysis_ready",
                    followup_reason="contextual_followup",
                    action_count=1,
                    issue_count=0,
                ),
            ]
        )

        self.assertIn("turn_1:operation_mismatch:expected=ranking:actual=aggregation", issues)

    def test_llm_generated_grouped_amount_situation_overrides_bad_overview_label(self) -> None:
        turn = _turn_plan_from_llm_item(
            {
                "question": "帮我看看2026年1月到3月各城市的订单总金额情况",
                "capability_family": "multi_file_overview",
                "required_operation": "dataset_overview",
            },
            index=0,
        )

        self.assertIsNotNone(turn)
        self.assertEqual("aggregation", turn.required_operation)
        self.assertEqual("aggregation", turn.capability_family)

    def test_llm_generated_city_revenue_customer_info_overrides_bad_overview_label(self) -> None:
        turn = _turn_plan_from_llm_item(
            {
                "question": "帮我看看2026年1月到3月每个城市的订单收入情况，包括客户信息吗？",
                "capability_family": "multi_file_overview",
                "required_operation": "dataset_overview",
            },
            index=0,
        )

        self.assertIsNotNone(turn)
        self.assertEqual("aggregation", turn.required_operation)
        self.assertEqual("aggregation", turn.capability_family)

    def test_llm_generated_schema_record_overview_overrides_bad_aggregation_label(self) -> None:
        turn = _turn_plan_from_llm_item(
            {
                "question": "请介绍一下订单和客户数据的基本情况，包括有哪些字段和记录数。",
                "capability_family": "aggregation",
                "required_operation": "aggregation",
            },
            index=0,
        )

        self.assertIsNotNone(turn)
        self.assertEqual("dataset_overview", turn.required_operation)
        self.assertEqual("overview", turn.capability_family)

    def test_llm_generated_scalar_metric_question_overrides_bad_quality_label(self) -> None:
        turn = _turn_plan_from_llm_item(
            {
                "question": "这个城市2026年3月的工单量是多少？",
                "capability_family": "quality",
                "required_operation": "cleaning_policy",
            },
            index=3,
        )

        self.assertIsNotNone(turn)
        self.assertEqual("aggregation", turn.required_operation)
        self.assertEqual("aggregation_followup", turn.capability_family)

    def test_llm_generated_multi_metric_reasonableness_overrides_bad_quality_label(self) -> None:
        turn = _turn_plan_from_llm_item(
            {
                "question": "这个城市3月份的工单数量与销售额相比是否合理？",
                "expected_kind": "quality",
                "capability_family": "quality",
                "required_operation": "cleaning_policy",
            },
            index=3,
        )

        self.assertIsNotNone(turn)
        self.assertEqual("aggregation", turn.required_operation)
        self.assertEqual("aggregation_followup", turn.capability_family)

    def test_ranked_set_profit_rate_how_question_is_metric_display_not_reranking(self) -> None:
        turn = _turn_plan_from_generated_question("收入排名前3的城市是哪些？他们的利润率如何？", index=1)

        self.assertEqual("aggregation", turn.required_operation)
        self.assertEqual("aggregation_followup", turn.capability_family)

    def test_largest_ticket_city_question_overrides_bad_quality_label(self) -> None:
        turn = _turn_plan_from_llm_item(
            {
                "question": "工单量最大的城市是哪几个？",
                "expected_kind": "quality",
                "capability_family": "quality",
                "required_operation": "cleaning_policy",
            },
            index=3,
        )

        self.assertIsNotNone(turn)
        self.assertEqual("ranking", turn.required_operation)
        self.assertEqual("generic_dimension_switch", turn.capability_family)

    def test_turn_gate_catches_dimension_mismatch_even_when_operation_matches(self) -> None:
        issues = _turn_issues(
            1,
            TurnPlan("结合相关表，按城市看金额排名前 5。", capability_family="multi_table_join_ranking", required_operation="ranking"),
            {
                "success": True,
                "answer": "按月份排名完成。",
                "logic_form": {
                    "operation": "ranking",
                    "parameters": {"metric": "amount", "dimension": "month"},
                },
                "current_analysis_context": {"state_name": "analysis_ready"},
            },
            previous_conversation_id="",
        )

        self.assertIn("turn_1:dimension_mismatch:expected=city:actual=month", issues)

    def test_llm_generated_gate_fails_unclassified_analysis_turns(self) -> None:
        issues = _llm_generated_conversation_issues(
            [
                TurnEvidence(
                    index=1,
                    question="随便讲讲你觉得有什么有意思的地方。",
                    expected_kind="analysis",
                    capability_family="analysis",
                    required_operation="",
                    success=True,
                    answer_type="text",
                    operation="chat",
                    conversation_id="conv_1",
                    state_name="analysis_ready",
                    action_count=1,
                    issue_count=0,
                ),
                TurnEvidence(
                    index=2,
                    question="继续。",
                    expected_kind="followup_analysis",
                    capability_family="llm_followup",
                    required_operation="",
                    success=True,
                    answer_type="text",
                    operation="chat",
                    conversation_id="conv_1",
                    state_name="analysis_ready",
                    followup_reason="contextual_followup",
                    action_count=1,
                    issue_count=0,
                ),
            ]
        )

        self.assertIn("turn_1:unclassified_required_operation", issues)
        self.assertIn("turn_2:unclassified_required_operation", issues)

    def test_generic_dimension_switch_followup_uses_current_dataset_not_retail_action(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=20260601,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=GenericDimensionSwitchSimulatorClient(),
                simulator_source="fake_llm",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(result.passed, result.issues)
        self.assertEqual(["ranking", "ranking", "ranking"], [turn.operation for turn in result.turns])
        self.assertEqual("structured_followup_action", result.turns[1].followup_reason)
        self.assertEqual("generic_dimension_switch", result.turns[1].capability_family)

    def test_post_initial_llm_turns_report_independent_analysis_separately(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_agent_random_conversation_eval(
                seed=23,
                scenario_count=1,
                max_followups=2,
                output_dir=Path(temp_dir),
                simulator_client=OverviewRankingQualitySimulatorClient(),
                simulator_source="fake_llm",
                agent_client=MockLLMClient(),
                min_conversations=1,
                min_capability_families=3,
                min_followup_turns=0,
                min_structured_action_turns=1,
            )

        self.assertTrue(report["passed"], report["results"])
        turns = report["results"][0]["turns"]
        self.assertEqual(["初始问题", "连续追问", "独立分析"], [turn["turn_role"] for turn in turns])
        self.assertEqual([False, True, True], [turn["conversation_turn"] for turn in turns])
        self.assertEqual(2, report["coverage"]["post_initial_turns"])
        self.assertEqual(2, report["coverage"]["contextualized_post_initial_turns"])
        self.assertEqual(0, report["coverage"]["missing_post_initial_context_turns"])

    def test_llm_user_simulator_failure_does_not_fallback_to_templates(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=42,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=EmptyUserSimulatorClient(),
                simulator_source="fake_llm",
                agent_client=MockLLMClient(),
            )

        self.assertFalse(result.passed)
        self.assertEqual([], result.turns)
        self.assertEqual(["simulator_generation_failed:LLM simulator returned no valid user questions"], result.issues)

    def test_env_llm_simulator_requires_structured_turns_for_auditable_random_eval(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=42,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=FakeUserSimulatorClient(),
                simulator_source="env",
                agent_client=MockLLMClient(),
            )

        self.assertFalse(result.passed)
        self.assertEqual([], result.turns)
        self.assertEqual(
            ["simulator_generation_failed:LLM simulator must return required_output.turns with at least one valid user question"],
            result.issues,
        )

    def test_builtin_random_conversation_eval_passes_with_mock_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_agent_random_conversation_eval(
                seed=7,
                scenario_count=0,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=None,
                simulator_source="deterministic",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(report["passed"], report["results"])
        self.assertEqual(1.0, report["pass_rate"])
        self.assertEqual("typical", report["scenario_family"])
        self.assertEqual(["typical"], report["scenario_families"])
        self.assertEqual(
            {"regional_performance_agent", "service_region_agent", "multi_file_customer_revenue_agent"},
            {item["scenario_id"] for item in report["results"]},
        )
        self.assertEqual({"typical"}, {item["scenario_family"] for item in report["results"]})
        for result in report["results"]:
            self.assertFalse(result["issues"])
            self.assertGreaterEqual(len(result["turns"]), 2)
            self.assertTrue(all(turn["scenario_family"] == "typical" for turn in result["turns"]))
        self.assertIn("structured_answer_turns", report["coverage"])
        self.assertIn("family_summary", report)
        self.assertIn("typical", report["family_level_pass_rate"])

    def test_scenario_family_catalog_contains_requested_families(self) -> None:
        catalog = scenario_family_catalog()

        self.assertGreaterEqual(len(catalog), 7)
        self.assertTrue(
            {
                "single_file_overview_topn_gap",
                "multi_file_overview_join_analysis",
                "data_quality_diagnosis",
                "time_trend_anomaly",
                "group_comparison_share",
                "ambiguous_user_language",
                "metric_switching",
            }.issubset(catalog)
        )
        self.assertGreaterEqual(len(scenario_family_scenarios()), 7)

    def test_can_select_single_scenario_family(self) -> None:
        selected = _scenarios_for_requested_families(["single_file_overview_topn_gap"])

        self.assertEqual(["single_file_overview_topn_gap"], sorted({item.scenario_family for item in selected}))
        self.assertEqual(["family_single_file_overview_topn_gap"], [item.scenario_id for item in selected])

    def test_can_select_multiple_scenario_families(self) -> None:
        selected = _scenarios_for_requested_families(["single_file_overview_topn_gap", "data_quality_diagnosis"])

        self.assertEqual(
            ["data_quality_diagnosis", "single_file_overview_topn_gap"],
            sorted({item.scenario_family for item in selected}),
        )

    def test_unknown_scenario_family_has_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown scenario family: missing_family"):
            _scenarios_for_requested_families(["missing_family"])

    def test_single_run_summary_includes_family_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_agent_random_conversation_eval(
                seed=19,
                scenario_count=1,
                max_followups=4,
                output_dir=Path(temp_dir),
                simulator_client=None,
                simulator_source="deterministic",
                agent_client=MockLLMClient(),
                scenario_families=["data_quality_diagnosis"],
                min_pass_rate=0.0,
                min_followup_turns=0,
                min_structured_action_turns=0,
                max_legacy_unverified_rate=1.0,
            )

        self.assertEqual("data_quality_diagnosis", report["scenario_family"])
        self.assertEqual(["data_quality_diagnosis"], report["scenario_families"])
        self.assertIn("family_summary", report)
        self.assertIn("family_coverage", report)
        self.assertIn("family_level_pass_rate", report)
        self.assertIn("family_level_semantic_pass_rate", report)
        self.assertIn("family_level_oracle_pass_rate", report)
        self.assertIn("family_level_expected_contract_pass_rate", report)
        self.assertIn("top_violation_codes_by_family", report)
        self.assertEqual(["data_quality_diagnosis"], report["coverage"]["scenario_families"])
        self.assertEqual("not_instrumented", report["coverage"]["expected_contract_coverage_status"])
        self.assertEqual(report["coverage"]["turn_count"], report["coverage"]["expected_contract_not_instrumented_turns"])
        self.assertEqual(report["coverage"]["turn_count"], report["coverage"]["expected_contract_coverage_risk_turns"])
        markdown = _report_markdown(report)
        self.assertIn("Expected contract coverage status: not_instrumented", markdown)
        self.assertIn("Expected contract not instrumented turns:", markdown)

    def test_multi_file_builtin_scenario_covers_join_and_followup(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=17,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=None,
                simulator_source="deterministic",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(result.passed, result.issues)
        self.assertIn(result.turns[0].operation, {"dataset_overview", "multi_table_dataset_overview"})
        self.assertEqual(["ranking", "aggregation", "ranking"], [turn.operation for turn in result.turns[1:]])
        self.assertEqual(
            ["multi_file_overview", "multi_table_join_ranking", "trend_followup", "ranking_followup"],
            [turn.capability_family for turn in result.turns],
        )
        self.assertTrue(any(turn.followup_reason == "structured_followup_action" for turn in result.turns[2:]))

    def test_multi_file_customer_drilldown_can_use_verified_entity_id_when_no_label_exists(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario(
                scenario,
                seed=31,
                max_followups=4,
                output_dir=Path(temp_dir),
                simulator_client=MultiFileCustomerIdDrilldownSimulatorClient(),
                simulator_source="fake_llm",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(result.passed, result.issues)
        self.assertEqual("filtered_metric_ranking", result.turns[-1].operation)
        self.assertTrue(result.turns[-1].success)
        self.assertIn("customer_id", result.turns[-1].answer_preview)

    def test_eval_can_repeat_random_conversations_per_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_agent_random_conversation_eval(
                seed=11,
                scenario_count=1,
                runs_per_scenario=2,
                max_followups=3,
                output_dir=Path(temp_dir),
                simulator_client=None,
                simulator_source="deterministic",
                agent_client=MockLLMClient(),
            )

        self.assertTrue(report["passed"], report["results"])
        self.assertEqual(1, report["scenario_count"])
        self.assertEqual(2, report["runs_per_scenario"])
        self.assertEqual(2, report["conversation_count"])
        self.assertEqual([1, 2], [item["run_index"] for item in report["results"]])
        self.assertGreaterEqual(report["coverage"]["followup_turns"], 2)
        self.assertGreaterEqual(report["coverage"]["structured_action_turns"], 1)

    def test_eval_writes_reviewable_report_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = run_agent_random_conversation_eval(
                seed=7,
                scenario_count=1,
                max_followups=2,
                output_dir=root,
                simulator_client=None,
                simulator_source="deterministic",
                agent_client=MockLLMClient(),
            )
            artifacts = write_eval_artifacts(report, root)

            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            markdown = (root / "report.md").read_text(encoding="utf-8")
            html = (root / "index.html").read_text(encoding="utf-8")
            with (root / "turn_records.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            jsonl_lines = (root / "conversation_records.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(report["passed"], summary["passed"])
        self.assertIn("# Agent Random Conversation Eval Report", markdown)
        self.assertIn("Open `index.html`", markdown)
        self.assertIn("Artifacts:", markdown)
        self.assertIn("## 失败索引", markdown)
        self.assertIn("## 对话流", markdown)
        self.assertIn("连续追问", markdown)
        self.assertIn("上下文", markdown)
        self.assertIn("Agent Random Conversation Eval", html)
        self.assertIn("可查看记录", html)
        self.assertIn("失败定位", html)
        self.assertIn("没有失败轮次", html)
        self.assertIn("对话记录", html)
        self.assertIn("预期 / 实际 operation", html)
        self.assertIn("timeline-item", html)
        self.assertIn("Agent 回答摘要", html)
        self.assertTrue(rows)
        self.assertIn("answer_preview", rows[0])
        self.assertIn("next_action_questions", rows[0])
        self.assertIn("operation_match", rows[0])
        self.assertIn("turn_issues", rows[0])
        self.assertIn("turn_role", rows[0])
        self.assertIn("conversation_turn", rows[0])
        self.assertIn("context_status", rows[0])
        self.assertIn("会话内连续提问", markdown)
        self.assertIn("会话内后续提问", html)
        self.assertTrue(any(row["answer_preview"] for row in rows))
        self.assertTrue(any(row["next_action_questions"] for row in rows))
        self.assertEqual(str(root / "index.html"), artifacts["index_html"])
        self.assertEqual(str(root / "summary.json"), artifacts["summary_json"])
        self.assertEqual(report["conversation_count"], len(jsonl_lines))

    def test_visual_report_surfaces_failed_turns_before_full_conversation_log(self) -> None:
        report = {
            "passed": False,
            "pass_rate": 0.0,
            "conversation_count": 1,
            "scenario_count": 1,
            "runs_per_scenario": 1,
            "seed": 9,
            "simulator_source": "env",
            "generated_at": "2026-06-01T00:00:00",
            "global_issues": ["global_pass_rate_below_threshold:0.0000<1.0000"],
            "thresholds": {"min_pass_rate": 1.0},
            "coverage": {"turn_count": 1, "capability_family_counts": {"ranking": 1}, "operation_counts": {"aggregation": 1}},
            "policy": "policy",
            "results": [
                {
                    "scenario_id": "scenario",
                    "run_index": 1,
                    "passed": False,
                    "capability_family": "ranking",
                    "issues": ["turn_1:operation_mismatch:expected=ranking:actual=aggregation"],
                    "turns": [
                        {
                            "index": 1,
                            "question": "哪个城市销售额最高？",
                            "expected_kind": "analysis",
                            "capability_family": "ranking",
                            "required_operation": "ranking",
                            "success": True,
                            "answer_type": "table",
                            "operation": "aggregation",
                            "conversation_id": "conv_1",
                            "state_name": "analysis_ready",
                            "turn_role": "初始问题",
                            "context_status": "新会话入口",
                            "structured_answer": True,
                            "section_count": 5,
                            "answer_preview": "按城市汇总。",
                            "next_action_questions": [],
                        }
                    ],
                }
            ],
        }

        markdown = _report_markdown(report)
        html = _report_html(report)

        self.assertLess(html.index("失败定位"), html.index("对话记录"))
        self.assertIn("哪个城市销售额最高？", markdown)
        self.assertIn("ranking", markdown)
        self.assertIn("aggregation", markdown)
        self.assertIn("turn_1:operation_mismatch", html)

    def test_eval_global_thresholds_fail_when_random_coverage_is_too_small(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_agent_random_conversation_eval(
                seed=7,
                scenario_count=1,
                runs_per_scenario=1,
                max_followups=1,
                output_dir=Path(temp_dir),
                simulator_client=None,
                simulator_source="deterministic",
                agent_client=MockLLMClient(),
                min_conversations=2,
                min_capability_families=4,
                min_followup_turns=3,
                min_structured_action_turns=2,
                min_structured_answer_turns=99,
            )

        self.assertFalse(report["passed"])
        self.assertEqual(1, report["conversation_count"])
        self.assertIn("global_conversation_count_below_threshold:1<2", report["global_issues"])
        self.assertTrue(any(issue.startswith("global_capability_family_count_below_threshold") for issue in report["global_issues"]))
        self.assertTrue(any(issue.startswith("global_followup_turns_below_threshold") for issue in report["global_issues"]))
        self.assertTrue(any(issue.startswith("global_structured_answer_turns_below_threshold") for issue in report["global_issues"]))

    def test_dynamic_uploaded_files_build_schema_driven_random_eval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "custom_sales.csv"
            csv_path.write_text(
                "month,city,product,sales,profit\n"
                "2026-01,上海,苹果,100,40\n"
                "2026-01,北京,苹果,250,80\n"
                "2026-02,上海,香蕉,180,70\n"
                "2026-02,北京,香蕉,160,50\n",
                encoding="utf-8",
            )

            scenarios = build_dynamic_scenarios([csv_path], dataset_name="custom_sales")
            report = run_agent_random_conversation_eval(
                seed=3,
                scenario_count=1,
                max_followups=5,
                output_dir=root / "eval",
                simulator_client=None,
                simulator_source="deterministic",
                agent_client=MockLLMClient(),
                input_files=[csv_path],
                dataset_name="custom_sales",
            )

        self.assertEqual("dynamic_custom_sales", scenarios[0].scenario_id)
        self.assertEqual("dynamic_uploaded_schema_agent", scenarios[0].capability_family)
        self.assertIn("custom_sales.csv", scenarios[0].schema_summary["files"])
        self.assertFalse(scenarios[0].shuffle_followups)
        self.assertGreaterEqual(scenarios[0].min_distinct_capability_families, 4)
        self.assertEqual(
            ["overview", "quality", "ranking", "ranking_followup", "derived_metric_followup", "trend_followup"],
            [turn.capability_family for turn in scenarios[0].turn_templates],
        )
        self.assertTrue(any("利润率" in turn.question for turn in scenarios[0].turn_templates))
        self.assertTrue(report["passed"], report["results"])
        self.assertEqual(["dynamic_custom_sales"], [item["scenario_id"] for item in report["results"]])
        families = {turn["capability_family"] for turn in report["results"][0]["turns"]}
        self.assertTrue({"overview", "quality", "ranking", "derived_metric_followup", "trend_followup"}.issubset(families))

    def test_dynamic_uploaded_files_without_profit_still_cover_reusable_families(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "orders.csv"
            csv_path.write_text(
                "month,region,product,revenue\n"
                "2026-01,华东,苹果,100\n"
                "2026-01,华北,苹果,250\n"
                "2026-02,华东,香蕉,180\n"
                "2026-02,华北,香蕉,160\n",
                encoding="utf-8",
            )

            scenario = build_dynamic_scenarios([csv_path], dataset_name="orders")[0]

        families = [turn.capability_family for turn in scenario.turn_templates]
        self.assertIn("overview", families)
        self.assertIn("quality", families)
        self.assertIn("ranking", families)
        self.assertIn("trend_followup", families)
        self.assertNotIn("derived_metric_followup", families)
        self.assertEqual(["ranking", "aggregation"], scenario.required_operations)

    def test_scenario_gate_requires_declared_dynamic_capability_coverage(self) -> None:
        scenario = ConversationScenario(
            scenario_id="gate",
            dataset_name="gate",
            capability_family="dynamic_uploaded_schema_agent",
            turn_templates=[],
            required_capability_families=["overview", "ranking"],
            min_turn_count=3,
            min_distinct_capability_families=2,
        )
        issues = _scenario_issues(
            scenario,
            [
                TurnEvidence(
                    index=1,
                    question="看一下这个数据。",
                    expected_kind="overview",
                    capability_family="overview",
                    required_operation="",
                    success=True,
                    answer_type="overview",
                    operation="multi_table_dataset_overview",
                    conversation_id="conv_1",
                    state_name="chat_only",
                    action_count=0,
                    issue_count=0,
                )
            ],
        )

        self.assertIn("missing_required_capability_family:ranking", issues)
        self.assertIn("min_turn_count_not_met:1<3", issues)
        self.assertIn("min_distinct_capability_families_not_met:1<2", issues)

    def test_mock_simulator_keeps_deterministic_templates(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        turns = simulate_user_turns(scenario, seed=11, max_followups=2, simulator_client=MockLLMClient())

        self.assertTrue(turns[0].question)
        self.assertNotEqual(scenario.turn_templates[0].question, turns[0].question)
        self.assertEqual(3, len(turns))

    def test_builtin_question_generation_is_schema_random_not_old_demo_questions(self) -> None:
        for scenario in builtin_scenarios():
            questions_a = [turn.question for turn in simulate_user_turns(scenario, seed=17, max_followups=3)]
            questions_b = [turn.question for turn in simulate_user_turns(scenario, seed=18, max_followups=3)]

            self.assertTrue(all(question for question in questions_a))
            self.assertNotEqual(questions_a, questions_b)
            joined = "\n".join([*questions_a, *questions_b])
            for token in OLD_DEMO_QUESTION_TOKENS:
                self.assertNotIn(token, joined)

    def test_share_followup_generation_preserves_share_intent(self) -> None:
        share_tokens = ("占比", "占总", "贡献", "份额", "比例")
        scenarios = [
            item
            for item in scenario_family_scenarios()
            if item.scenario_family in {"single_file_overview_topn_gap", "group_comparison_share"}
        ]

        self.assertEqual(
            ["single_file_overview_topn_gap", "group_comparison_share"],
            [item.scenario_family for item in scenarios],
        )
        for scenario in scenarios:
            turns = simulate_user_turns(scenario, seed=20260604, max_followups=4)
            share_turns = [turn for turn in turns if turn.capability_family == "share_followup"]

            self.assertEqual(1, len(share_turns), scenario.scenario_family)
            self.assertEqual("top_k_share", share_turns[0].required_operation)
            self.assertTrue(
                any(token in share_turns[0].question for token in share_tokens),
                (scenario.scenario_family, share_turns[0].question),
            )

    def test_llm_simulator_prompt_uses_capability_plan_not_seed_question_templates(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")
        client = CapturingUserSimulatorClient()

        turns = simulate_user_turns(scenario, seed=5, max_followups=2, simulator_client=client)

        self.assertEqual(["ranking", "trend_followup"], [turn.capability_family for turn in turns])
        prompt = json.dumps(client.messages, ensure_ascii=False)
        payload = json.loads(client.messages[1]["content"])
        self.assertIn("capability_plan", prompt)
        self.assertIn("不能照抄模板", prompt)
        self.assertNotIn("seed_templates", prompt)
        self.assertIn("turns", payload["required_output"])

    def test_english_llm_generated_questions_are_classified_into_capabilities(self) -> None:
        self.assertEqual(
            "ranking",
            _turn_plan_from_generated_question("Which city had the highest total sales last quarter?", index=0).capability_family,
        )
        self.assertEqual(
            "trend_followup",
            _turn_plan_from_generated_question("How did that city's sales trend month by month?", index=1).capability_family,
        )
        self.assertEqual(
            "derived_metric_followup",
            _turn_plan_from_generated_question("Which city had the highest profit margin?", index=1).capability_family,
        )
        self.assertEqual(
            "generic_dimension_switch",
            _turn_plan_from_generated_question("Break that down by product", index=1).capability_family,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("客户记录一共有多少？", index=0).required_operation,
        )
        self.assertEqual(
            "cleaning_policy",
            _turn_plan_from_generated_question("这些数据有没有缺失或异常？", index=1).required_operation,
        )
        self.assertEqual(
            "ranking",
            _turn_plan_from_generated_question("在2月销售额增长最快的城市中，哪个产品贡献最大？", index=1).required_operation,
        )
        self.assertEqual(
            "generic_dimension_switch",
            _turn_plan_from_generated_question("在2月销售额增长最快的城市中，哪个产品贡献最大？", index=1).capability_family,
        )
        self.assertEqual(
            "growth_ranking",
            _turn_plan_from_generated_question("从1月到3月，销售额增长最快的城市是哪个？", index=1).required_operation,
        )
        self.assertEqual(
            "growth_ranking",
            _turn_plan_from_generated_question("这些城市中，销售额增长最快的是哪个？", index=1).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("2026年1月到3月，每个城市的订单总额和利润率分别是多少？", index=0).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("这个城市在1月、2月、3月的利润率变化趋势是怎样的？", index=1).required_operation,
        )
        self.assertEqual(
            "ranking",
            _turn_plan_from_generated_question("对于该城市，各业务线按利润率从高到低排序是怎样的？", index=4).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("2026年1月的利润率相比2月是上升还是下降？", index=1).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("2026年各月的订单总金额分别是多少？", index=0).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("请给我总览一下订单和客户数据，包括总订单金额、客户数以及利润率。", index=0).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("该城市每个月的工单量是否也同步增长？", index=4).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_llm_item(
                {
                    "question": "该城市每个月的工单量是否也同步增长？",
                    "expected_kind": "quality",
                    "capability_family": "quality",
                    "required_operation": "cleaning_policy",
                },
                index=4,
            ).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("这些排名前3的城市，它们的利润率分别是多少？", index=1).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("在2026年第一季度，订单金额排名前三的城市是哪些？它们的利润率分别是多少？", index=1).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("在销售额前三的城市中，利润总额是多少？", index=1).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("这个城市各服务线的工单量占比如何？", index=1).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("我们服务区域上个月的销售总额是多少？", index=0).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("前3名城市在2月和3月的销售额分别是多少？", index=1).required_operation,
        )
        self.assertEqual(
            "ranking",
            _turn_plan_from_generated_question("在上面概况中，2026年1月哪个城市的收入最高？", index=1).required_operation,
        )
        self.assertEqual(
            "aggregation",
            _turn_plan_from_generated_question("上个月各城市的销售数据怎么样？", index=0).required_operation,
        )
        self.assertEqual(
            "ranking",
            _turn_plan_from_generated_question("这个城市上个月的利润率在全部城市中排第几？", index=1).required_operation,
        )
        self.assertEqual(
            "month",
            _expected_dimension_from_question("按季度看前两名城市销售额差距变化"),
        )
        self.assertEqual(
            "amount",
            _expected_metric_from_question("在利润率最高的那个月，该城市下哪个客户群的订单额最高？"),
        )
        self.assertEqual(
            "利润率",
            _expected_metric_from_question("在2026年第一季度，订单金额最高的前3个城市中，哪个城市的利润率最高？"),
        )
        self.assertEqual(
            "利润率",
            _expected_metric_from_question("2026年1月订单总额最高的城市，其利润率在1月到3月的变化趋势如何？"),
        )
        self.assertEqual(
            "利润率",
            _expected_metric_from_question("其中总金额最高的客户在2026年1月到3月每个月的利润率是多少？"),
        )
        self.assertEqual(
            "amount",
            _expected_metric_from_question("在利润率最高的城市中，哪个客户群的订单金额最大？"),
        )
        self.assertEqual(
            "sales",
            _expected_metric_from_question("在利润率最高的城市中，哪个服务线的销售额最高？"),
        )
        self.assertEqual(
            "tickets",
            _expected_metric_from_question("在利润率最高的城市中，哪个服务线的工单量最高？"),
        )
        self.assertEqual(
            "amount",
            _expected_metric_from_question("在2026年第一季度，哪个城市的订单总额最高？"),
        )
        self.assertEqual(
            "amount",
            _expected_metric_from_question("这个城市在2026年1月到3月的订单总额变化趋势如何？"),
        )
        self.assertEqual(
            "profit",
            _expected_metric_from_question("在销售额前三的城市中，利润总额是多少？"),
        )
        self.assertEqual(
            "profit",
            _expected_metric_from_question("在总金额最高的城市中，哪个客户贡献的利润最多？"),
        )
        self.assertEqual(
            "amount",
            _expected_metric_from_question("在利润最高的城市中，哪个客户贡献的订单总金额最多？"),
        )
        self.assertEqual(
            "profit",
            _expected_metric_from_question("在2026年1月，订单金额最高的城市中，哪个客户细分（segment）贡献的利润最多？"),
        )
        self.assertEqual(
            "sales",
            _expected_metric_from_question("这个城市在2月和3月的销售趋势如何？"),
        )
        self.assertEqual(
            "sales,tickets",
            _expected_metric_from_question("2026年1月各城市的销售总额和工单量分别是多少？"),
        )

    def test_chinese_month_filter_matches_yyyy_mm_values_across_backends(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月哪个城市的销售额最高？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"])
        self.assertEqual([{"city": "上海", "sales": 318}], response["result"]["rows"])

    def test_named_city_scalar_question_inside_conversation_keeps_followup_context(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月哪个城市的销售额最高？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="北京1月的销售额是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["followup_context"]["is_followup"], response.get("followup_context"))
        self.assertIn(response["followup_context"]["reason"], {"self_contained_followup", "contextual_followup", "structured_followup_action"})
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(276.0, response["result"]["value"])

    def test_topn_candidate_set_metric_can_differ_from_ranking_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在2026年1月销售额前3的城市中，每个城市的利润排名如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual({"month": {"year": 2026, "month": 1}}, response["logic_form"]["filters"])
        self.assertEqual("profit", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            {"dimension": "city", "metric": "sales", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"year": 2026, "month": 1}}},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertIn("Candidate-set metric bound as TopN filter", "\n".join(response["verification"]["semantic_verification_notes"]))
        self.assertEqual([{"city": "上海", "profit": 92}, {"city": "北京", "profit": 83}], response["result"]["rows"])

    def test_service_sales_and_tickets_multi_metric_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售总额和工单量分别是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["sales", "tickets"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"city": "上海", "sales": 180.0, "tickets": 35.0}, {"city": "北京", "sales": 216.0, "tickets": 28.0}],
            response["result"]["rows"],
        )

    def test_reasonableness_followup_keeps_sales_and_tickets_metrics(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年第一季度各城市的总销售额是多少？",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="哪个城市在2026年3月的销售额最高？",
                execution_mode="dual",
            )
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个城市从1月到3月的销售额趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个城市3月份的工单数量与销售额相比是否合理？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(["sales", "tickets"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual({"city": "深圳", "month": {"month": 3}}, response["logic_form"]["filters"])
        self.assertIn("sales", response["result"]["columns"])
        self.assertIn("tickets", response["result"]["columns"])
        self.assertIn("是否合理需要历史基准", response["answer"])
        self.assertIn("当前只展示已验证指标对照", response["answer"])

    def test_topn_candidate_set_scalar_metric_can_differ_from_ranking_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在2026年1月销售额前3的城市中，利润总额是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("profit", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(
            {"dimension": "city", "metric": "sales", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"year": 2026, "month": 1}}},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual(175.0, response["result"]["value"])

    def test_ordinal_ranking_question_returns_requested_rank_position(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="那2026年1月销售额第二高的城市是哪个？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(2, response["logic_form"]["parameters"]["rank_position"])
        self.assertEqual([{"city": "北京", "sales": 276}], response["result"]["rows"])

    def test_extreme_city_reference_can_switch_to_product_profit(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年第一季度各城市的总销售额排名如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(first["conversation_id"]),
                question="那这几个城市的销售额月度趋势是怎样的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(first["conversation_id"]),
                question="在销售额最高的城市中，哪种产品的利润贡献最大？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("contextual_extreme_reference", response["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("profit", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("product", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "深圳", "month": {"year": 2026, "month_range": [1, 3]}}, response["logic_form"]["filters"])
        self.assertEqual([{"product": "数据治理", "profit": 126}], response["result"]["rows"])

    def test_contextual_top_city_followup_filters_before_customer_drilldown(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            top_city = service.respond_to_message(
                dataset_id=dataset_id,
                question="在2026年第一季度，哪个城市的订单总金额最高？列出前3名。",
                execution_mode="dual",
            )
            conversation_id = str(top_city["conversation_id"])
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个城市在1月、2月、3月的订单金额月度趋势如何？",
                execution_mode="dual",
            )
            customer = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="在订单金额最高的城市中，哪个客户贡献的订单金额最多？",
                execution_mode="dual",
            )

        self.assertEqual([{"city": "上海", "amount": 325}, {"city": "北京", "amount": 310}, {"city": "深圳", "amount": 288}], top_city["result"]["rows"])
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual({"city": "上海", "month": {"month_range": [1, 3]}}, trend["logic_form"]["filters"])
        self.assertEqual([{"month": "2026-01", "amount": 120}, {"month": "2026-02", "amount": 205}], trend["result"]["rows"])
        self.assertEqual("contextual_extreme_reference", customer["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", customer["logic_form"]["operation"])
        self.assertEqual("customer_id", customer["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "上海", "month": {"year": 2026, "month_range": [1, 3]}}, customer["logic_form"]["filters"])
        self.assertEqual([{"customer_id": "C1", "amount": 325}], customer["result"]["rows"])

    def test_contextual_city_trend_then_customer_segment_phrase_uses_segment_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            conversation_id = str(
                service.respond_to_message(
                    dataset_id=str(upload["dataset_id"]),
                    question="请介绍一下订单和客户数据的基本情况，包括有哪些字段和数据量。",
                    execution_mode="dual",
                )["conversation_id"]
            )
            service.respond_to_message(
                conversation_id=conversation_id,
                question="2026年1月哪个城市的订单金额最高？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=conversation_id,
                question="这个城市在2026年1月到3月的订单金额趋势如何？",
                execution_mode="dual",
            )
            customer = service.respond_to_message(
                conversation_id=conversation_id,
                question="在2026年1月，这个城市中哪个客户段的订单金额排名第一？",
                execution_mode="dual",
            )

        self.assertTrue(customer["success"], customer.get("verification"))
        self.assertEqual("structured_followup_action", customer["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", customer["logic_form"]["operation"])
        self.assertEqual("segment", customer["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "北京", "month": {"year": 2026, "month": 1}}, customer["logic_form"]["filters"])
        self.assertEqual([{"segment": "企业", "amount": 310}], customer["result"]["rows"])

    def test_growth_fastest_city_candidate_then_profit_margin_segment_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="对于订单总额增长最快的那个城市，其利润率最高的客户细分是什么？",
                execution_mode="dual",
        )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertIsNone(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("ranking", response["logic_form"]["operation"])
        self.assertEqual("segment", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertEqual(
            {
                "operation": "growth_ranking",
                "dimension": "city",
                "metric": "amount",
                "aggregation": "sum",
                "time_column": "month",
                "growth_mode": "rate",
                "limit": 1,
                "sort_order": "desc",
            },
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual([{"segment": "企业", "利润率": 102 / 325}], response["result"]["rows"])

    def test_target_city_ranking_overrides_customer_id_statistics_phrase(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="按客户ID统计，哪个城市的总订单金额排名前三？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertIn(response["logic_form"]["operation"], {"ranking", "filtered_metric_ranking"})
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["source_tables"])
        self.assertEqual([{"city": "上海", "amount": 325}, {"city": "北京", "amount": 310}, {"city": "深圳", "amount": 288}], response["result"]["rows"])

    def test_explicit_fact_table_with_dimension_table_field_joins_for_city_grouping(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="帮我看看orders表里2026年1月到3月各城市的收入情况，以及对应的客户信息？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["source_tables"])
        self.assertEqual(
            [
                {"city": "上海", "amount": 325},
                {"city": "北京", "amount": 310},
                {"city": "广州", "amount": 172},
                {"city": "深圳", "amount": 288},
            ],
            response["result"]["rows"],
        )

    def test_contextual_no_data_followup_returns_structured_boundary_not_failure(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="帮我看看2026年1月到3月各城市的订单总金额情况",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="哪个城市在这三个月中总金额最高？列出前3名",
                execution_mode="dual",
            )
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个排名第一的城市在2026年1月到3月每个月的金额趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="该城市在2026年3月金额最高的前3个客户分别贡献了多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("debug", {}).get("output_contract_validation"))
        self.assertEqual([], response["result"]["rows"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual({"city": "上海", "month": {"month": 3, "year": 2026}}, response["logic_form"]["filters"])
        self.assertIn("当前结果没有返回", response["answer"])
        self.assertGreaterEqual(len(response.get("structured_answer_sections") or {}), 5)

    def test_contextual_change_wording_then_profit_customer_drilldown(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            top_city = service.respond_to_message(
                dataset_id=dataset_id,
                question="在这些月份里，哪个城市的订单金额最高？列出前5个城市。",
                execution_mode="dual",
            )
            conversation_id = str(top_city["conversation_id"])
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="刚才排名第一的城市，其订单金额在这三个月中是如何变化的？",
                execution_mode="dual",
            )
            profit_customer = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="在这个城市中，利润最高的前3个客户是谁？",
                execution_mode="dual",
            )

        self.assertEqual("city", top_city["logic_form"]["parameters"]["dimension"])
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "上海"}, trend["logic_form"]["filters"])
        self.assertEqual("structured_followup_action", profit_customer["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", profit_customer["logic_form"]["operation"])
        self.assertEqual("profit", profit_customer["logic_form"]["parameters"]["metric"])
        self.assertEqual("customer_id", profit_customer["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "上海"}, profit_customer["logic_form"]["filters"])
        self.assertEqual([{"customer_id": "C1", "profit": 102}], profit_customer["result"]["rows"])

    def test_topn_focus_set_survives_trend_before_customer_profit_drilldown(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            top_cities = service.respond_to_message(
                dataset_id=dataset_id,
                question="在2026年第一季度，哪个城市的客户总订单金额排名前三？",
                execution_mode="dual",
            )
            conversation_id = str(top_cities["conversation_id"])
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这前三名城市在2026年1月到3月的月度订单金额趋势如何？",
                execution_mode="dual",
            )
            customer = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="在这些城市中，利润最高的客户是哪个？",
                execution_mode="dual",
            )

        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual(
            {"dimension": "city", "metric": "amount", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"year": 2026, "month_range": [1, 3]}}},
            trend["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertTrue(customer["success"], customer.get("verification"))
        self.assertEqual("structured_followup_action", customer["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", customer["logic_form"]["operation"])
        self.assertEqual("profit", customer["logic_form"]["parameters"]["metric"])
        self.assertEqual("customer_id", customer["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            {"dimension": "city", "metric": "amount", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"year": 2026, "month_range": [1, 3]}}},
            customer["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual([{"customer_id": "C1", "profit": 102}, {"customer_id": "C2", "profit": 86}, {"customer_id": "C4", "profit": 79}], customer["result"]["rows"])

    def test_customer_count_ranking_uses_distinct_entity_count(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在2026年1月，哪个城市的客户数量最多？列出前3个城市及其客户数。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("customer_id", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("nunique", response["logic_form"]["parameters"]["aggregation"])
        self.assertEqual(["city", "count"], response["result"]["columns"])

    def test_amount_ranking_can_include_customer_count_without_changing_primary_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="哪个城市的订单总金额最高？列出前3名及各自的客户数量。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("customer_count", response["logic_form"]["parameters"]["metric_specs"][0]["name"])
        self.assertEqual(["city", "amount", "customer_count"], response["result"]["columns"])

    def test_grouped_share_question_returns_share_table_not_scalar_topk_share(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年第一季度，各服务线的工单量占比是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertTrue(response["logic_form"]["parameters"]["share_of_total"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])
        self.assertIn("tickets_share", response["result"]["columns"])
        self.assertAlmostEqual(
            100.0,
            sum(float(row["tickets_share"]) for row in response["result"]["rows"]),
            places=6,
        )

    def test_segment_profit_margin_can_filter_candidate_customers_by_amount(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在2026年第一季度，哪个客户群体的利润率最高？按segment分组，只考虑订单金额前5的客户。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("segment", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertEqual(
            {"dimension": "customer_id", "metric": "amount", "aggregation": "sum", "limit": 5, "sort_order": "desc"},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual(["segment", "利润率"], response["result"]["columns"])

    def test_customer_topn_amount_does_not_treat_order_data_as_order_count(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="基于订单数据，结合客户表，列出2026年第一季度收入最高的前5个客户及其总金额。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("customer_id", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"month_range": [1, 3], "year": 2026}}, response["logic_form"]["filters"])

    def test_profit_margin_followup_trend_keeps_ratio_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            top_city = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年第一季度，哪个城市的利润率最高？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(top_city["conversation_id"]),
                question="这个城市在1月、2月、3月的利润率变化趋势是怎样的？",
                execution_mode="dual",
            )

        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("amount", trend["logic_form"]["parameters"]["derived_metric"]["denominator"])

    def test_product_profit_margin_scalar_followup_exposes_verified_metric_column(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            city = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年1月到3月，哪个城市的销售额最高？",
                execution_mode="dual",
            )
            conversation_id = str(city["conversation_id"])
            service.respond_to_message(
                conversation_id=conversation_id,
                question="这个城市在这三个月的销售额趋势是怎样的？",
                execution_mode="dual",
            )
            product = service.respond_to_message(
                conversation_id=conversation_id,
                question="那在这个城市里，哪款产品的销售额排名第一？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=conversation_id,
                question="这款产品的利润率是多少？",
                execution_mode="dual",
            )

        self.assertTrue(product["success"], product.get("verification"))
        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual({"city": "深圳", "product": "数据治理"}, response["logic_form"]["filters"])
        self.assertEqual(["利润率"], response["result"]["columns"])
        self.assertIn("利润率", response["result"]["rows"][0])

    def test_growth_ranking_followup_uses_entity_dimension_and_growth_operation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售额排名是怎样的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="从1月到2月，销售额增长最快的两个城市是哪些？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("growth_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(["city", "sales_growth_rate", "start_period", "end_period", "start_value", "end_value", "growth_delta", "growth_rate"], response["result"]["columns"])

    def test_change_largest_city_followup_uses_growth_delta_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售额排名是怎样的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="那么，从1月到2月，销售额变化最大的城市是哪个？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("growth_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("abs_delta", response["logic_form"]["parameters"]["growth_mode"])
        self.assertEqual({"month": {"month_range": [1, 2]}}, response["logic_form"]["filters"])
        self.assertEqual("上海", response["result"]["rows"][0]["city"])

    def test_growth_trend_most_obvious_followup_uses_growth_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月各城市的销售额和工单量情况如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="销售额最高的三个城市是哪些？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这三个城市中，哪个城市在2026年1到3月的销售额增长趋势最明显？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("growth_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])

    def test_profit_margin_breakdown_then_highest_city_runs_compound_actions(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售额分别是多少？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="按销售额从高到低排个序，前三个城市是哪些？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这几个城市从1月到3月的销售额变化趋势如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这些城市中，哪个月份的销售额数据质量有问题？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="计算每个城市各月的利润率，并找出利润率最高的城市。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("compound_analysis", response["answer_type"])
        self.assertEqual("compound_followup_actions", response["followup_context"]["reason"])
        self.assertEqual(["aggregation", "ranking"], [action["result_operation"] for action in response["agent_actions"]])
        sub_results = response["result"]["sub_results"]
        self.assertEqual("aggregation", sub_results[0]["logic_form"]["operation"])
        self.assertEqual("city", sub_results[0]["logic_form"]["parameters"]["dimension"])
        self.assertEqual("ranking", sub_results[1]["logic_form"]["operation"])
        self.assertEqual("city", sub_results[1]["logic_form"]["parameters"]["dimension"])
        self.assertEqual("深圳", sub_results[1]["result"]["rows"][0]["city"])
        self.assertEqual("ranking", response["current_analysis_context"]["operation"])

    def test_rank_retention_followup_reruns_ranking_for_new_month(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售额排名是怎样的？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="那2月份销售额最高的城市是哪个？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市在3月份还保持第一吗？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual({"month": {"month": 3}}, response["logic_form"]["filters"])

    def test_metric_anomaly_followup_with_whether_wording_uses_quality_operation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月各城市的销售额和利润情况如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这三个月销售额排名前三的城市是哪些？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="排名第一的城市在这三个月的销售额趋势是怎样的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="该城市各服务线的工单量是否有异常？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("outlier_count", response["logic_form"]["operation"])
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])

    def test_business_ticket_quality_followup_uses_grouped_aggregation_without_quality_signals(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售情况如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="销量最高的城市是哪个？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市1到3月的销量趋势怎样？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="该城市各服务线的工单质量如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "北京"}, response["logic_form"]["filters"])
        self.assertEqual(
            [{"service_line": "实施交付", "tickets": 33}, {"service_line": "客户成功", "tickets": 28}],
            response["result"]["rows"],
        )

    def test_ticket_quality_with_anomaly_suffix_stays_quality_operation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售情况如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="销量最高的城市是哪个？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市1到3月的销量趋势怎样？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="该城市各服务线的工单质量如何？有没有异常值？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("cleaning_policy", response["logic_form"]["operation"])

    def test_ranked_entity_share_followup_uses_top_k_share(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年第一季度的订单数据有哪些？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="按客户ID统计总订单金额，排名前五的客户是哪几个？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这些前五客户在2026年1月到3月的月度订单金额趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="其中排名第一的客户，其订单金额贡献占比多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("top_k_share", response["logic_form"]["operation"])
        self.assertEqual("customer_id", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(1, response["logic_form"]["parameters"]["limit"])

    def test_ranked_set_share_followup_after_gap_uses_top_k_share(self) -> None:
        scenario = next(item for item in scenario_family_scenarios() if item.scenario_family == "group_comparison_share")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="按服务线分组看销售额表现。",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="前 3 名城市之间差距有多大？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这些 Top 城市的销售额分别占总销售额多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("top_k_share", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(["深圳", "上海", "北京"], response["logic_form"]["parameters"]["referent_values"])

    def test_ranked_set_metric_display_uses_aggregation_not_reranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年第一季度各城市的总销售额排名如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="排名前3的城市在3月份的销售额分别是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertIn("candidate_filter", response["logic_form"]["parameters"])

    def test_multi_metric_trend_followup_preserves_amount_and_profit(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月，每个城市的订单总额和利润总额是多少？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在这些城市中，哪个城市的利润率最高？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市在2026年1月到3月期间，每月的订单总额和利润总额变化趋势如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("month", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(["amount", "profit"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual(["month", "amount", "profit"], response["result"]["columns"])

    def test_profit_condition_month_keeps_order_amount_as_target_metric(self) -> None:
        self.assertEqual("amount", _expected_metric_from_question("在利润最高的那个月，哪个客户群体的订单总额最大？"))

        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在利润最高的那个月，哪个客户群体的订单总额最大？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertIn(response["logic_form"]["operation"], {"ranking", "filtered_metric_ranking"})
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("segment", response["logic_form"]["parameters"]["dimension"])

    def test_same_dimension_extreme_reference_keeps_ranking_intent(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月，各城市的订单收入总额是多少？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在收入最高的城市中，哪些城市的利润率更高？",
                execution_mode="dual",
        )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertIn(response["followup_context"]["reason"], {"self_contained_followup", "structured_followup_action"})
        self.assertIn(response["logic_form"]["operation"], {"ranking", "filtered_metric_ranking"})
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["metric"])

    def test_anomaly_count_compound_question_is_quality_family(self) -> None:
        plan = _turn_plan_from_generated_question("该城市在1月份的工单数量有多少？是否存在异常值？", index=1)
        self.assertEqual("quality", plan.expected_kind)
        self.assertEqual("cleaning_policy", plan.required_operation)
        distribution = _turn_plan_from_generated_question("这个城市各服务线的工单量分布怎么样？有没有异常？", index=1)
        self.assertEqual("followup_analysis", distribution.expected_kind)
        self.assertEqual("aggregation", distribution.required_operation)

    def test_customer_group_segment_alias_uses_segment_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="哪个城市的客户贡献收入最高？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市从1月到3月的收入趋势是怎样的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在该城市中，哪个客户群（segment）的收入排名第一？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("segment", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])

    def test_highest_income_city_phrase_reuses_city_focus_for_trend(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月各城市的订单总收入是多少？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="哪个城市的收入最高？列出前3名。",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个最高收入城市在2026年1月到3月的月度收入趋势如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("month", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])

    def test_month_rank_change_wording_keeps_city_ranking_target_after_trend(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="请介绍一下订单和客户数据的基本情况，包括有哪些字段和数据量。",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="在2026年1月，哪个城市的订单金额最高？请列出前3名。",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="这些城市的订单金额在2026年1月到3月之间是如何变化的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="在2026年3月，订单金额排名前三的城市是哪些？与1月相比有变化吗？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual({"month": {"year": 2026, "month": 3}}, response["logic_form"]["filters"])

    def test_highest_month_reference_filters_before_city_sales_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年各月的订单总额和利润率分别是多少？",
                execution_mode="dual",
            )
            top_month = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="哪个月份的利润率最高？请列出前三个月。",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="在利润率最高的月份，哪个城市的销售额最高？",
                execution_mode="dual",
            )

        self.assertTrue(top_month["success"], top_month.get("verification"))
        self.assertEqual(
            [
                {"month": "2026-02", "利润率": 0.3050397877984085},
                {"month": "2026-01", "利润率": 0.28837209302325584},
                {"month": "2026-03", "利润率": 0.2743055555555556},
            ],
            top_month["result"]["rows"],
        )
        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("contextual_extreme_reference", response["followup_context"]["reason"])
        self.assertEqual("在2026年2月，哪个城市的销售额最高？", response["followup_context"]["revised_question"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"month": 2, "year": 2026}}, response["logic_form"]["filters"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["source_tables"])
        self.assertEqual([{"city": "上海", "amount": 205}], response["result"]["rows"])

    def test_explicit_named_city_change_followup_routes_to_month_trend(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            ranking = service.respond_to_message(
                dataset_id=dataset_id,
                question="按销售额从高到低排列城市，并告诉我前3名是哪些？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(ranking["conversation_id"]),
                question="成都的销售额在1月到3月之间如何变化？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertEqual("ranking", ranking["logic_form"]["operation"])
        self.assertEqual("city", ranking["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", ranking["logic_form"]["parameters"]["metric"])
        self.assertEqual(3, ranking["logic_form"]["parameters"]["limit"])
        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "成都", "month": {"month_range": [1, 3]}}, trend["logic_form"]["filters"])

    def test_each_city_trend_prefers_month_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在这三个月里，每个城市的销售额趋势如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"month": "2026-01", "sales": 594}, {"month": "2026-02", "sales": 606}, {"month": "2026-03", "sales": 594}],
            response["result"]["rows"],
        )

    def test_self_contained_join_ranking_after_overview_keeps_requested_city_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="帮我概览这批客户订单收入上传文件能支持哪些分析。",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id="",
                conversation_id=str(overview["conversation_id"]),
                question="结合相关表，按城市看金额排名前 5。",
                execution_mode="dual",
            )

        self.assertEqual("self_contained_followup", response["followup_context"]["reason"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["source_tables"])
        self.assertEqual(
            [{"city": "上海", "amount": 325}, {"city": "北京", "amount": 310}, {"city": "深圳", "amount": 288}, {"city": "广州", "amount": 172}],
            response["result"]["rows"],
        )

    def test_multi_metric_total_returns_all_requested_metrics(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请帮我查一下所有客户的订单总金额和总利润是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["amount", "profit"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual([{"amount": 1095, "profit": 318}], response["result"]["rows"])
        self.assertIn("数据摘要（关键指标）", response["answer"])
        self.assertIn("amount 为 1,095", response["answer"])
        self.assertIn("profit 为 318", response["answer"])

    def test_grouped_order_total_and_profit_returns_both_requested_metrics(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="从客户和订单数据中，2026年1月到3月各城市的订单总额和总利润情况如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(["amount", "profit"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual(
            [
                {"city": "上海", "amount": 325.0, "profit": 102.0},
                {"city": "北京", "amount": 310.0, "profit": 86.0},
                {"city": "广州", "amount": 172.0, "profit": 51.0},
                {"city": "深圳", "amount": 288.0, "profit": 79.0},
            ],
            response["result"]["rows"],
        )

    def test_different_cities_amount_question_routes_to_grouped_aggregation_not_distinct_count(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年第一季度不同城市的订单总金额是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])

    def test_customer_segment_trend_followup_keeps_month_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="从订单和客户数据中，2026年第一季度各城市的总收入是多少？",
                execution_mode="dual",
            )
            segment = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在收入最高的城市中，哪个客户群体贡献最大？列出前3名客户群及其收入。",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个客户群在2026年1月到3月的收入趋势如何？",
                execution_mode="dual",
            )
            margin_month = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在这三个月中，哪个月份该客户群的利润率最高？",
                execution_mode="dual",
            )

        self.assertTrue(segment["success"], segment.get("verification"))
        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual("amount", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertTrue(margin_month["success"], margin_month.get("verification"))
        self.assertIn(margin_month["logic_form"]["operation"], {"ranking", "filtered_metric_ranking"})
        self.assertEqual("利润率", margin_month["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", margin_month["logic_form"]["parameters"]["dimension"])

    def test_top_city_monthly_amount_trend_is_not_rewritten_to_month_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请介绍一下客户订单数据，包括订单金额、利润和客户信息，以及有哪些城市和细分市场？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在2026年第一季度，哪个城市的订单总金额最高？请列出前5个城市。",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="对于刚才排名第一的城市，其每月订单金额在2026年1月到3月的变化趋势是怎样的？",
                execution_mode="dual",
            )

        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual("amount", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])

    def test_ranked_city_set_monthly_trend_prefers_time_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请给我总览一下订单和客户数据，包括总订单金额、客户数以及利润率。",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在2026年第一季度，哪个城市的订单金额最高？列出前5名。",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这些城市在2026-01到2026-03期间，每个月的订单金额趋势如何？",
                execution_mode="dual",
            )
            growth = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在刚才的趋势中，哪个城市在2026-02的订单金额增长最快？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertIn("按月份展示订单金额趋势", trend["followup_context"]["revised_question"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual("amount", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertTrue(growth["success"], growth.get("verification"))
        self.assertEqual("growth_ranking", growth["logic_form"]["operation"])
        self.assertEqual("amount", growth["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", growth["logic_form"]["parameters"]["dimension"])

    def test_top_ranked_city_customer_margin_followup_filters_city_and_accepts_customer_id(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月，每个城市的总订单金额是多少？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="按总金额排名前三的城市是哪些？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这三个城市在2026年1月到3月的月度金额趋势如何？",
                execution_mode="dual",
            )
            customer = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="其中排名第一的城市，利润率最高的客户是哪位？",
                execution_mode="dual",
            )

        self.assertTrue(customer["success"], customer.get("verification"))
        self.assertEqual("contextual_extreme_reference", customer["followup_context"]["reason"])
        self.assertIn("在上海城市中", customer["followup_context"]["revised_question"])
        self.assertEqual("filtered_metric_ranking", customer["logic_form"]["operation"])
        self.assertEqual("利润率", customer["logic_form"]["parameters"]["metric"])
        self.assertEqual("customer_id", customer["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "上海"}, customer["logic_form"]["filters"])
        self.assertEqual([{"customer_id": "C1", "利润率": 0.31384615384615383}], customer["result"]["rows"])

    def test_grouped_metric_and_distinct_entity_count_join_by_city(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月，各城市的订单总额和客户数量是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(["amount", "customer_count"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual("nunique", response["logic_form"]["parameters"]["metric_specs"][1]["aggregation"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["source_tables"])
        self.assertEqual(
            [
                {"city": "上海", "amount": 325.0, "customer_count": 1},
                {"city": "北京", "amount": 310.0, "customer_count": 1},
                {"city": "广州", "amount": 172.0, "customer_count": 1},
                {"city": "深圳", "amount": 288.0, "customer_count": 1},
            ],
            response["result"]["rows"],
        )

    def test_monthly_amount_and_profit_question_does_not_treat_customer_data_as_customer_count(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="订单和客户数据中，2026年各月的总收入和总利润分别是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("month", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(["amount", "profit"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual(
            [
                {"month": "2026-01", "amount": 430.0, "profit": 124.0},
                {"month": "2026-02", "amount": 377.0, "profit": 115.0},
                {"month": "2026-03", "amount": 288.0, "profit": 79.0},
            ],
            response["result"]["rows"],
        )

    def test_order_overview_with_totals_and_order_count_succeeds(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请给我一份订单数据的概览，包括总金额、总利润和订单数量。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual(["amount", "profit", "order_count"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual(
            [
                {"amount": 1095.0, "profit": 318.0, "order_count": 5},
            ],
            response["result"]["rows"],
        )

    def test_top_city_profit_margin_respectively_uses_aggregation_not_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="这个数据集包含哪些客户和订单信息？请简要介绍一下。",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                dataset_id="",
                conversation_id=str(overview["conversation_id"]),
                question="2026年1月哪个城市的订单金额最高？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id="",
                conversation_id=str(overview["conversation_id"]),
                question="2026年1月这个城市（金额最高的城市）的订单金额在后续月份（2月和3月）的变化趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id="",
                conversation_id=str(overview["conversation_id"]),
                question="在2026年第一季度，订单金额排名前三的城市是哪些？它们的利润率分别是多少？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(
            {"dimension": "city", "metric": "amount", "aggregation": "sum", "limit": 3, "sort_order": "desc"},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertIn("按城市汇总利润率", response["followup_context"]["revised_question"])

    def test_order_total_followups_override_previous_profit_margin_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年第一季度各城市的订单总额和利润率分别是多少？",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="在2026年第一季度，哪个城市的订单总额最高？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="这个城市在2026年1月到3月的订单总额变化趋势如何？",
                execution_mode="dual",
            )
            segment = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="在刚才那个城市中，哪个客户细分（segment）的订单总额最高？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertEqual("amount", ranking["logic_form"]["parameters"]["metric"])
        self.assertEqual([{"city": "上海", "amount": 325}], ranking["result"]["rows"])
        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("amount", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual(
            [{"month": "2026-01", "amount": 120}, {"month": "2026-02", "amount": 205}],
            trend["result"]["rows"],
        )
        self.assertTrue(segment["success"], segment.get("verification"))
        self.assertEqual("amount", segment["logic_form"]["parameters"]["metric"])
        self.assertEqual("segment", segment["logic_form"]["parameters"]["dimension"])
        self.assertEqual([{"segment": "企业", "amount": 325}], segment["result"]["rows"])

    def test_highest_city_trend_and_customer_group_followup_keep_context_after_failure_candidate(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="请给我一份2026年1月到3月各城市的订单总金额和客户数量数据。",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="在2026年第一季度，哪个城市的订单总金额最高？请列出前5名。",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="这个最高城市的订单总金额在1月、2月、3月分别是多少？趋势如何？",
                execution_mode="dual",
            )
            customer_group = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="在这些月份中，该城市哪个客户群体的订单金额最高？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual("amount", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "上海", "month": {"month_range": [1, 3]}}, trend["logic_form"]["filters"])
        self.assertTrue(customer_group["success"], customer_group.get("verification"))
        self.assertEqual("structured_followup_action", customer_group["followup_context"]["reason"])
        self.assertEqual("amount", customer_group["logic_form"]["parameters"]["metric"])
        self.assertEqual("segment", customer_group["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "上海", "month": {"month_range": [1, 3]}}, customer_group["logic_form"]["filters"])
        self.assertEqual([{"segment": "企业", "amount": 325}], customer_group["result"]["rows"])

    def test_generated_multi_metric_total_is_classified_as_aggregation(self) -> None:
        turn = _turn_plan_from_generated_question("请帮我查一下所有客户的订单总金额和总利润是多少？", index=0)

        self.assertEqual("aggregation", turn.required_operation)
        self.assertEqual("aggregation", turn.capability_family)

    def test_overview_wording_with_explicit_totals_routes_to_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请介绍一下客户订单数据的基本情况，包括总金额、总利润和客户数量。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["amount", "profit", "customer_count"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual([{"amount": 1095.0, "profit": 318.0, "customer_count": 4}], response["result"]["rows"])

    def test_multi_file_business_overview_with_metric_totals_routes_to_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请介绍一下订单和客户数据的基本情况，包括总金额、总利润和客户数量。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["amount", "profit", "customer_count"], response["logic_form"]["parameters"]["metrics"])

    def test_multi_file_overall_situation_with_metric_examples_routes_to_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="从orders和customers表里能看出哪些整体情况？比如总订单金额、客户数之类的。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["amount", "customer_count"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual(["orders"], response["logic_form"]["source_tables"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["parameters"]["explicit_table_mentions"])
        self.assertEqual([{"amount": 1095.0, "customer_count": 4}], response["result"]["rows"])

    def test_explicit_orders_and_customers_overview_keeps_fact_table_for_metrics(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请展示 orders 和 customers 表的整体数据情况，包括总金额、总利润和客户数量。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["amount", "profit", "customer_count"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual(["orders"], response["logic_form"]["source_tables"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["parameters"]["explicit_table_mentions"])
        self.assertEqual([{"amount": 1095.0, "profit": 318.0, "customer_count": 4}], response["result"]["rows"])

    def test_overview_wording_with_total_income_and_customer_count_routes_to_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请概述客户订单收入数据的基本情况，包括总收入和总客户数。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["amount", "customer_count"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual([{"amount": 1095.0, "customer_count": 4}], response["result"]["rows"])

    def test_overview_wording_with_income_profit_and_margin_routes_to_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请介绍一下2026年1月到3月客户订单数据的基本情况，包括总收入、利润和利润率。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual(["amount", "profit", "利润率"], response["logic_form"]["parameters"]["metrics"])
        self.assertEqual(
            [{"amount": 1095.0, "profit": 318.0, "利润率": 318.0 / 1095.0}],
            response["result"]["rows"],
        )

    def test_order_data_content_question_routes_to_overview_not_raw_rows(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年第一季度的订单数据有哪些？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("dataset_overview", response["logic_form"]["operation"])
        self.assertEqual("overview", response["answer_type"])
        self.assertIn("数据摘要（关键指标）", response["answer"])

    def test_grouped_sales_situation_routes_to_aggregation_not_overview(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="帮我看看2026年1月到3月各城市的销售情况",
                execution_mode="dual",
            )
            sales_data = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="给我看一下2026年1月到3月各城市的销售数据",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(
            [{"city": "上海", "sales": 428}, {"city": "北京", "sales": 414}, {"city": "深圳", "sales": 586}],
            response["result"]["rows"],
        )
        self.assertTrue(sales_data["success"], sales_data.get("verification"))
        self.assertEqual("aggregation", sales_data["logic_form"]["operation"])
        self.assertEqual("city", sales_data["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", sales_data["logic_form"]["parameters"]["metric"])

    def test_grouped_metric_overview_wording_routes_to_aggregation_not_overview(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请给我一个服务区域经营数据的总体概览，包括各城市的销售额、利润和工单量。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertIn("sales", response["logic_form"]["parameters"].get("metrics") or [response["logic_form"]["parameters"].get("metric")])

    def test_total_amount_and_city_distribution_routes_to_grouped_join_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请介绍一下客户订单数据的基本情况，包括总金额和城市分布。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual(["orders", "customers"], response["logic_form"]["source_tables"])
        self.assertEqual("table", response["answer_type"])
        self.assertEqual(
            [
                {"city": "上海", "amount": 325},
                {"city": "北京", "amount": 310},
                {"city": "广州", "amount": 172},
                {"city": "深圳", "amount": 288},
            ],
            response["result"]["rows"],
        )

    def test_compound_city_segment_customer_count_uses_entity_count_not_amount(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="有哪些城市和客户细分？各有多少客户？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("segment", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("customer_id", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("nunique", response["logic_form"]["parameters"]["aggregation"])
        self.assertEqual(
            [{"name": "customer_count", "field": "customer_id", "aggregation": "nunique"}],
            response["logic_form"]["parameters"]["metric_specs"],
        )
        self.assertEqual(["segment", "customer_count"], response["result"]["columns"])
        self.assertNotIn("amount", response["result"]["columns"])
        self.assertEqual(
            [{"segment": "个人", "customer_count": 1}, {"segment": "企业", "customer_count": 3}],
            response["result"]["rows"],
        )

    def test_single_month_grouped_sales_overview_routes_to_aggregation_not_overview(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="请给我2026年1月各城市的销售额总览。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])

    def test_expected_dimension_treats_month_range_as_filter_when_grouping_by_city(self) -> None:
        self.assertEqual("city", _expected_dimension_from_question("2026年1月到3月各城市的订单总金额是多少？"))
        self.assertEqual("city", _expected_dimension_from_question("2026年1月到3月，各个城市的总订单金额是多少？"))
        self.assertEqual("city", _expected_dimension_from_question("哪个城市的客户贡献的总金额最高？列出前5个城市。"))
        self.assertEqual("city", _expected_dimension_from_question("请介绍一下客户订单数据的基本情况，包括总金额和城市分布。"))
        self.assertEqual("service_line", _expected_dimension_from_question("这个城市各条服务线的工单数量分布如何？"))
        self.assertEqual("city", _expected_dimension_from_question("哪个月份的销售额最高？请列出前3名城市及其销售额。"))
        self.assertEqual("month", _expected_dimension_from_question("这个城市在2026年1月到3月的销售额趋势如何？"))
        self.assertEqual("month", _expected_dimension_from_question("销售额最高的城市是哪个？其1月到3月的月度趋势如何？"))
        self.assertEqual("month", _expected_dimension_from_question("前3名城市在2月和3月的销售额分别是多少？"))
        self.assertEqual("", _expected_dimension_from_question("2026年1月到3月的订单总金额和总利润是多少？"))
        self.assertEqual(["service_line", "city"], _expected_dimensions_from_question("按服务线分，利润率最高的城市是哪几个？"))
        self.assertEqual("product", _expected_dimension_from_question("那这个城市销售额排名第二的产品是什么？"))
        self.assertEqual("segment", _expected_dimension_from_question("这个城市在这三个月里，哪个细分市场的订单金额排名第一？"))
        self.assertEqual("segment", _expected_dimension_from_question("这个城市中，哪个客户分区的订单金额排名第一？"))
        self.assertEqual("segment", _expected_dimension_from_question("在2026年第一季度，该城市中哪个客户分段的订单金额最高？"))
        self.assertEqual("segment", _expected_dimension_from_question("在2026年2月，该城市中哪个客户段的订单金额最高？"))
        self.assertEqual("customer_id", _expected_dimension_from_question("在这段时间内，该城市排名前三的客户是哪些？"))
        self.assertEqual("customer_id", _expected_dimension_from_question("在这三个月中，哪个月份的订单金额最高？该月份的前三大客户是哪些？"))
        self.assertEqual("city", _expected_dimension_from_question("在所有城市中，2月销售额排名前三的是哪些？"))
        self.assertEqual("customer_id", _expected_dimension_from_question("在这些客户中，哪个客户的月度收入增长最快？请按增长率排序。"))
        self.assertEqual("product", _expected_dimension_from_question("在增长最快的城市中，哪个产品销售额最高？"))
        self.assertEqual("service_line", _expected_dimension_from_question("利润率最高的城市，其各服务线的利润率排名如何？"))

    def test_expected_dimension_preserves_explicit_uploaded_time_field_for_trend(self) -> None:
        self.assertEqual("sign_time", _expected_dimension_from_question("按sign_time看这个指标的趋势。"))
        self.assertEqual(["sign_time"], _expected_dimensions_from_question("按sign_time看这个指标的趋势。"))
        self.assertEqual("month", _expected_dimension_from_question("按月看这个指标趋势。"))

    def test_expected_dimensions_accept_compound_distribution_targets(self) -> None:
        self.assertEqual(
            ["segment", "city"],
            _expected_dimensions_from_question("请概述订单和客户数据的基本情况，包括总订单金额、总客户数，以及各城市和客户分段的分布。"),
        )

    def test_filtered_derived_metric_ranking_is_dual_backend_consistent(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="筛选深圳城市的数据，哪个城市利润率最高？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("errors"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual({"city": "深圳"}, response["logic_form"]["filters"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertEqual("深圳", response["result"]["rows"][0]["city"])
        self.assertAlmostEqual(244 / 749, response["result"]["rows"][0]["利润率"])

    def test_contextual_metric_anomaly_followup_carries_entity_and_time_scope(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="销售额排名前3的城市是哪些？",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="排名第一的城市在2026年1月到3月的销售额趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="该城市3月份的工单量是否异常？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("outlier_count", response["logic_form"]["operation"])
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])
        self.assertEqual({"city": "深圳", "month": {"month": 3}}, response["logic_form"]["filters"])
        self.assertIn("当前筛选口径下异常值数量为 0", response["answer"])

    def test_abnormally_low_entity_followup_routes_to_quality_check_after_trend(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="上个月各城市的销售额情况怎么样？",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="销售额排名前3的城市是哪些？",
                execution_mode="dual",
            )
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这些城市的销售额在过去三个月是怎么变化的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="有没有哪个城市销售额异常低？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("outlier_count", response["logic_form"]["operation"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])

    def test_top_n_city_phrase_without_ranking_word_stays_ranking(self) -> None:
        self.assertEqual(
            "ranking",
            _turn_plan_from_generated_question("那2026年1月销售额前3的城市是哪些？", index=1).required_operation,
        )
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月哪个城市的销售额最高？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="那2026年1月销售额前3的城市是哪些？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"year": 2026, "month": 1}}, response["logic_form"]["filters"])
        self.assertEqual([{"city": "上海", "sales": 318}, {"city": "北京", "sales": 276}], response["result"]["rows"])

    def test_focus_set_rank_change_question_keeps_ranking_not_trend(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月哪个城市的销售额最高？",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                conversation_id=conversation_id,
                question="那2026年1月销售额前3的城市是哪些？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=conversation_id,
                question="这些城市在2026年2月的销售额排名有变化吗？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"year": 2026, "month": 2}}, response["logic_form"]["filters"])
        self.assertEqual(
            {"dimension": "city", "metric": "sales", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"year": 2026, "month": 1}}},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual([{"city": "上海", "sales": 245}], response["result"]["rows"])

    def test_pronoun_city_trend_and_explicit_product_profit_override_context(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年1月哪个城市的销售额最高？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="那个城市2月和3月的销售额分别是多少？",
                execution_mode="dual",
            )
            product = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="在1月销售额前3的城市中，哪个产品贡献了最多的利润？",
                execution_mode="dual",
        )

        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertEqual({"city": "上海", "month": {"month_range": [2, 3]}}, trend["logic_form"]["filters"])
        self.assertEqual("sales", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual("profit", product["logic_form"]["parameters"]["metric"])
        self.assertEqual("product", product["logic_form"]["parameters"]["dimension"])
        self.assertEqual([{"product": "云服务", "profit": 92}, {"product": "安全审计", "profit": 83}], product["result"]["rows"])

    def test_plural_city_set_followup_switches_to_product_then_profit_margin(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年1月各城市销售额排名如何？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="排名前三的城市在2月和3月的销售额趋势怎样？",
                execution_mode="dual",
            )
            product = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="在这些城市中，哪个产品销售额最高？",
                execution_mode="dual",
            )
            margin = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="那个产品的利润率是多少？",
                execution_mode="dual",
            )

        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertEqual("structured_followup_action", trend["followup_context"]["reason"])
        self.assertNotIn("在在", trend["followup_context"]["revised_question"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual({"month": {"month_range": [2, 3]}}, trend["logic_form"]["filters"])
        self.assertEqual("sales", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            {"dimension": "city", "metric": "sales", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"month": 1, "year": 2026}}},
            trend["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertTrue(product["success"], product.get("verification"))
        self.assertTrue(product["followup_context"]["is_followup"])
        self.assertEqual("product", product["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", product["logic_form"]["parameters"]["metric"])
        self.assertTrue(margin["success"], margin.get("verification"))
        self.assertEqual("利润率", margin["logic_form"]["parameters"]["metric"])
        self.assertEqual(
            {"name": "利润率", "numerator": "profit", "denominator": "sales", "formula": "sum(profit)/sum(sales)"},
            margin["logic_form"]["parameters"]["derived_metric"],
        )

    def test_month_filter_city_ranking_uses_city_dimension_and_structured_answer(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="那2月份销售额最高的城市是哪个？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"month": 2}}, response["logic_form"]["filters"])
        self.assertEqual([{"city": "深圳", "sales": 361}], response["result"]["rows"])
        self.assertIn("数据摘要（关键指标）", response["answer"])

    def test_highest_three_phrase_and_followups_keep_candidate_set(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年1月销售额最高的3个城市是哪些？",
                execution_mode="dual",
            )
            total = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="这前3个城市在2026年1月的总销售额是多少？",
                execution_mode="dual",
            )
            product = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="在这3个城市中，哪个产品销售额排名第一？",
                execution_mode="dual",
            )

        self.assertTrue(first["success"], first.get("verification"))
        self.assertEqual(3, first["logic_form"]["parameters"]["limit"])
        self.assertTrue(total["success"], total.get("verification"))
        self.assertEqual("structured_followup_action", total["followup_context"]["reason"])
        self.assertEqual("aggregation", total["logic_form"]["operation"])
        self.assertEqual(
            {"dimension": "city", "metric": "sales", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"month": 1, "year": 2026}}},
            total["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertTrue(product["success"], product.get("verification"))
        self.assertEqual("product", product["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", product["logic_form"]["parameters"]["metric"])
        self.assertNotEqual({"product": "什么"}, product["logic_form"].get("filters"))

    def test_all_cities_month_filter_ranking_keeps_city_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在所有城市中，2月份销售额排名前三的是哪些？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"month": 2}}, response["logic_form"]["filters"])

    def test_total_amount_ranking_with_customer_count_keeps_amount_primary_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="哪个城市的订单总额最高？列出前3名及其客户数量。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("ranking", response["logic_form"]["operation"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"name": "customer_count", "field": "customer_id", "aggregation": "nunique"}],
            response["logic_form"]["parameters"]["metric_specs"],
        )

    def test_amount_ranking_with_customer_total_count_wording_keeps_supplemental_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="按订单总额排名，前3的城市是哪些？它们各自的客户总数是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("ranking", response["logic_form"]["operation"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"name": "customer_count", "field": "customer_id", "aggregation": "nunique"}],
            response["logic_form"]["parameters"]["metric_specs"],
        )
        self.assertEqual(["city", "amount", "customer_count"], response["result"]["columns"])
        self.assertIn("customer_count", response["answer"])

    def test_multi_file_followup_profit_month_then_city_amount_customer_count_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="这个数据集包含哪些信息？能简单介绍一下订单和客户表吗？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="2026年1月哪个城市的订单金额最高？列出前5名。",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="这些城市的订单金额在2026年1月到3月的变化趋势如何？",
                execution_mode="dual",
            )
            profit_month = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="对于金额最高的那个城市，哪个月份的利润率最高？",
                execution_mode="dual",
            )
            city_customer_count = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="在这些城市中，按总金额排名前3的城市是哪些？它们的客户数量分别是多少？",
                execution_mode="dual",
            )

        self.assertTrue(profit_month["success"], profit_month.get("verification"))
        self.assertEqual("structured_followup_action", profit_month["followup_context"]["reason"])
        self.assertEqual("ranking", profit_month["logic_form"]["operation"])
        self.assertEqual("利润率", profit_month["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", profit_month["logic_form"]["parameters"]["dimension"])
        self.assertTrue(city_customer_count["success"], city_customer_count.get("verification"))
        self.assertEqual("ranking", city_customer_count["logic_form"]["operation"])
        self.assertEqual("amount", city_customer_count["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", city_customer_count["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"name": "customer_count", "field": "customer_id", "aggregation": "nunique"}],
            city_customer_count["logic_form"]["parameters"]["metric_specs"],
        )
        self.assertEqual(["city", "amount", "customer_count"], city_customer_count["result"]["columns"])

    def test_ranked_city_set_reference_with_numeric_limit_inherits_candidate_filter(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="先概览一下订单和客户数据。",
                execution_mode="dual",
            )
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="2026年1月收入排名前5城市是哪些？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="这前5名城市在2026年1月到3月的收入趋势如何？",
                execution_mode="dual",
            )

        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertNotEqual("self_contained_followup", trend["followup_context"]["reason"])
        self.assertEqual("aggregation", trend["logic_form"]["operation"])
        self.assertEqual("amount", trend["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            {"dimension": "city", "metric": "amount", "aggregation": "sum", "limit": 5, "sort_order": "desc", "filters": {"month": {"month": 1, "year": 2026}}},
            trend["logic_form"]["parameters"]["candidate_filter"],
        )

    def test_profit_rate_candidate_set_can_rank_top_child_within_each_parent(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在利润率最高的前3个城市中，每个城市哪个客户群的订单金额最高？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("grouped_child_ranking", response["logic_form"]["operation"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["parent_dimension"])
        self.assertEqual("segment", response["logic_form"]["parameters"]["child_dimension"])
        self.assertEqual("segment", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            {
                "dimension": "city",
                "metric": "利润率",
                "aggregation": "ratio",
                "limit": 3,
                "sort_order": "desc",
                "derived_metric": {"name": "利润率", "numerator": "profit", "denominator": "amount", "formula": "sum(profit)/sum(amount)"},
            },
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual(["city", "segment", "amount"], response["result"]["columns"])
        self.assertEqual(
            [
                {"city": "上海", "segment": "企业", "amount": 325},
                {"city": "广州", "segment": "个人", "amount": 172},
                {"city": "北京", "segment": "企业", "amount": 310},
            ],
            response["result"]["rows"],
        )

    def test_random_overview_phrasings_route_to_dataset_overview(self) -> None:
        for scenario_id, question in (
            ("multi_file_customer_revenue_agent", "从orders和customers两张表里能分析哪些数据？"),
            ("multi_file_customer_revenue_agent", "请给我一份2026年1月到3月各城市的订单收入概览。"),
            ("service_region_agent", "2026年第一季度整体销售和利润情况如何？"),
        ):
            scenario = next(item for item in builtin_scenarios() if item.scenario_id == scenario_id)
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                file_paths = _scenario_file_paths(scenario, root)
                service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
                upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
                response = service.respond_to_message(
                    dataset_id=str(upload["dataset_id"]),
                    question=question,
                    execution_mode="dual",
                )

            self.assertTrue(response["success"], response.get("errors"))
            self.assertEqual("overview", response["answer_type"])
            self.assertIn(response["debug"]["operation"], {"dataset_overview", "multi_table_dataset_overview"})

    def test_profit_margin_ranking_over_months_keeps_month_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="帮我看看2026年1月到3月各城市的销售额情况",
                execution_mode="dual",
            )
            city = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="这三个月里销售额最高的城市是哪个？",
                execution_mode="dual",
            )
            quality = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="这个城市每个月的利润数据质量怎么样？有没有缺失或异常？",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                dataset_id="",
                conversation_id=str(first["conversation_id"]),
                question="按利润率排名，这个城市各月的利润率表现如何？",
                execution_mode="dual",
            )

        self.assertTrue(city["success"], city.get("verification"))
        self.assertTrue(quality["success"], quality.get("verification"))
        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertEqual("filtered_metric_ranking", ranking["logic_form"]["operation"])
        self.assertEqual("利润率", ranking["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", ranking["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "深圳", "month": {"year": 2026, "month_range": [1, 3]}}, ranking["logic_form"]["filters"])

    def test_monthly_profit_margin_calculation_after_city_ranking_stays_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售额排名是怎样的？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="那2026年2月销售额最高的城市是哪个？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="该城市在2026年3月的销售额排名如何？",
                execution_mode="dual",
            )
            margin = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="计算该城市每个月的利润率。",
                execution_mode="dual",
            )

        self.assertTrue(margin["success"], margin.get("verification"))
        self.assertEqual("structured_followup_action", margin["followup_context"]["reason"])
        self.assertEqual("aggregation", margin["logic_form"]["operation"])
        self.assertEqual("利润率", margin["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", margin["logic_form"]["parameters"]["dimension"])

    def test_month_only_followup_and_quality_interruption_keep_dialogue_state(self) -> None:
        regional = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")
        service_region = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(regional, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市销售额排名如何？",
                execution_mode="dual",
            )
            february = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="那2026年2月呢？",
                execution_mode="dual",
            )
            top_february = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="2月销售额前三的城市是哪些？",
                execution_mode="dual",
            )

        self.assertEqual("structured_followup_action", february["followup_context"]["reason"])
        self.assertEqual("aggregation", february["logic_form"]["operation"])
        self.assertEqual({"month": {"month": 2, "year": 2026}}, february["logic_form"]["filters"])
        self.assertEqual("filtered_metric_ranking", top_february["logic_form"]["operation"])
        self.assertEqual("city", top_february["logic_form"]["parameters"]["dimension"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(service_region, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="今年1月到3月各城市的销售额和利润数据怎么样？",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="按销售额从高到低排个序，看看前3名城市是哪些？",
                execution_mode="dual",
            )
            quality = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="这些城市的数据质量怎么样，有没有缺失值或异常？",
                execution_mode="dual",
            )
            margin = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="那前3名城市各月的利润率排名是怎样的？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertTrue(quality["success"], quality.get("verification"))
        self.assertEqual("structured_followup_action", margin["followup_context"]["reason"])
        self.assertIn(margin["logic_form"]["operation"], {"ranking", "filtered_metric_ranking"})
        self.assertEqual("利润率", margin["logic_form"]["parameters"]["metric"])
        self.assertEqual("month", margin["logic_form"]["parameters"]["dimension"])

    def test_multi_entity_profit_margin_followups_preserve_entity_and_time_scope(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            top_cities = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="那么2026年第一季度销售额排名前三的城市是哪些？",
                execution_mode="dual",
            )
            best_margin = service.respond_to_message(
                conversation_id=str(top_cities["conversation_id"]),
                question="这些城市中哪个的利润率最高？",
                execution_mode="dual",
            )
            breakdown = service.respond_to_message(
                conversation_id=str(top_cities["conversation_id"]),
                question="这些城市2月份的利润率分别是多少？",
                execution_mode="dual",
            )

        self.assertEqual({"month": {"year": 2026, "month_range": [1, 3]}}, top_cities["logic_form"]["filters"])
        self.assertEqual("aggregation", breakdown["logic_form"]["operation"])
        self.assertEqual("city", breakdown["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"month": 2}}, breakdown["logic_form"]["filters"])
        self.assertEqual(
            [{"city": "上海", "利润率": 74 / 245}, {"city": "深圳", "利润率": 118 / 361}],
            breakdown["result"]["rows"],
        )
        self.assertEqual("filtered_metric_ranking", best_margin["logic_form"]["operation"])
        self.assertEqual("city", best_margin["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"year": 2026, "month_range": [1, 3]}}, best_margin["logic_form"]["filters"])

    def test_grouped_profit_margin_display_after_trend_uses_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售额情况如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="销售额最高的三个城市是哪些？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="上海在2026年头三个月的销售额趋势是怎样的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="2026年1月各城市的利润率如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertIn("按城市汇总利润率", response["followup_context"]["revised_question"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"month": 1, "year": 2026}}, response["logic_form"]["filters"])
        self.assertEqual(
            [{"city": "上海", "利润率": 42 / 180}, {"city": "北京", "利润率": 68 / 216}],
            response["result"]["rows"],
        )

    def test_self_contained_ranking_after_overview_is_not_rewritten_to_overview_metric(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            overview = service.respond_to_message(
                dataset_id=dataset_id,
                question="请给我一份客户订单收入的整体概况。",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=str(overview["conversation_id"]),
                question="基于上一步的概况，我想知道哪个城市的客户贡献的订单总金额最高？请列出前5名城市及其总金额。",
                execution_mode="dual",
            )

        self.assertIn(response["followup_context"]["reason"], {"self_contained_followup", "contextual_followup"})
        self.assertEqual("ranking", response["logic_form"]["operation"])
        self.assertEqual("amount", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"city": "上海", "amount": 325}, {"city": "北京", "amount": 310}, {"city": "深圳", "amount": 288}, {"city": "广州", "amount": 172}],
            response["result"]["rows"],
        )

    def test_growth_ranking_returns_entity_and_followup_filters_that_entity(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            growth = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="从1月到3月，销售额增长最快的城市是哪个？",
                execution_mode="dual",
            )
            product = service.respond_to_message(
                conversation_id=str(growth["conversation_id"]),
                question="在增长最快的城市中，哪种产品销售额最高？",
                execution_mode="dual",
            )

        self.assertTrue(growth["success"], growth.get("verification"))
        self.assertTrue(growth["verification"]["pandas_sql_consistent"], growth["verification"])
        self.assertEqual("growth_ranking", growth["logic_form"]["operation"])
        self.assertEqual("city", growth["logic_form"]["parameters"]["dimension"])
        self.assertEqual("sales", growth["logic_form"]["parameters"]["metric"])
        self.assertEqual({"month": {"month_range": [1, 3]}}, growth["logic_form"]["filters"])
        self.assertEqual("深圳", growth["result"]["rows"][0]["city"])
        self.assertEqual("structured_followup_action", product["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", product["logic_form"]["operation"])
        self.assertEqual({"city": "深圳", "month": {"month_range": [1, 3]}}, product["logic_form"]["filters"])
        self.assertEqual("product", product["logic_form"]["parameters"]["dimension"])
        self.assertEqual([{"product": "数据治理", "sales": 388}, {"product": "云服务", "sales": 361}], product["result"]["rows"])

    def test_explicit_metric_top_gap_followup_overrides_previous_profit_margin_context(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="哪个城市的销售额最高？",
                execution_mode="dual",
            )
            trend = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="按月份看这个指标的趋势。",
                execution_mode="dual",
            )
            margin = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="继续按城市看利润率排名前 2。",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="比较 Top 2 的销售额差距。",
                execution_mode="dual",
            )

        self.assertTrue(first["success"], first.get("verification"))
        self.assertTrue(trend["success"], trend.get("verification"))
        self.assertTrue(margin["success"], margin.get("verification"))
        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertIn("销售额排名前3", response["followup_context"]["revised_question"])
        self.assertEqual("ranking", response["logic_form"]["operation"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"city": "深圳", "sales": 749}, {"city": "上海", "sales": 563}, {"city": "北京", "sales": 276}],
            response["result"]["rows"],
        )

    def test_service_line_best_performance_routes_to_derived_metric_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="从利润率看，哪个服务线表现最好？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("ranking", response["logic_form"]["operation"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertEqual("客户成功", response["result"]["rows"][0]["service_line"])

    def test_positive_profit_filter_is_bound_before_profit_margin_service_line_ranking(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在利润为正的服务线中，哪个服务线的利润率最高？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual({"profit": {"operator": ">", "value": 0}}, response["logic_form"]["filters"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertEqual([{"service_line": "客户成功", "利润率": 0.3235294117647059}], response["result"]["rows"])

    def test_scope_city_target_service_line_keeps_answer_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="在2026年1月，所有城市中利润率排名前3的服务线是哪些？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertTrue(response["verification"]["pandas_sql_consistent"], response["verification"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertIn("service_line", response["result"]["rows"][0])

    def test_city_service_line_profit_margin_followup_then_best_line_trend(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            overview = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月，各城市的销售额和利润情况怎么样？",
                execution_mode="dual",
            )
            top_city = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="哪个城市在这三个月的总销售额最高？",
                execution_mode="dual",
            )
            city_trend = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="这个城市的销售额在1月到3月的变化趋势如何？",
                execution_mode="dual",
            )
            service_line_ranking = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="这个城市各服务线的利润率排名是怎样的？",
                execution_mode="dual",
            )
            best_line_trend = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="那利润率最高的服务线在1月到3月的利润率变化趋势呢？",
                execution_mode="dual",
            )

        self.assertTrue(top_city["success"], top_city.get("verification"))
        self.assertTrue(city_trend["success"], city_trend.get("verification"))
        self.assertTrue(service_line_ranking["success"], service_line_ranking.get("verification"))
        self.assertTrue(best_line_trend["success"], best_line_trend.get("verification"))
        self.assertEqual("structured_followup_action", service_line_ranking["followup_context"]["reason"])
        self.assertEqual("service_line", service_line_ranking["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "深圳"}, service_line_ranking["logic_form"]["filters"])
        self.assertEqual("structured_followup_action", best_line_trend["followup_context"]["reason"])
        self.assertEqual("aggregation", best_line_trend["logic_form"]["operation"])
        self.assertEqual("month", best_line_trend["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", best_line_trend["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertEqual("客户成功", best_line_trend["logic_form"]["filters"].get("service_line"))
        self.assertEqual({"month": {"month_range": [1, 3]}, "city": "深圳", "service_line": "客户成功"}, best_line_trend["logic_form"]["filters"])

    def test_rank_target_dimension_after_candidate_service_line_uses_city(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月各城市的总销售额是多少？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="销售额最高的城市是哪个？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市在2026年头三个月的销售额趋势如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="该城市各服务线的工单量占比如何？",
                execution_mode="dual",
            )
            ranking = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在工单量最多的服务线中，利润率排名前三的城市是哪些？",
                execution_mode="dual",
            )

        self.assertTrue(ranking["success"], ranking.get("verification"))
        self.assertEqual("structured_followup_action", ranking["followup_context"]["reason"])
        self.assertEqual("ranking", ranking["logic_form"]["operation"])
        self.assertEqual("利润率", ranking["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", ranking["logic_form"]["parameters"]["dimension"])

    def test_candidate_topn_followup_aggregates_requested_metric_for_candidate_set(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            ranking = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月各城市的销售额排名如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(ranking["conversation_id"]),
                question="那1月份销售额前三的城市，在2月和3月的总销售额是多少？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("month", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"month": {"month_range": [2, 3]}}, response["logic_form"]["filters"])
        self.assertEqual(
            {"dimension": "city", "metric": "sales", "aggregation": "sum", "limit": 3, "sort_order": "desc", "filters": {"month": {"month": 1, "year": 2026}}},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual([{"month": "2026-02", "sales": 245}], response["result"]["rows"])

    def test_focus_entity_rank_position_among_all_entities_uses_ranking_without_entity_filter(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月各城市的销售额情况如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="哪个城市在这三个月里销售额最高？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市上个月的利润率在全部城市中排第几？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertIn(response["followup_context"]["reason"], {"structured_followup_action", "contextual_followup"})
        self.assertIn(response["logic_form"]["operation"], {"ranking", "filtered_metric_ranking"})
        self.assertEqual("利润率", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertNotIn("city", response["logic_form"].get("filters") or {})

    def test_focus_entity_rank_position_after_scalar_followup_uses_original_entity_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "regional_performance_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月哪个城市的销售额最高？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="那这个城市2月份的销售额是多少？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="在2月份，这个城市销售额排第几？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertIn(response["logic_form"]["operation"], {"ranking", "filtered_metric_ranking"})
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"dimension": "city", "value": "上海"}, response["logic_form"]["parameters"]["rank_target"])
        self.assertEqual({"month": {"month": 2}}, response["logic_form"].get("filters") or {})
        self.assertEqual([{"city": "上海", "sales": 245, "rank": 2}], response["result"]["rows"])

    def test_monthly_ticket_anomaly_followup_routes_to_quality_operation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月各城市的销售额情况如何？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="哪个城市在这三个月里销售额最高？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市的销售额在三个月里是怎么变化的？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这个城市每个月的工单量有异常吗？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertIn(response["logic_form"]["operation"], {"outlier_count", "anomaly_rules"})
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])

    def test_negative_profit_followup_routes_to_quality_operation_not_detail_lookup(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            first = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年1月到3月各城市的销售总额是多少？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="销售最好的三个城市是哪些？",
                execution_mode="dual",
            )
            service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="排名第一的城市在这三个月里每个月的销售趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(first["conversation_id"]),
                question="这些城市中，有没有哪个月份的利润出现负值？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertIn(response["logic_form"]["operation"], {"anomaly_rules", "numeric_quality", "cleaning_policy", "quality_summary", "data_quality_report"})
        self.assertNotEqual("detail_lookup", response["logic_form"]["operation"])
        self.assertIn("负值", response["answer"])

    def test_joined_candidate_topn_followup_computes_margin_per_candidate_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            overview = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="2026年第一季度各城市的订单收入总额是多少？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                conversation_id=str(overview["conversation_id"]),
                question="收入最高的三个城市中，每个城市的利润率如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertEqual(
            {"dimension": "city", "metric": "amount", "aggregation": "sum", "limit": 3, "sort_order": "desc"},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual(["上海", "北京", "深圳"], [row["city"] for row in response["result"]["rows"]])

    def test_distribution_reasonableness_uses_metric_distribution_not_detail_lookup(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="该城市各服务线的工单量分布是否合理？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [{"service_line": "实施交付", "tickets": 112}, {"service_line": "客户成功", "tickets": 98}],
            response["result"]["rows"],
        )

    def test_distribution_reasonableness_with_anomaly_suffix_stays_grouped_aggregation(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年1月到3月各城市的服务总销售额是多少？",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="哪个城市在这三个月的销售额最高？",
                execution_mode="dual",
            )
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个城市每个月的销售额趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个城市各服务线的工单量分布是否合理？有没有异常？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])

    def test_service_line_distribution_measure_word_followup_switches_dimension(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年1月到3月各城市的销售额和利润情况如何？",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="哪个城市在这三个月里利润最高？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个城市各条服务线的工单数量分布如何？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("tickets", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("service_line", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"city": "深圳"}, response["logic_form"]["filters"])
        self.assertEqual(
            [{"service_line": "实施交付", "tickets": 44}, {"service_line": "客户成功", "tickets": 39}],
            response["result"]["rows"],
        )

    def test_extreme_month_scope_then_city_topn_uses_candidate_filter(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            response = service.respond_to_message(
                dataset_id=str(upload["dataset_id"]),
                question="哪个月份的销售额最高？请列出前3名城市及其销售额。",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("ranking", response["logic_form"]["operation"])
        self.assertEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            {"dimension": "month", "metric": "sales", "aggregation": "sum", "limit": 1, "sort_order": "desc"},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual([{"city": "深圳", "sales": 302}, {"city": "上海", "sales": 248}], response["result"]["rows"])

    def test_contextual_extreme_month_scope_then_customer_topn_keeps_city_filter(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "multi_file_customer_revenue_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            first = service.respond_to_message(
                dataset_id=dataset_id,
                question="2026年第一季度各城市的订单总金额是多少？",
                execution_mode="dual",
            )
            conversation_id = str(first["conversation_id"])
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="哪个城市的订单总金额最高？同时列出该城市的客户名称。",
                execution_mode="dual",
            )
            service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="这个城市在2026年1月至3月期间，每月的订单金额趋势如何？",
                execution_mode="dual",
            )
            response = service.respond_to_message(
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                question="在这三个月中，哪个月份的订单金额最高？该月份的前三大客户是哪些？",
                execution_mode="dual",
            )

        self.assertTrue(response["success"], response.get("verification"))
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual({"city": "上海"}, response["logic_form"]["filters"])
        self.assertEqual("customer_id", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            {"dimension": "month", "metric": "amount", "aggregation": "sum", "limit": 1, "sort_order": "desc"},
            response["logic_form"]["parameters"]["candidate_filter"],
        )
        self.assertEqual([{"customer_id": "C1", "amount": 205}], response["result"]["rows"])

    def test_sales_performance_and_grouped_share_do_not_fall_back_to_detail_lookup(self) -> None:
        scenario = next(item for item in builtin_scenarios() if item.scenario_id == "service_region_agent")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_paths = _scenario_file_paths(scenario, root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
            dataset_id = str(upload["dataset_id"])
            sales = service.respond_to_message(
                dataset_id=dataset_id,
                question="上个月各城市的销售业绩如何？",
                execution_mode="dual",
            )
            share = service.respond_to_message(
                dataset_id=dataset_id,
                question="这个城市各服务线的工单量占比如何？",
                execution_mode="dual",
            )

        self.assertTrue(sales["success"], sales.get("verification"))
        self.assertEqual("aggregation", sales["logic_form"]["operation"])
        self.assertEqual("sales", sales["logic_form"]["parameters"]["metric"])
        self.assertEqual("city", sales["logic_form"]["parameters"]["dimension"])
        self.assertTrue(share["success"], share.get("verification"))
        self.assertEqual("aggregation", share["logic_form"]["operation"])
        self.assertEqual("tickets", share["logic_form"]["parameters"]["metric"])
        self.assertEqual("service_line", share["logic_form"]["parameters"]["dimension"])
        self.assertTrue(share["logic_form"]["parameters"]["share_of_total"])

    def test_eval_classifier_accepts_grouped_derived_metric_and_quality_report_ops(self) -> None:
        grouped = _turn_plan_from_generated_question("请给我2026年1月各城市的总销售额和利润率。", index=0)
        distribution = _turn_plan_from_generated_question("这个城市各条服务线的工单数量分布如何？", index=3)
        negative = _turn_plan_from_generated_question("这些城市中，有没有哪个月份的利润出现负值？", index=4)
        change_rank = _turn_plan_from_generated_question("那么，从1月到2月，销售额变化最大的城市是哪个？", index=2)
        service_line_dimension = _expected_dimension_from_question("在2026年1月，所有城市中利润率排名前3的服务线是哪些？")
        scalar_total_dimension = _expected_dimension_from_question("刚才那个排名中，前3名城市的销售额总和是多少？")
        compound_profit_dimension = _expected_dimension_from_question("计算每个城市各月的利润率，并找出利润率最高的城市。")
        self.assertEqual("aggregation", distribution.required_operation)
        self.assertEqual("aggregation_followup", distribution.capability_family)
        issues = _llm_generated_conversation_issues(
            [
                TurnEvidence(
                    index=1,
                    question="这些数据是否存在异常或质量问题？",
                    expected_kind="quality",
                    capability_family="quality",
                    required_operation="cleaning_policy",
                    success=True,
                    answer_type="text",
                    operation="data_quality_report",
                    conversation_id="c1",
                    state_name="analysis_ready",
                    action_count=1,
                ),
                TurnEvidence(
                    index=2,
                    question="该城市各服务线的工单数量是否有异常？",
                    expected_kind="quality",
                    capability_family="quality",
                    required_operation="cleaning_policy",
                    success=True,
                    answer_type="text",
                    operation="anomaly_rules",
                    conversation_id="c1",
                    state_name="analysis_ready",
                    action_count=1,
                ),
                TurnEvidence(
                    index=3,
                    question="这些城市中，有没有哪个月份的利润出现负值？",
                    expected_kind="quality",
                    capability_family="quality",
                    required_operation="cleaning_policy",
                    success=True,
                    answer_type="cleaning_simulation",
                    operation="numeric_quality",
                    conversation_id="c1",
                    state_name="analysis_ready",
                    followup_reason="structured_followup_action",
                    action_count=1,
                ),
                TurnEvidence(
                    index=4,
                    question="按月份看这个指标的趋势",
                    expected_kind="followup_analysis",
                    capability_family="trend_followup",
                    required_operation="aggregation",
                    success=True,
                    answer_type="table",
                    operation="aggregation",
                    conversation_id="c1",
                    state_name="analysis_ready",
                    followup_reason="contextual_followup",
                    action_count=1,
                ),
            ]
        )

        self.assertEqual("aggregation", grouped.required_operation)
        self.assertEqual("growth_ranking", change_rank.required_operation)
        self.assertEqual("growth_ranking_followup", change_rank.capability_family)
        self.assertEqual("service_line", service_line_dimension)
        self.assertEqual("", scalar_total_dimension)
        self.assertEqual("city", compound_profit_dimension)
        self.assertEqual("quality", negative.expected_kind)
        self.assertEqual("cleaning_policy", negative.required_operation)
        self.assertFalse([issue for issue in issues if "operation_mismatch" in issue], issues)

    def test_eval_evidence_uses_matching_sub_result_for_compound_followup(self) -> None:
        turn = TurnPlan(
            "计算每个城市各月的利润率，并找出利润率最高的城市。",
            expected_kind="followup_analysis",
            capability_family="derived_metric_followup",
            required_operation="ranking",
        )
        response = {
            "success": True,
            "answer_type": "compound_analysis",
            "conversation_id": "c1",
            "logic_form": {"operation": "compound_followup", "parameters": {"action_count": 2}},
            "result": {
                "sub_results": [
                    {
                        "success": True,
                        "logic_form": {"operation": "aggregation", "parameters": {"metric": "利润率", "dimension": "city"}},
                    },
                    {
                        "success": True,
                        "logic_form": {"operation": "ranking", "parameters": {"metric": "利润率", "dimension": "city"}},
                    },
                ]
            },
            "current_analysis_context": {"state_name": "analysis_ready"},
            "followup_context": {"reason": "compound_followup_actions"},
        }

        evidence = _turn_evidence(2, turn, response)

        self.assertEqual("ranking", evidence.operation)
        self.assertEqual("city", evidence.actual_dimension)
        self.assertEqual("利润率", evidence.actual_metric)

    def test_trend_followup_deterministic_oracle_exports_expected_result(self) -> None:
        turn = TurnPlan(
            "按月份看这个指标的趋势",
            expected_kind="followup_analysis",
            capability_family="trend_followup",
            required_operation="aggregation",
        )
        response = {
            "success": True,
            "answer": "销售额先升后降，2 月达到峰值后回落。",
            "answer_type": "table",
            "conversation_id": "conv_trend_oracle",
            "logic_form": {"operation": "aggregation", "parameters": {"metric": "sales", "dimension": "month"}},
            "result": {
                "rows": [
                    {"month": "2026-01", "sales": 396},
                    {"month": "2026-02", "sales": 550},
                    {"month": "2026-03", "sales": 482},
                ]
            },
            "debug": {"result_artifacts": {"trend_description": "先升后降"}},
            "current_analysis_context": {"state_name": "analysis_ready"},
            "followup_context": {"is_followup": True, "reason": "structured_followup_action"},
        }

        oracle = _deterministic_fixture_oracle_result(response["logic_form"], response, {}, turn=turn)

        self.assertTrue(oracle["oracle_available"])
        self.assertTrue(oracle["passed"])
        self.assertEqual("up_then_down", oracle["expected_result"]["trend_shape"])
        self.assertEqual({"month": "2026-02", "value": 550.0}, oracle["expected_result"]["peak"])
        self.assertEqual({"month": "2026-01", "value": 396.0}, oracle["expected_result"]["low"])
        self.assertEqual({"from": "2026-01", "to": "2026-02", "delta": 154.0}, oracle["expected_result"]["max_change"])
        self.assertEqual(["整体上升", "单调上升", "持续上升"], oracle["expected_result"]["forbidden_descriptions"])


if __name__ == "__main__":
    unittest.main()
