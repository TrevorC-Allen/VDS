#!/usr/bin/env python3
"""Run randomized multi-turn Agent conversation checks for uploaded datasets."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime
import html
import json
import math
import random
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.oracle_results import (
    build_oracle_result,
    oracle_multi_table_join_ranking,
    oracle_quality_field_counts,
    oracle_multi_file_dataset_overview,
    oracle_overview_schema_field_coverage,
    oracle_topn_followup_gap,
    oracle_trend_followup_series,
)
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.llm.client import LLMClient, MissingLLMConfigError, MockLLMClient, load_llm_client_from_env
from scripts.eval_gate import EvalGateConfig, build_eval_gate_result, eval_gate_markdown, metrics_from_coverage


OLD_DEMO_QUESTION_TOKENS = (
    "天然水",
    "东方树叶",
    "茶π",
    "分销金额",
    "历史分销",
    "v_trd_dist_ord_dtl",
)

OPERATION_EQUIVALENTS = {
    "dataset_overview": {"dataset_overview", "multi_table_dataset_overview", "dataset_source_overview"},
    "ranking": {"ranking", "filtered_metric_ranking"},
    "growth_ranking": {"growth_ranking"},
    "cleaning_policy": {"cleaning_policy", "quality_summary", "data_quality_report", "anomaly_rules", "outlier_count", "numeric_quality", "temporal_quality"},
}
TREND_FOLLOWUP_FORBIDDEN_DESCRIPTIONS = ("整体上升", "单调上升", "持续上升")
ANALYSIS_TURN_KINDS = {"analysis", "followup_analysis", "overview", "quality"}
ORACLE_MISSING_ISSUE_CODES = {"oracle_expected_result_missing", "oracle_actual_result_missing"}
ORACLE_MISMATCH_ISSUE_CODES = {
    "oracle_result_mismatch",
    "gap_mismatch",
    "trend_shape_mismatch",
    "overview_required_field_missing",
    "quality_field_level_missing",
}
ORACLE_FAILURE_ISSUE_CODES = ORACLE_MISSING_ISSUE_CODES | ORACLE_MISMATCH_ISSUE_CODES


@dataclass
class TurnPlan:
    question: str
    expected_kind: str = "analysis"
    capability_family: str = "analysis"
    required_operation: str = ""


@dataclass(frozen=True)
class ScenarioFamily:
    name: str
    description: str
    dataset_requirements: list[str] = field(default_factory=list)
    turn_templates: list[str] = field(default_factory=list)
    expected_contract_family: str = ""
    semantic_expectations: list[str] = field(default_factory=list)
    oracle_availability: str = "not_available"
    required_context_behavior: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ConversationScenario:
    scenario_id: str
    dataset_name: str
    capability_family: str
    turn_templates: list[TurnPlan]
    scenario_family: str = "typical"
    family_description: str = ""
    dataset_requirements: list[str] = field(default_factory=list)
    expected_contract_family: str = ""
    semantic_expectations: list[str] = field(default_factory=list)
    oracle_availability: str = "not_available"
    required_context_behavior: str = ""
    tags: list[str] = field(default_factory=list)
    required_operations: list[str] = field(default_factory=list)
    required_capability_families: list[str] = field(default_factory=list)
    min_turn_count: int = 2
    min_distinct_capability_families: int = 1
    shuffle_followups: bool = True
    files: dict[str, str] = field(default_factory=dict)
    file_paths: list[str] = field(default_factory=list)
    schema_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnEvidence:
    index: int
    question: str
    expected_kind: str
    capability_family: str
    required_operation: str
    scenario_family: str = "typical"
    answer_type: str = ""
    operation: str = ""
    conversation_id: str = ""
    state_name: str = ""
    expected_metric: str = ""
    expected_dimension: str = ""
    actual_metric: str = ""
    actual_dimension: str = ""
    followup_reason: str = ""
    action_count: int = 0
    issue_count: int = 0
    structured_answer: bool = False
    section_count: int = 0
    turn_role: str = ""
    conversation_turn: bool = False
    context_status: str = ""
    semantic_status: str = "legacy_unverified"
    contract_satisfied: bool | None = None
    contract_family: str = ""
    contract_checked: bool = False
    contract_violation_codes: list[str] = field(default_factory=list)
    contract_violation_error_codes: list[str] = field(default_factory=list)
    oracle_available: bool = False
    oracle_passed: bool | None = None
    oracle_issue_codes: list[str] = field(default_factory=list)
    oracle_issue_metadata: dict[str, Any] = field(default_factory=dict)
    expected_result: Any | None = None
    actual_result: Any | None = None
    answer_preview: str = ""
    llm_judge_failed: bool | None = None
    next_action_questions: list[str] = field(default_factory=list)
    success: bool = False


@dataclass
class ScenarioResult:
    scenario_id: str
    capability_family: str
    run_index: int
    passed: bool
    simulator_source: str
    turns: list[TurnEvidence]
    issues: list[str]
    scenario_family: str = "typical"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run randomized continuous-follow-up checks for VDS Agent behavior.")
    parser.add_argument("--seed", type=int, default=20260601)
    parser.add_argument("--scenario-count", type=int, default=0, help="Number of scenarios to sample. Use 0 to run all scenarios.")
    parser.add_argument(
        "--scenario-family",
        action="append",
        default=[],
        help="Scenario family to run. Repeat for multiple families; use 'all' for all configured families. Default keeps legacy typical scenarios.",
    )
    parser.add_argument(
        "--required-family",
        action="append",
        default=[],
        help="Required scenario family coverage for the eval gate.",
    )
    parser.add_argument("--runs-per-scenario", type=int, default=1)
    parser.add_argument("--max-followups", type=int, default=5)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument("--min-conversations", type=int, default=1)
    parser.add_argument("--min-capability-families", type=int, default=1)
    parser.add_argument("--min-followup-turns", type=int, default=1)
    parser.add_argument("--min-structured-action-turns", type=int, default=1)
    parser.add_argument("--min-structured-answer-turns", type=int, default=0)
    parser.add_argument("--max-semantic-failed-turns", type=int, default=0)
    parser.add_argument("--max-oracle-failed-turns", type=int, default=0)
    parser.add_argument("--max-legacy-unverified-rate", type=float, default=0.2)
    parser.add_argument("--files", nargs="*", help="Optional uploaded dataset files. When provided, the eval builds a dynamic scenario from their schema.")
    parser.add_argument("--dataset-name", default="uploaded_dataset")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--simulator-provider", choices=("deterministic", "mock", "env"), default="deterministic")
    parser.add_argument("--agent-provider", choices=("mock", "env"), default="mock")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "outputs" / "agent_random_eval" / datetime.now().strftime("%Y%m%d-%H%M%S")
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = run_agent_random_conversation_eval(
            seed=args.seed,
            scenario_count=args.scenario_count,
            runs_per_scenario=args.runs_per_scenario,
            max_followups=args.max_followups,
            output_dir=output_dir,
            simulator_client=_load_simulator_client(args.simulator_provider),
            simulator_source=args.simulator_provider,
            agent_client=_load_agent_client(args.agent_provider),
            input_files=[_resolve_path(path) for path in args.files or []],
            dataset_name=args.dataset_name,
            scenario_families=args.scenario_family,
            required_families=args.required_family,
            min_pass_rate=args.min_pass_rate,
            min_conversations=args.min_conversations,
            min_capability_families=args.min_capability_families,
            min_followup_turns=args.min_followup_turns,
            min_structured_action_turns=args.min_structured_action_turns,
            min_structured_answer_turns=args.min_structured_answer_turns,
            max_semantic_failed_turns=args.max_semantic_failed_turns,
            max_oracle_failed_turns=args.max_oracle_failed_turns,
            max_legacy_unverified_rate=args.max_legacy_unverified_rate,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    artifacts = write_eval_artifacts(report, output_dir)
    if args.print_summary:
        print(_summary_text(report))
        print(f"open_report={artifacts['index_html']}")
    else:
        print(
            json.dumps(
                {
                    "output_dir": str(output_dir),
                    "passed": report["passed"],
                    "gate_passed": report.get("gate_passed"),
                    "gate_failed_reasons": report.get("gate_failed_reasons"),
                    "pass_rate": report["pass_rate"],
                    "scenario_family": report.get("scenario_family"),
                    "scenario_families": report.get("scenario_families"),
                    "artifacts": artifacts,
                },
                ensure_ascii=False,
            )
        )
    if not report["passed"]:
        raise SystemExit(1)


def run_agent_random_conversation_eval(
    *,
    seed: int,
    scenario_count: int,
    max_followups: int,
    output_dir: Path,
    runs_per_scenario: int = 1,
    simulator_client: LLMClient | None = None,
    simulator_source: str = "deterministic",
    agent_client: LLMClient | None = None,
    input_files: list[Path] | None = None,
    dataset_name: str = "uploaded_dataset",
    min_pass_rate: float = 1.0,
    min_conversations: int = 1,
    min_capability_families: int = 1,
    min_followup_turns: int = 1,
    min_structured_action_turns: int = 1,
    min_structured_answer_turns: int = 0,
    max_semantic_failed_turns: int = 0,
    max_oracle_failed_turns: int = 0,
    max_legacy_unverified_rate: float = 0.2,
    scenario_families: Sequence[str] | None = None,
    required_families: Sequence[str] = (),
) -> dict[str, Any]:
    """Run randomized conversation scenarios and return a JSON-ready report."""

    started = time.perf_counter()
    rng = random.Random(seed)
    all_scenarios = (
        build_dynamic_scenarios(input_files, dataset_name=dataset_name)
        if input_files
        else _scenarios_for_requested_families(scenario_families)
    )
    selected = _sample_scenarios(all_scenarios, scenario_count, rng)
    repeat_count = max(1, int(runs_per_scenario or 1))
    results = []
    for scenario_index, scenario in enumerate(selected):
        for run_index in range(1, repeat_count + 1):
            run_suffix = "" if repeat_count == 1 else f"_run_{run_index}"
            results.append(
                run_scenario(
                    scenario,
                    seed=seed + scenario_index * 1000 + run_index - 1,
                    run_index=run_index,
                    max_followups=max_followups,
                    output_dir=output_dir / f"{scenario.scenario_id}{run_suffix}",
                    simulator_client=simulator_client,
                    simulator_source=simulator_source,
                    agent_client=agent_client or MockLLMClient(),
                )
            )
    coverage = _coverage_summary(results)
    passed_count = sum(1 for result in results if result.passed)
    pass_rate = _scenario_pass_rate(results)
    required_global_families = [] if simulator_source not in {"deterministic", "mock"} else sorted(
        {
            family
            for scenario in selected
            for family in _required_families_for_turn_budget(scenario, max_followups=max_followups)
        }
    )
    required_scenario_families = _normalize_required_scenario_families(required_families, selected)
    missing_global_families = [
        family for family in required_global_families if family not in coverage["capability_families"]
    ]
    global_issues = [f"global_missing_capability_family:{family}" for family in missing_global_families]
    if not results:
        global_issues.append("no_scenarios_selected")
    thresholds = {
        "min_pass_rate": max(0.0, min(1.0, float(min_pass_rate))),
        "min_conversations": max(1, int(min_conversations or 1)),
        "min_capability_families": max(1, int(min_capability_families or 1)),
        "min_followup_turns": max(0, int(min_followup_turns or 0)),
        "min_structured_action_turns": max(0, int(min_structured_action_turns or 0)),
        "min_structured_answer_turns": max(0, int(min_structured_answer_turns or 0)),
        "max_semantic_failed_turns": max(0, int(max_semantic_failed_turns or 0)),
        "max_oracle_failed_turns": max(0, int(max_oracle_failed_turns or 0)),
        "max_legacy_unverified_rate": max(0.0, min(1.0, float(max_legacy_unverified_rate))),
    }
    if pass_rate < thresholds["min_pass_rate"]:
        global_issues.append(f"global_pass_rate_below_threshold:{pass_rate:.4f}<{thresholds['min_pass_rate']:.4f}")
    if len(results) < thresholds["min_conversations"]:
        global_issues.append(f"global_conversation_count_below_threshold:{len(results)}<{thresholds['min_conversations']}")
    if len(coverage["capability_families"]) < thresholds["min_capability_families"]:
        global_issues.append(
            f"global_capability_family_count_below_threshold:{len(coverage['capability_families'])}<{thresholds['min_capability_families']}"
        )
    contextualized_turns = int(coverage.get("contextualized_post_initial_turns", coverage.get("followup_turns", 0)) or 0)
    if contextualized_turns < thresholds["min_followup_turns"]:
        global_issues.append(f"global_followup_turns_below_threshold:{contextualized_turns}<{thresholds['min_followup_turns']}")
    if coverage["structured_action_turns"] < thresholds["min_structured_action_turns"]:
        global_issues.append(
            f"global_structured_action_turns_below_threshold:{coverage['structured_action_turns']}<{thresholds['min_structured_action_turns']}"
        )
    if coverage["structured_answer_turns"] < thresholds["min_structured_answer_turns"]:
        global_issues.append(
            f"global_structured_answer_turns_below_threshold:{coverage['structured_answer_turns']}<{thresholds['min_structured_answer_turns']}"
        )
    transport_success_turns = sum(1 for result in results for turn in result.turns if turn.success)
    gate_result = build_eval_gate_result(
        metrics_from_coverage(
            coverage,
            transport_success_turns=transport_success_turns,
        ),
        EvalGateConfig(
            max_semantic_failed_turns=thresholds["max_semantic_failed_turns"],
            max_oracle_failed_turns=thresholds["max_oracle_failed_turns"],
            max_legacy_unverified_rate=thresholds["max_legacy_unverified_rate"],
            required_families=tuple(required_scenario_families),
        ),
    )
    for reason in gate_result["gate_failed_reasons"]:
        global_issues.append(f"eval_gate:{reason}")
    passed = passed_count == len(results) and not global_issues and bool(gate_result["gate_passed"])
    return {
        "name": "agent_random_conversation_eval",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "scenario_count": len(selected),
        "scenario_family": _selected_scenario_family_label(selected),
        "scenario_families": sorted({scenario.scenario_family for scenario in selected if scenario.scenario_family}),
        "runs_per_scenario": repeat_count,
        "conversation_count": len(results),
        "passed": passed,
        "passed_count": passed_count,
        "global_issues": global_issues,
        "gate_result": gate_result,
        "gate_passed": gate_result["gate_passed"],
        "gate_failed_reasons": gate_result["gate_failed_reasons"],
        "pass_rate": pass_rate,
        "thresholds": thresholds,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "simulator_source": simulator_source,
        "dataset_name": dataset_name,
        "input_files": [str(path) for path in input_files or []],
        "coverage": coverage,
        "family_summary": coverage.get("family_summary", {}),
        "family_coverage": gate_result.get("family_coverage", {}),
        "family_level_pass_rate": coverage.get("family_level_pass_rate", {}),
        "family_level_semantic_pass_rate": coverage.get("family_level_semantic_pass_rate", {}),
        "family_level_oracle_pass_rate": coverage.get("family_level_oracle_pass_rate", {}),
        "family_level_expected_contract_pass_rate": coverage.get("family_level_expected_contract_pass_rate", {}),
        "top_violation_codes_by_family": coverage.get("top_violation_codes_by_family", {}),
        "policy": (
            "This eval checks reusable Agent behavior: multi-turn state, structured actions, grounded success, "
            "contract-aware direct or structured answers, and no raw internal artifact leakage. Built-in scenarios use schema-randomized "
            "questions rather than prior demo questions; LLM simulator mode must generate fresh user questions from schema."
        ),
        "results": [asdict(result) for result in results],
    }


def run_scenario(
    scenario: ConversationScenario,
    *,
    seed: int,
    run_index: int = 1,
    max_followups: int,
    output_dir: Path,
    simulator_client: LLMClient | None,
    simulator_source: str,
    agent_client: LLMClient,
) -> ScenarioResult:
    """Run one uploaded-dataset conversation scenario."""

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        questions = simulate_user_turns(
            scenario,
            seed=seed,
            max_followups=max_followups,
            simulator_client=simulator_client,
            require_llm_generated=simulator_source not in {"deterministic", "mock"},
            require_structured_llm=simulator_source == "env",
        )
    except ValueError as exc:
        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            scenario_family=scenario.scenario_family,
            capability_family=scenario.capability_family,
            run_index=run_index,
            passed=False,
            simulator_source=simulator_source,
            turns=[],
            issues=[f"simulator_generation_failed:{exc}"],
        )
    issues: list[str] = []
    turns: list[TurnEvidence] = []
    with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir:
        root = Path(temp_dir)
        file_paths = _scenario_file_paths(scenario, root)
        service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=agent_client)
        upload = service.upload_datasets(file_paths, original_filenames=[path.name for path in file_paths])
        if not upload.get("success"):
            return ScenarioResult(
                scenario_id=scenario.scenario_id,
                scenario_family=scenario.scenario_family,
                capability_family=scenario.capability_family,
                run_index=run_index,
                passed=False,
                simulator_source=simulator_source,
                turns=[],
                issues=[f"upload_failed:{upload.get('errors') or upload}"],
            )
        conversation_id = ""
        uploaded_tables = service.file_store.get_tables(str(upload.get("dataset_id") or "")) or {}
        for index, turn in enumerate(questions, start=1):
            response = service.respond_to_message(
                dataset_id=str(upload.get("dataset_id") or "") if index == 1 else "",
                conversation_id=conversation_id,
                question=turn.question,
                execution_mode="dual",
            )
            if index == 1:
                conversation_id = str(response.get("conversation_id") or "")
            evidence = _turn_evidence(index, turn, response, tables=uploaded_tables)
            evidence.scenario_family = scenario.scenario_family
            turns.append(evidence)
            issues.extend(_turn_issues(index, turn, response, previous_conversation_id=conversation_id, evidence=evidence))
            if conversation_id and str(response.get("conversation_id") or "") != conversation_id:
                issues.append(f"turn_{index}:conversation_id_changed")
        scenario_passed = all(_is_turn_semantically_successful(turn) for turn in turns)
        if simulator_source in {"deterministic", "mock"}:
            issues.extend(_scenario_issues(scenario, turns))
        else:
            issues.extend(_llm_generated_conversation_issues(turns))
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        scenario_family=scenario.scenario_family,
        capability_family=scenario.capability_family,
        run_index=run_index,
        passed=scenario_passed and not issues,
        simulator_source=simulator_source,
        turns=turns,
        issues=issues,
    )


def simulate_user_turns(
    scenario: ConversationScenario,
    *,
    seed: int,
    max_followups: int,
    simulator_client: LLMClient | None = None,
    require_llm_generated: bool = False,
    require_structured_llm: bool = False,
) -> list[TurnPlan]:
    """Generate a random initial question plus follow-ups."""

    if simulator_client is not None and not isinstance(simulator_client, MockLLMClient):
        generated = _llm_simulated_turns(
            scenario,
            max_followups=max_followups,
            simulator_client=simulator_client,
            require_structured=require_structured_llm,
        )
        if generated:
            return generated
        if require_llm_generated:
            raise ValueError("LLM simulator returned no valid user questions")
    elif require_llm_generated:
        raise ValueError("LLM simulator was required but no non-mock simulator client was provided")
    return _schema_randomized_turns(scenario, seed=seed, max_followups=max_followups)


def builtin_scenarios() -> list[ConversationScenario]:
    """Return reusable synthetic scenarios that are not tied to benchmark answers."""

    return [
        ConversationScenario(
            scenario_id="regional_performance_agent",
            dataset_name="regional_performance",
            capability_family="generic_metric_ranking_followup",
            files={
                "regional_performance.csv": (
                    "month,city,product,sales,profit\n"
                    "2026-01,上海,云服务,318,92\n"
                    "2026-01,北京,安全审计,276,83\n"
                    "2026-02,上海,数据治理,245,74\n"
                    "2026-02,深圳,云服务,361,118\n"
                    "2026-03,广州,安全审计,206,59\n"
                    "2026-03,深圳,数据治理,388,126\n"
                )
            },
            turn_templates=[
                TurnPlan("", capability_family="ranking", required_operation="ranking"),
                TurnPlan("", expected_kind="followup_analysis", capability_family="trend_followup", required_operation="aggregation"),
                TurnPlan("", expected_kind="followup_analysis", capability_family="ranking_followup", required_operation="ranking"),
                TurnPlan("", expected_kind="followup_analysis", capability_family="derived_metric_followup", required_operation="ranking"),
            ],
            required_operations=["ranking"],
            required_capability_families=["ranking", "ranking_followup"],
            min_distinct_capability_families=2,
            schema_summary={
                "domain_label": "区域经营表现",
                "primary_table": {
                    "table_name": "regional_performance",
                    "metric": "sales",
                    "dimension": "city",
                    "time_column": "month",
                    "columns": ["month", "city", "product", "sales", "profit"],
                },
                "alternate_dimensions": ["product", "city"],
                "time_values": ["2026-01", "2026-02", "2026-03"],
                "derived_metric_label": "利润率",
            },
        ),
        ConversationScenario(
            scenario_id="service_region_agent",
            dataset_name="service_region_performance",
            capability_family="service_metric_followup",
            files={
                "service_metrics.csv": (
                    "month,city,service_line,sales,profit,tickets\n"
                    "2026-01,上海,实施交付,180,42,35\n"
                    "2026-01,北京,客户成功,216,68,28\n"
                    "2026-02,上海,客户成功,248,83,31\n"
                    "2026-02,深圳,实施交付,302,96,44\n"
                    "2026-03,深圳,客户成功,284,91,39\n"
                    "2026-03,北京,实施交付,198,52,33\n"
                )
            },
            turn_templates=[
                TurnPlan("", expected_kind="overview", capability_family="overview", required_operation="dataset_overview"),
                TurnPlan("", capability_family="ranking", required_operation="ranking"),
                TurnPlan("", expected_kind="followup_analysis", capability_family="trend_followup", required_operation="aggregation"),
                TurnPlan("", expected_kind="quality", capability_family="quality"),
                TurnPlan("", expected_kind="followup_analysis", capability_family="derived_metric_followup", required_operation="ranking"),
            ],
            required_operations=["dataset_overview", "ranking", "aggregation"],
            required_capability_families=["overview", "ranking", "trend_followup"],
            min_distinct_capability_families=3,
            shuffle_followups=False,
            schema_summary={
                "domain_label": "服务区域经营",
                "primary_table": {
                    "table_name": "service_metrics",
                    "metric": "sales",
                    "dimension": "city",
                    "time_column": "month",
                    "columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
                "alternate_dimensions": ["service_line", "city"],
                "time_values": ["2026-01", "2026-02", "2026-03"],
                "derived_metric_label": "利润率",
            },
        ),
        ConversationScenario(
            scenario_id="multi_file_customer_revenue_agent",
            dataset_name="multi_file_customer_revenue",
            capability_family="multi_file_join_followup",
            files={
                "orders.csv": (
                    "month,customer_id,amount,profit\n"
                    "2026-01,C1,120,38\n"
                    "2026-01,C2,310,86\n"
                    "2026-02,C1,205,64\n"
                    "2026-02,C3,172,51\n"
                    "2026-03,C4,288,79\n"
                ),
                "customers.csv": (
                    "customer_id,city,segment\n"
                    "C1,上海,企业\n"
                    "C2,北京,企业\n"
                    "C3,广州,个人\n"
                    "C4,深圳,企业\n"
                ),
            },
            turn_templates=[
                TurnPlan("", expected_kind="overview", capability_family="multi_file_overview", required_operation="dataset_overview"),
                TurnPlan("", capability_family="multi_table_join_ranking", required_operation="ranking"),
                TurnPlan("", expected_kind="followup_analysis", capability_family="trend_followup", required_operation="aggregation"),
                TurnPlan("", expected_kind="followup_analysis", capability_family="ranking_followup", required_operation="ranking"),
            ],
            required_operations=["dataset_overview", "ranking", "aggregation"],
            required_capability_families=["multi_file_overview", "multi_table_join_ranking", "trend_followup"],
            min_turn_count=4,
            min_distinct_capability_families=3,
            shuffle_followups=False,
            schema_summary={
                "domain_label": "客户订单收入",
                "primary_table": {
                    "table_name": "orders",
                    "metric": "amount",
                    "dimension": "city",
                    "time_column": "month",
                    "columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
                "alternate_dimensions": ["segment", "city"],
                "derived_metric_label": "利润率",
                "join_hint": "orders.customer_id = customers.customer_id",
                "time_values": ["2026-01", "2026-02", "2026-03"],
            },
        ),
    ]


def scenario_family_catalog() -> dict[str, ScenarioFamily]:
    """Return the configured random-eval scenario family metadata."""

    return {
        "single_file_overview_topn_gap": ScenarioFamily(
            name="single_file_overview_topn_gap",
            description="Single-file overview followed by TopN, share, gap, and calculation-process follow-ups.",
            dataset_requirements=["one tabular file", "categorical dimension", "numeric metric"],
            turn_templates=["overview", "topn", "share", "gap", "calculation_process"],
            expected_contract_family="topn_gap",
            semantic_expectations=["topn_rows", "metric_values_present", "gap_pairwise_or_adjacent", "direct_answer_first"],
            oracle_availability="deterministic for topn/share/gap fixture turns when result artifacts are available",
            required_context_behavior="Follow-ups must inherit the TopN candidate set and metric.",
            tags=["single_file", "topn", "gap", "share", "followup"],
        ),
        "multi_file_overview_join_analysis": ScenarioFamily(
            name="multi_file_overview_join_analysis",
            description="Multi-file overview, join-key discovery, cross-table ranking, object drilldown, and metric-definition challenge.",
            dataset_requirements=["two related files", "join key", "numeric fact metric", "dimension table"],
            turn_templates=["multi_file_overview", "join_key", "cross_table_analysis", "object_drilldown", "metric_definition_challenge"],
            expected_contract_family="multi_file_join",
            semantic_expectations=["all_files_covered", "join_key_evidence", "cross_table_result", "metric_definition_explained"],
            oracle_availability="deterministic for fixture join ranking and overview coverage",
            required_context_behavior="Follow-ups must keep the joined table scope and referenced object.",
            tags=["multi_file", "join", "overview", "drilldown"],
        ),
        "data_quality_diagnosis": ScenarioFamily(
            name="data_quality_diagnosis",
            description="Data quality diagnosis across field-level issues, duplicates, missingness, anomalies, impact, and remediation.",
            dataset_requirements=["tabular file", "fields suitable for missing/duplicate/outlier checks"],
            turn_templates=["quality_overview", "worst_fields", "duplicates_missing_outliers", "analysis_impact", "repair_plan"],
            expected_contract_family="data_quality",
            semantic_expectations=["field_level_quality_evidence", "duplicate_check", "outlier_or_rule_risk", "impact_analysis"],
            oracle_availability="deterministic for field-level quality fixture turns",
            required_context_behavior="Follow-ups must keep the diagnosed dataset and field-level evidence.",
            tags=["quality", "duplicates", "missing", "outliers"],
        ),
        "time_trend_anomaly": ScenarioFamily(
            name="time_trend_anomaly",
            description="Time-series trend, growth, anomaly month, cause drilldown, and time-filter follow-ups.",
            dataset_requirements=["time column", "numeric metric", "dimension for drilldown"],
            turn_templates=["trend", "growth", "anomaly", "cause_drilldown", "time_filter"],
            expected_contract_family="trend_anomaly",
            semantic_expectations=["time_field_detected", "trend_series", "anomaly_evidence", "time_filter_definition"],
            oracle_availability="deterministic for fixture trend series when time values match schema",
            required_context_behavior="Follow-ups must preserve metric and time grain unless explicitly changed.",
            tags=["trend", "anomaly", "time_filter"],
        ),
        "group_comparison_share": ScenarioFamily(
            name="group_comparison_share",
            description="Grouped comparison across region/channel/customer type with TopN, share, tail objects, and gap follow-ups.",
            dataset_requirements=["categorical group field", "numeric metric"],
            turn_templates=["groupby", "topn", "share", "bottom", "gap"],
            expected_contract_family="group_share_gap",
            semantic_expectations=["groupby_correct", "share_ratio_correct", "top_bottom_switch", "gap_output"],
            oracle_availability="deterministic for fixture grouped ranking/share turns",
            required_context_behavior="Follow-ups must keep the active group dimension and switch top/bottom only when requested.",
            tags=["groupby", "share", "topn", "bottom", "gap"],
        ),
        "ambiguous_user_language": ScenarioFamily(
            name="ambiguous_user_language",
            description="Colloquial, partial-field, typo, and omitted-subject questions that require inheritance or clarification.",
            dataset_requirements=["fields with likely aliases", "prior context for omitted-subject follow-ups"],
            turn_templates=["colloquial_question", "partial_field_name", "typo", "omitted_subject", "clarify_or_inherit"],
            expected_contract_family="ambiguous_language",
            semantic_expectations=["alias_or_fuzzy_match", "context_inheritance", "clarify_when_required", "no_ungrounded_calculation"],
            oracle_availability="partial; deterministic gate focuses on context and operation evidence",
            required_context_behavior="Ambiguous follow-ups must inherit prior context or ask for clarification.",
            tags=["ambiguity", "alias", "fuzzy", "clarification"],
        ),
        "metric_switching": ScenarioFamily(
            name="metric_switching",
            description="Switch metric from sales to profit to order count, then explain why rankings changed.",
            dataset_requirements=["at least two numeric metrics", "countable rows or order count"],
            turn_templates=["sales_ranking", "profit_ranking", "order_count_ranking", "explain_change"],
            expected_contract_family="metric_switching",
            semantic_expectations=["metric_recomputed_after_switch", "old_metric_not_reused", "metric_definition_change_explained"],
            oracle_availability="partial; deterministic gate focuses on metric and operation evidence",
            required_context_behavior="Metric switches must replace the active metric instead of silently reusing the previous one.",
            tags=["metric_switch", "ranking", "explanation"],
        ),
    }


def scenario_family_scenarios() -> list[ConversationScenario]:
    """Return all configured scenario-family conversations."""

    return [
        _scenario_from_family(
            ConversationScenario(
                scenario_id="family_single_file_overview_topn_gap",
                dataset_name="regional_performance",
                capability_family="single_file_topn_gap_followup",
                scenario_family="single_file_overview_topn_gap",
                files={
                    "regional_performance.csv": (
                        "month,city,product,sales,profit\n"
                        "2026-01,上海,云服务,318,92\n"
                        "2026-01,北京,安全审计,276,83\n"
                        "2026-02,上海,数据治理,245,74\n"
                        "2026-02,深圳,云服务,361,118\n"
                        "2026-03,广州,安全审计,206,59\n"
                        "2026-03,深圳,数据治理,388,126\n"
                    )
                },
                turn_templates=[
                    TurnPlan("请先概览这份区域经营数据。", expected_kind="overview", capability_family="overview", required_operation="dataset_overview"),
                    TurnPlan("按城市看销售额排名前 3。", capability_family="ranking", required_operation="ranking"),
                    TurnPlan("Top 3 城市销售额占比是多少？", expected_kind="followup_analysis", capability_family="share_followup", required_operation="top_k_share"),
                    TurnPlan("比较 Top 3 城市之间的销售额差距。", expected_kind="followup_analysis", capability_family="ranking_followup", required_operation="ranking"),
                    TurnPlan("这个差距的计算过程是什么？", expected_kind="followup_analysis", capability_family="ranking_followup"),
                ],
                required_operations=["dataset_overview", "ranking", "top_k_share"],
                required_capability_families=["overview", "ranking", "share_followup", "ranking_followup"],
                min_turn_count=5,
                min_distinct_capability_families=4,
                shuffle_followups=False,
                schema_summary=_regional_schema_summary(),
            )
        ),
        _scenario_from_family(
            ConversationScenario(
                scenario_id="family_multi_file_overview_join_analysis",
                dataset_name="multi_file_customer_revenue",
                capability_family="multi_file_join_followup",
                scenario_family="multi_file_overview_join_analysis",
                files={
                    "orders.csv": (
                        "month,customer_id,amount,profit\n"
                        "2026-01,C1,120,38\n"
                        "2026-01,C2,310,86\n"
                        "2026-02,C1,205,64\n"
                        "2026-02,C3,172,51\n"
                        "2026-03,C4,288,79\n"
                    ),
                    "customers.csv": (
                        "customer_id,city,segment\n"
                        "C1,上海,企业\n"
                        "C2,北京,企业\n"
                        "C3,广州,个人\n"
                        "C4,深圳,企业\n"
                    ),
                },
                turn_templates=[
                    TurnPlan("请概览订单和客户两个文件的结构。", expected_kind="overview", capability_family="multi_file_overview", required_operation="dataset_overview"),
                    TurnPlan("这两个文件可以通过哪个字段关联？", expected_kind="followup_analysis", capability_family="multi_file_overview", required_operation="dataset_overview"),
                    TurnPlan("关联后按城市看订单金额排名前 3。", expected_kind="followup_analysis", capability_family="multi_table_join_ranking", required_operation="ranking"),
                    TurnPlan("排名最高的城市里，哪个客户贡献订单金额最多？", expected_kind="followup_analysis", capability_family="ranking_followup", required_operation="ranking"),
                    TurnPlan("这里的订单金额口径是什么？", expected_kind="followup_analysis", capability_family="aggregation_followup"),
                ],
                required_operations=["dataset_overview", "ranking"],
                required_capability_families=["multi_file_overview", "multi_table_join_ranking", "ranking_followup"],
                min_turn_count=5,
                min_distinct_capability_families=3,
                shuffle_followups=False,
                schema_summary=_multi_file_customer_schema_summary(),
            )
        ),
        _scenario_from_family(
            ConversationScenario(
                scenario_id="family_data_quality_diagnosis",
                dataset_name="service_region_performance",
                capability_family="data_quality_diagnosis",
                scenario_family="data_quality_diagnosis",
                files=_service_region_files(),
                turn_templates=[
                    TurnPlan("这批服务区域数据质量怎么样？", expected_kind="quality", capability_family="quality", required_operation="cleaning_policy"),
                    TurnPlan("哪些字段的问题最大？", expected_kind="followup_analysis", capability_family="quality", required_operation="cleaning_policy"),
                    TurnPlan("有没有重复、缺失或异常值？", expected_kind="followup_analysis", capability_family="quality", required_operation="cleaning_policy"),
                    TurnPlan("这些问题会影响哪些分析？", expected_kind="followup_analysis", capability_family="quality", required_operation="cleaning_policy"),
                    TurnPlan("应该怎么修复这些数据问题？", expected_kind="followup_analysis", capability_family="quality", required_operation="cleaning_policy"),
                ],
                required_operations=["cleaning_policy"],
                required_capability_families=["quality"],
                min_turn_count=5,
                min_distinct_capability_families=1,
                shuffle_followups=False,
                schema_summary=_service_region_schema_summary(),
            )
        ),
        _scenario_from_family(
            ConversationScenario(
                scenario_id="family_time_trend_anomaly",
                dataset_name="regional_performance",
                capability_family="time_trend_anomaly",
                scenario_family="time_trend_anomaly",
                files=builtin_scenarios()[0].files,
                turn_templates=[
                    TurnPlan("按月份看销售额趋势。", capability_family="trend", required_operation="aggregation"),
                    TurnPlan("环比变化最大的是哪个月份？", expected_kind="followup_analysis", capability_family="trend_followup", required_operation="aggregation"),
                    TurnPlan("哪个月份看起来异常？", expected_kind="followup_analysis", capability_family="trend_followup", required_operation="aggregation"),
                    TurnPlan("异常月份主要由哪个产品造成？", expected_kind="followup_analysis", capability_family="generic_dimension_switch", required_operation="ranking"),
                    TurnPlan("只看 2026-02 到 2026-03 这段时间。", expected_kind="followup_analysis", capability_family="trend_followup", required_operation="aggregation"),
                ],
                required_operations=["aggregation", "ranking"],
                required_capability_families=["trend", "trend_followup", "generic_dimension_switch"],
                min_turn_count=5,
                min_distinct_capability_families=3,
                shuffle_followups=False,
                schema_summary=_regional_schema_summary(),
            )
        ),
        _scenario_from_family(
            ConversationScenario(
                scenario_id="family_group_comparison_share",
                dataset_name="service_region_performance",
                capability_family="group_comparison_share",
                scenario_family="group_comparison_share",
                files=_service_region_files(),
                turn_templates=[
                    TurnPlan("按服务线分组看销售额表现。", capability_family="aggregation", required_operation="aggregation"),
                    TurnPlan("服务线销售额 Top 3 是哪些？", expected_kind="followup_analysis", capability_family="ranking_followup", required_operation="ranking"),
                    TurnPlan("这些 Top 服务线的销售额占比是多少？", expected_kind="followup_analysis", capability_family="share_followup", required_operation="top_k_share"),
                    TurnPlan("尾部服务线是哪几个？", expected_kind="followup_analysis", capability_family="ranking_followup", required_operation="ranking"),
                    TurnPlan("头部和尾部差距有多大？", expected_kind="followup_analysis", capability_family="ranking_followup", required_operation="ranking"),
                ],
                required_operations=["aggregation", "ranking", "top_k_share"],
                required_capability_families=["aggregation", "ranking_followup", "share_followup"],
                min_turn_count=5,
                min_distinct_capability_families=3,
                shuffle_followups=False,
                schema_summary=_service_region_schema_summary(),
            )
        ),
        _scenario_from_family(
            ConversationScenario(
                scenario_id="family_ambiguous_user_language",
                dataset_name="regional_performance",
                capability_family="ambiguous_user_language",
                scenario_family="ambiguous_user_language",
                files=builtin_scenarios()[0].files,
                turn_templates=[
                    TurnPlan("哪个城市卖得最好？", capability_family="ranking", required_operation="ranking"),
                    TurnPlan("那利润呢？", expected_kind="followup_analysis", capability_family="derived_metric_followup", required_operation="ranking"),
                    TurnPlan("按产品拆一下刚才那个。", expected_kind="followup_analysis", capability_family="generic_dimension_switch", required_operation="ranking"),
                    TurnPlan("这个差距怎么算？", expected_kind="followup_analysis", capability_family="ranking_followup"),
                    TurnPlan("如果字段口径不清楚，先说明需要澄清什么。", expected_kind="followup_analysis", capability_family="llm_followup"),
                ],
                required_operations=["ranking"],
                required_capability_families=["ranking", "derived_metric_followup", "generic_dimension_switch"],
                min_turn_count=5,
                min_distinct_capability_families=3,
                shuffle_followups=False,
                schema_summary=_regional_schema_summary(),
            )
        ),
        _scenario_from_family(
            ConversationScenario(
                scenario_id="family_metric_switching",
                dataset_name="service_region_performance",
                capability_family="metric_switching",
                scenario_family="metric_switching",
                files=_service_region_files(),
                turn_templates=[
                    TurnPlan("先按城市看销售额排名前 3。", capability_family="ranking", required_operation="ranking"),
                    TurnPlan("再改成按利润排名。", expected_kind="followup_analysis", capability_family="generic_dimension_switch", required_operation="ranking"),
                    TurnPlan("再改成按工单数排名。", expected_kind="followup_analysis", capability_family="generic_dimension_switch", required_operation="ranking"),
                    TurnPlan("为什么排名会变化？", expected_kind="followup_analysis", capability_family="aggregation_followup"),
                ],
                required_operations=["ranking"],
                required_capability_families=["ranking", "generic_dimension_switch"],
                min_turn_count=4,
                min_distinct_capability_families=2,
                shuffle_followups=False,
                schema_summary=_service_region_schema_summary(),
            )
        ),
    ]


def _scenario_from_family(scenario: ConversationScenario) -> ConversationScenario:
    family = scenario_family_catalog()[scenario.scenario_family]
    scenario.family_description = family.description
    scenario.dataset_requirements = list(family.dataset_requirements)
    scenario.expected_contract_family = family.expected_contract_family
    scenario.semantic_expectations = list(family.semantic_expectations)
    scenario.oracle_availability = family.oracle_availability
    scenario.required_context_behavior = family.required_context_behavior
    scenario.tags = list(family.tags)
    return scenario


def _regional_schema_summary() -> dict[str, Any]:
    return {
        "domain_label": "区域经营表现",
        "primary_table": {
            "table_name": "regional_performance",
            "metric": "sales",
            "dimension": "city",
            "time_column": "month",
            "columns": ["month", "city", "product", "sales", "profit"],
        },
        "alternate_dimensions": ["product", "city"],
        "time_values": ["2026-01", "2026-02", "2026-03"],
        "derived_metric_label": "利润率",
    }


def _service_region_files() -> dict[str, str]:
    return {
        "service_metrics.csv": (
            "month,city,service_line,sales,profit,tickets\n"
            "2026-01,上海,实施交付,180,42,35\n"
            "2026-01,北京,客户成功,216,68,28\n"
            "2026-02,上海,客户成功,248,83,31\n"
            "2026-02,深圳,实施交付,302,96,44\n"
            "2026-03,深圳,客户成功,284,91,39\n"
            "2026-03,北京,实施交付,198,52,33\n"
        )
    }


def _service_region_schema_summary() -> dict[str, Any]:
    return {
        "domain_label": "服务区域经营",
        "primary_table": {
            "table_name": "service_metrics",
            "metric": "sales",
            "dimension": "city",
            "time_column": "month",
            "columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
        },
        "alternate_dimensions": ["service_line", "city"],
        "time_values": ["2026-01", "2026-02", "2026-03"],
        "derived_metric_label": "利润率",
    }


def _multi_file_customer_schema_summary() -> dict[str, Any]:
    return {
        "domain_label": "客户订单收入",
        "primary_table": {
            "table_name": "orders",
            "metric": "amount",
            "dimension": "city",
            "time_column": "month",
            "columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
        },
        "alternate_dimensions": ["segment", "city"],
        "derived_metric_label": "利润率",
        "join_hint": "orders.customer_id = customers.customer_id",
        "time_values": ["2026-01", "2026-02", "2026-03"],
    }


def _scenarios_for_requested_families(requested: Sequence[str] | None) -> list[ConversationScenario]:
    names = _normalize_requested_family_names(requested)
    if not names:
        return builtin_scenarios()
    if "all" in names:
        return scenario_family_scenarios()
    scenarios_by_family: dict[str, list[ConversationScenario]] = {"typical": builtin_scenarios()}
    for scenario in scenario_family_scenarios():
        scenarios_by_family.setdefault(scenario.scenario_family, []).append(scenario)
    known = sorted(scenarios_by_family)
    unknown = [name for name in names if name not in scenarios_by_family]
    if unknown:
        raise ValueError(f"Unknown scenario family: {', '.join(unknown)}. Known families: {', '.join(['all', *known])}")
    selected: list[ConversationScenario] = []
    seen: set[str] = set()
    for name in names:
        for scenario in scenarios_by_family.get(name, []):
            if scenario.scenario_id in seen:
                continue
            selected.append(scenario)
            seen.add(scenario.scenario_id)
    return selected


def _normalize_requested_family_names(requested: Sequence[str] | None) -> list[str]:
    names: list[str] = []
    for value in requested or []:
        for item in str(value or "").split(","):
            name = item.strip()
            if name:
                names.append(name)
    return names


def _normalize_required_scenario_families(required: Sequence[str], selected: Sequence[ConversationScenario]) -> list[str]:
    names = _normalize_requested_family_names(required)
    if any(name == "all" for name in names):
        return sorted({scenario.scenario_family for scenario in selected if scenario.scenario_family})
    return sorted(set(names))


def _selected_scenario_family_label(selected: Sequence[ConversationScenario]) -> str:
    families = sorted({scenario.scenario_family for scenario in selected if scenario.scenario_family})
    if not families:
        return "not_available"
    if len(families) == 1:
        return families[0]
    return "multiple"


def build_dynamic_scenarios(input_files: list[Path] | None, *, dataset_name: str) -> list[ConversationScenario]:
    """Build a schema-driven scenario from real uploaded files."""

    files = [Path(path) for path in input_files or []]
    if not files:
        return []
    with tempfile.TemporaryDirectory() as temp_dir:
        service = DataAgentService(file_store=TempFileStore(Path(temp_dir) / "storage"), llm_client=MockLLMClient())
        upload = service.upload_datasets(files, original_filenames=[path.name for path in files])
        if not upload.get("success"):
            raise RuntimeError(f"Could not upload files for dynamic agent eval: {upload.get('errors') or upload}")
        tables = service.file_store.get_tables(str(upload.get("dataset_id") or "")) or {}
        schema = _schema_summary_from_tables(tables, files)
    primary = schema.get("primary_table") if isinstance(schema.get("primary_table"), dict) else {}
    metric = str(primary.get("metric") or "")
    dimension = str(primary.get("dimension") or "")
    time_column = str(primary.get("time_column") or "")
    turns: list[TurnPlan] = [
        TurnPlan("看一下这个数据。", expected_kind="overview", capability_family="overview"),
        TurnPlan("有没有明显的数据质量问题？", expected_kind="quality", capability_family="quality"),
    ]
    required_operations: list[str] = []
    required_capability_families: list[str] = ["overview", "quality"]
    if metric and dimension:
        turns.append(
            TurnPlan(
                f"哪个{_field_label(dimension)}的{_field_label(metric)}最高？",
                capability_family="ranking",
                required_operation="ranking",
            )
        )
        required_operations.append("ranking")
        required_capability_families.append("ranking")
        turns.append(
            TurnPlan(
                "比较 Top 结果之间的差距",
                expected_kind="followup_analysis",
                capability_family="ranking_followup",
                required_operation="ranking",
            )
        )
        required_capability_families.append("ranking_followup")
    if _has_columns(primary, "profit", "sales"):
        turns.append(
            TurnPlan(
                "利润率也重新看一下",
                expected_kind="followup_analysis",
                capability_family="derived_metric_followup",
                required_operation="ranking",
            )
        )
        required_capability_families.append("derived_metric_followup")
    if time_column and metric:
        turns.append(
            TurnPlan(
                f"按{_field_label(time_column)}看这个指标的趋势",
                expected_kind="followup_analysis" if metric and dimension else "analysis",
                capability_family="trend_followup" if metric and dimension else "trend",
                required_operation="aggregation",
            )
        )
        required_operations.append("aggregation")
        required_capability_families.append("trend_followup" if metric and dimension else "trend")
    if metric and not any(turn.capability_family in {"ranking_followup", "trend_followup", "derived_metric_followup"} for turn in turns):
        turns.append(
            TurnPlan(
                f"继续看{_field_label(metric)}有没有明显异常",
                expected_kind="followup_analysis",
                capability_family="quality_followup",
            )
        )
        required_capability_families.append("quality_followup")
    scenario_id = "dynamic_" + _safe_id(dataset_name or files[0].stem or "uploaded_dataset")
    return [
        ConversationScenario(
            scenario_id=scenario_id,
            dataset_name=dataset_name,
            capability_family="dynamic_uploaded_schema_agent",
            scenario_family="dynamic_uploaded_schema",
            family_description="Schema-driven uploaded-file scenario built from the provided files.",
            dataset_requirements=["user-provided uploaded files"],
            expected_contract_family="dynamic_uploaded_schema",
            semantic_expectations=["overview_or_quality", "schema_grounded_ranking_or_trend_when_available"],
            oracle_availability="depends on uploaded schema and generated operations",
            required_context_behavior="Follow-ups must inherit the uploaded dataset and active metric/dimension.",
            tags=["dynamic", "uploaded_files"],
            turn_templates=turns,
            required_operations=required_operations,
            required_capability_families=list(dict.fromkeys(required_capability_families)),
            min_turn_count=min(len(turns), 4),
            min_distinct_capability_families=min(len(set(required_capability_families)), 4),
            shuffle_followups=False,
            file_paths=[str(path) for path in files],
            schema_summary=schema,
        )
    ]


def _schema_randomized_turns(scenario: ConversationScenario, *, seed: int, max_followups: int) -> list[TurnPlan]:
    rng = random.Random(seed)
    if not scenario.turn_templates:
        return []
    first = scenario.turn_templates[0]
    followups = list(scenario.turn_templates[1:])
    if scenario.shuffle_followups:
        rng.shuffle(followups)
    selected = [first, *followups[:max(0, max_followups)]]
    return [_randomized_turn_plan(scenario, plan, rng=rng, index=index) for index, plan in enumerate(selected)]


def _randomized_turn_plan(scenario: ConversationScenario, plan: TurnPlan, *, rng: random.Random, index: int) -> TurnPlan:
    question = _random_question_for_capability(scenario, plan, rng=rng, index=index)
    return TurnPlan(
        question=question,
        expected_kind=plan.expected_kind,
        capability_family=plan.capability_family,
        required_operation=plan.required_operation,
    )


def _random_question_for_capability(scenario: ConversationScenario, plan: TurnPlan, *, rng: random.Random, index: int) -> str:
    context = _question_context(scenario)
    capability = plan.capability_family
    metric = context["metric_label"]
    dimension = context["dimension_label"]
    time_column = context["time_label"]
    domain = context["domain_label"]
    alternate_dimension = context["alternate_dimension_label"]
    derived_metric = context["derived_metric_label"]
    top_n = rng.choice([2, 3, 5])
    variants: dict[str, list[str]] = {
        "overview": [
            f"请概览这批{domain}数据的结构和关键字段。",
            f"不预设结论，先概览这批{domain}数据。",
            f"帮我概览上传的{domain}数据结构和可分析方向。",
        ],
        "multi_file_overview": [
            f"请概览这批{domain}多文件数据的结构和关联字段。",
            f"不直接下结论，先概览这些{domain}文件的数据结构。",
            f"帮我概览这批{domain}上传文件能支持哪些分析。",
        ],
        "ranking": [
            f"哪个{dimension}的{metric}最高？",
            f"按{dimension}看{metric}排名前 {top_n}。",
            f"{dimension}{metric} Top {top_n} 是哪些？",
        ],
        "multi_table_join_ranking": [
            f"关联明细表和维表后，哪个{dimension}的{metric}最高？",
            f"结合相关表，按{dimension}看{metric}排名前 {top_n}。",
            f"按{dimension}汇总{metric}，Top {top_n} 是哪些？",
        ],
        "trend_followup": [
            f"按{time_column}看这个指标的趋势。",
            f"继续按{time_column}看{metric}趋势。",
            f"这些 Top 对象按{time_column}的{metric}趋势怎么样？",
        ],
        "ranking_followup": [
            f"比较 Top {top_n} 的{metric}差距。",
            f"比较 Top {dimension}之间的差距。",
            f"前 {top_n} 名{dimension}之间差距有多大？",
        ],
        "share_followup": [
            f"这些 Top {dimension}的{metric}分别占总{metric}多少？",
            f"Top {top_n} {dimension}的{metric}贡献占比是多少？",
            f"刚才这些 Top {dimension}各自的{metric}份额是多少？",
        ],
        "derived_metric_followup": [
            f"{derived_metric}也重新看一下。",
            f"按{dimension}看{derived_metric}排名前 {top_n}。",
            f"继续按{dimension}看{derived_metric}排名前 {top_n}。",
        ],
        "quality": [
            f"先检查这批{domain}数据有没有缺失、重复或明显异常。",
            f"这批{domain}数据质量怎么样，有没有会影响分析的问题？",
            f"做分析前先看数据质量，重点查缺失、重复和异常值。",
        ],
    }
    if capability.endswith("_followup") and capability not in variants:
        variants[capability] = [
            f"继续沿用上面的口径，换到{alternate_dimension}维度再看一遍。",
            f"基于刚才结果，进一步拆到{alternate_dimension}看看来源。",
        ]
    choices = variants.get(capability) or variants.get(plan.required_operation) or []
    if not choices and plan.question:
        choices = [plan.question]
    if not choices:
        choices = [f"围绕{domain}数据继续做一个{capability}分析。"]
    question = rng.choice(choices)
    return _avoid_old_demo_question(question, fallback=f"按{dimension}汇总{metric}，看主要差异。")


def _question_context(scenario: ConversationScenario) -> dict[str, str]:
    schema = scenario.schema_summary if isinstance(scenario.schema_summary, dict) else {}
    primary = schema.get("primary_table") if isinstance(schema.get("primary_table"), dict) else {}
    metric = str(primary.get("metric") or "sales")
    dimension = str(primary.get("dimension") or "city")
    time_column = str(primary.get("time_column") or "month")
    alternate_dimensions = [str(item) for item in schema.get("alternate_dimensions") or [] if str(item)]
    alternate_dimension = next((item for item in alternate_dimensions if item != dimension), dimension)
    return {
        "domain_label": str(schema.get("domain_label") or scenario.dataset_name or "业务"),
        "metric_label": _field_label(metric),
        "dimension_label": _field_label(dimension),
        "time_label": _field_label(time_column),
        "alternate_dimension_label": _field_label(alternate_dimension),
        "derived_metric_label": str(schema.get("derived_metric_label") or "利润率"),
    }


def _avoid_old_demo_question(question: str, *, fallback: str) -> str:
    if any(token in question for token in OLD_DEMO_QUESTION_TOKENS):
        return fallback
    return question


def _llm_simulated_turns(
    scenario: ConversationScenario,
    *,
    max_followups: int,
    simulator_client: LLMClient,
    require_structured: bool = False,
) -> list[TurnPlan]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是 VDS 随机用户模拟器，只生成用户会问的问题，不生成答案。"
                "问题必须基于给定字段和能力族，包含一个初始问题和连续追问。"
                "默认使用中文提问。"
                "每一轮都要像真实业务用户临场提问，不能照抄模板、不能复用历史演示题或固定商品案例。"
                "追问必须自然继承上一轮上下文，例如沿用刚才的 Top 对象、口径、指标或时间范围。"
                "如果 schema_summary 提供 time_values 或时间范围，只能使用这些时间值，不能发明其他年份、月份或季度。"
                "不要包含 task_id、标准答案、评分规则、raw prompt 或任何后端内部信息。只返回 JSON。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "simulate_random_user_conversation",
                    "scenario_id": scenario.scenario_id,
                    "scenario_family": scenario.scenario_family,
                    "scenario_family_description": scenario.family_description,
                    "dataset_requirements": scenario.dataset_requirements,
                    "expected_contract_family": scenario.expected_contract_family,
                    "semantic_expectations": scenario.semantic_expectations,
                    "oracle_availability": scenario.oracle_availability,
                    "required_context_behavior": scenario.required_context_behavior,
                    "tags": scenario.tags,
                    "dataset_files": _scenario_file_names(scenario),
                    "schema_summary": scenario.schema_summary,
                    "capability_family": scenario.capability_family,
                    "required_capability_families": scenario.required_capability_families,
                    "min_turn_count": scenario.min_turn_count,
                    "min_distinct_capability_families": scenario.min_distinct_capability_families,
                    "capability_plan": [
                        {
                            "turn_role": "initial" if index == 0 else "followup",
                            "expected_kind": turn.expected_kind,
                            "capability_family": turn.capability_family,
                            "required_operation": turn.required_operation,
                        }
                        for index, turn in enumerate(scenario.turn_templates)
                    ],
                    "randomization_rules": [
                        "Do not copy any benchmark/demo wording.",
                        "Follow capability_plan in order. Do not skip, replace, or reorder required capability families.",
                        "Use the schema fields and business domain to vary metric, dimension, time grain, Top-N, comparison, share, trend, quality, and derived-metric questions.",
                        "Use only time values present in schema_summary.time_values when asking time-scoped questions.",
                        "Follow-ups should be short and contextual, not independent new tasks.",
                    ],
                    "required_output": {
                        "turns": [
                            {
                                "question": "short user question",
                                "expected_kind": "copy from capability_plan",
                                "capability_family": "copy from capability_plan",
                                "required_operation": "copy from capability_plan",
                            }
                        ],
                        "max_turn_count": max_followups + 1,
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = simulator_client.complete_json(messages, temperature=0.7)
    structured_turns = raw.get("turns")
    if isinstance(structured_turns, list):
        turns = [
            turn
            for index, item in enumerate(structured_turns[: max(1, max_followups + 1)])
            if (turn := _turn_plan_from_llm_item(item, index=index, scenario=scenario))
        ]
        if turns:
            return turns
    if require_structured:
        raise ValueError("LLM simulator must return required_output.turns with at least one valid user question")
    initial = _safe_question(raw.get("initial_question"))
    followups = [_safe_question(item) for item in raw.get("followups") or []]
    followups = [item for item in followups if item][:max_followups]
    if not initial:
        return []
    return [
        _turn_plan_from_generated_question(initial, index=0),
        *[_turn_plan_from_generated_question(item, index=index) for index, item in enumerate(followups, start=1)],
    ]


def _turn_plan_from_llm_item(item: Any, *, index: int, scenario: ConversationScenario | None = None) -> TurnPlan | None:
    if isinstance(item, dict):
        question = _safe_question(item.get("question") or item.get("user_question"))
        if not question:
            return None
        inferred = _turn_plan_from_generated_question(question, index=index)
        declared_kind = str(item.get("expected_kind") or "")
        declared_family = str(item.get("capability_family") or "")
        declared_operation = str(item.get("required_operation") or "")
        inferred_family_is_specific = inferred.capability_family not in {"analysis", "llm_followup"}
        required_operation = inferred.required_operation or declared_operation
        if not required_operation and (declared_kind == "quality" or declared_family == "quality"):
            required_operation = "cleaning_policy"
        return TurnPlan(
            question=question,
            expected_kind=inferred.expected_kind if inferred_family_is_specific else declared_kind or inferred.expected_kind,
            capability_family=inferred.capability_family if inferred_family_is_specific else declared_family or inferred.capability_family,
            required_operation=required_operation,
        )
    question = _safe_question(item)
    return _turn_plan_from_generated_question(question, index=index) if question else None


def _turn_plan_from_generated_question(question: str, *, index: int) -> TurnPlan:
    compact = "".join(str(question or "").split())
    lowered = str(question or "").lower()
    compact_lower = compact.lower()
    expected_kind = "analysis" if index == 0 else "followup_analysis"
    top_set_metric_display = any(token in compact for token in ("前3", "前三", "前5", "前五", "排名前")) and any(
        token in compact for token in ("是多少", "有多少", "多少", "分别", "如何", "怎么样")
    ) and any(
        token in compact for token in ("销售额", "销售金额", "订单金额", "订单总额", "订单总金额", "工单量", "工单数", "利润", "收入", "金额")
    )
    distribution_metric_display = "分布" in compact and any(
        token in compact for token in ("城市", "客户", "客群", "客户群", "客户细分", "服务线", "业务线", "产品", "商品")
    ) and any(token in compact for token in ("销售", "收入", "金额", "利润", "订单", "工单", "指标", "数据"))
    schema_record_overview = any(token in compact for token in ("字段", "记录数", "数据量", "行数", "表结构", "字段结构")) and any(
        token in compact for token in ("基本情况", "介绍", "概览", "概述", "总览", "看看", "看一下")
    )
    explicit_metric_total = any(
        token in compact
        for token in (
            "总金额",
            "总额",
            "总收入",
            "总利润",
            "总订单金额",
            "订单总金额",
            "订单金额",
            "客户数量",
            "总客户数",
            "销售总额",
            "销售总金额",
            "合计金额",
            "合计利润",
        )
    ) or bool(re.search(r"客户数(?!据)", compact))
    time_metric_trend = (
        any(token in compact for token in ("每月", "每个月", "各月", "各月份", "按月", "按月份", "月度"))
        and any(token in compact for token in ("销售", "收入", "金额", "利润", "订单", "工单", "票据", "指标"))
        and any(token in compact for token in ("增长", "同步增长", "趋势", "变化", "上升", "下降", "升还是降", "升降"))
    )
    multi_metric_reasonableness = (
        any(token in compact for token in ("相比", "对比", "比较", "是否合理", "合不合理", "合理"))
        and sum(
            1
            for signals in (
                ("销售额", "销售金额", "销售总额", "收入", "销售"),
                ("工单数量", "工单量", "工单数", "票据数", "工单", "票据"),
                ("利润率", "毛利率"),
                ("利润", "毛利"),
                ("订单金额", "订单总额", "订单总金额", "订单"),
            )
            if any(token in compact for token in signals)
        )
        >= 2
    )
    topn_entity_count_ranking = any(token in compact for token in ("排名前", "前3", "前三", "前5", "前五", "Top", "top")) and any(
        token in compact for token in ("客户数量", "客户数", "客户总数", "总客户数", "客户个数")
    ) and any(token in compact for token in ("城市", "客户", "产品", "服务线", "业务线", "地区", "区域"))
    if schema_record_overview and not explicit_metric_total:
        return TurnPlan(question, expected_kind="overview", capability_family="overview", required_operation="dataset_overview")
    if (
        any(token in compact for token in ("数据质量", "质量问题", "缺失", "重复", "异常", "负值", "负数", "小于0", "小于零", "低于0", "低于零"))
        or any(token in lowered for token in ("quality", "missing", "duplicate", "outlier", "anomaly"))
    ) and not distribution_metric_display and not any(token in compact for token in ("复核", "高点", "低点")):
        return TurnPlan(question, expected_kind="quality", capability_family="quality", required_operation="cleaning_policy")
    if time_metric_trend:
        return TurnPlan(question, expected_kind=expected_kind, capability_family="trend_followup" if index > 0 else "trend", required_operation="aggregation")
    if multi_metric_reasonableness:
        return TurnPlan(question, expected_kind=expected_kind, capability_family="aggregation_followup" if index > 0 else "aggregation", required_operation="aggregation")
    if topn_entity_count_ranking:
        return TurnPlan(question, expected_kind=expected_kind, capability_family="ranking_followup" if index > 0 else "ranking", required_operation="ranking")
    if (
        any(token in compact for token in ("汇总", "分组"))
        or (explicit_metric_total and any(token in compact for token in ("和", "及", "与", "以及", "、", "包括")))
        or any(token in compact for token in ("销售总额", "销售总金额", "收入总额"))
        or ("概况" in compact and any(token in compact for token in ("按城市", "按业务线", "按服务线", "按地区", "按区域")))
        or (any(token in compact for token in ("各城市", "各地区", "各区域", "各服务线", "各业务线")) and any(token in compact for token in ("总金额", "总额", "总销售额", "销售额", "销售", "总利润", "利润率", "合计", "是多少", "情况", "怎么样", "如何", "表现")))
        or (any(token in compact for token in ("各月", "每月")) and any(token in compact for token in ("总金额", "总额", "总收入", "总利润", "金额", "利润", "订单")))
        or (any(token in compact for token in ("每个城市", "每个地区", "每个区域", "每个服务线", "每个业务线")) and any(token in compact for token in ("分别", "是多少", "各自", "情况", "怎么样", "如何", "概况", "看看", "看一下", "包括")))
        or (any(token in compact for token in ("分布", "是否合理", "合理")) and any(token in compact for token in ("各城市", "各地区", "各区域", "各服务线", "各业务线", "每个城市", "每个服务线")))
        or distribution_metric_display
        or any(token in compact for token in ("平均", "均值", "中位数", "总共有多少", "一共多少", "有多少"))
        or top_set_metric_display
    ) and any(
        token in compact for token in ("销售", "收入", "金额", "利润", "指标", "数据", "订单", "客户", "记录", "工单", "票据")
    ) and (top_set_metric_display or not any(token in compact for token in ("top", "Top", "排名", "排行", "排序", "排列", "从高到低", "从低到高", "最高", "最低", "最多", "最少"))):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="aggregation_followup" if index > 0 else "aggregation", required_operation="aggregation")
    overview_signal = any(token in compact for token in ("看一下这个数据", "这个数据主要", "概览", "总结", "概况", "整体情况", "整体数据")) or any(
        token in lowered for token in ("overview", "summarize", "summary", "profile", "what can we analyze")
    )
    if overview_signal and not any(token in compact for token in ("哪个", "哪些", "哪一个", "最高", "最低", "最多", "最少", "排名", "排行", "排序", "排列", "从高到低", "从低到高", "Top", "top")):
        return TurnPlan(question, expected_kind="overview", capability_family="overview", required_operation="dataset_overview")
    candidate_scope_scalar = any(token in compact for token in ("前3", "前三", "前5", "前五", "排名前")) and any(token in compact for token in ("中", "里", "内"))
    if candidate_scope_scalar and any(token in compact for token in ("是多少", "有多少", "多少")) and any(
        token in compact for token in ("销售额", "销售金额", "订单金额", "订单总额", "订单总金额", "工单量", "工单数", "利润", "收入", "金额")
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="aggregation_followup" if index > 0 else "aggregation", required_operation="aggregation")
    if any(token in compact for token in ("是多少", "有多少", "多少")) and any(
        token in compact for token in ("销售额", "销售金额", "销售总额", "销售总金额", "订单金额", "订单总额", "订单总金额", "工单量", "工单数", "利润", "收入", "收入总额", "金额")
    ) and not any(token in compact for token in ("top", "Top", "排名", "最高", "最低", "最多", "最少", "前")):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="aggregation_followup" if index > 0 else "aggregation", required_operation="aggregation")
    if (
        "利润率" in compact
        or ("profit" in lowered and any(token in lowered for token in ("rate", "margin")))
        or "margin" in lowered
    ) and (
        any(token in compact for token in ("趋势", "变化趋势", "如何变化", "怎么变化", "怎样变化", "按月份", "月度"))
        or any(token in compact for token in ("相比", "相较", "上升", "下降", "升还是降", "升降"))
        or any(token in lowered for token in ("trend", "month by month", "monthly", "change over time"))
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="derived_metric_followup" if index > 0 else "derived_metric", required_operation="aggregation")
    contextual_top_entity_reference = any(
        token in compact
        for token in ("这些前三", "这些前3", "这些排名前三", "这些排名前3", "这3个", "这三个", "这五个", "这些Top", "这些top")
    )
    if (
        "利润率" in compact
        or ("profit" in lowered and any(token in lowered for token in ("rate", "margin")))
        or "margin" in lowered
    ) and any(token in compact for token in ("分别", "各自", "每个", "各个")) and (contextual_top_entity_reference or not any(
        token in compact for token in ("top", "Top", "排名", "最高", "最低", "最多", "最少", "前")
    )):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="derived_metric_followup" if index > 0 else "derived_metric", required_operation="aggregation")
    if (
        "利润率" in compact
        or ("profit" in lowered and any(token in lowered for token in ("rate", "margin")))
        or "margin" in lowered
    ) and any(token in compact for token in ("是多少", "多少")) and not any(
        token in compact for token in ("top", "Top", "排名", "最高", "最低", "最多", "最少", "最好", "最佳", "最优", "最差", "前")
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="derived_metric_followup" if index > 0 else "derived_metric", required_operation="aggregation")
    if "利润率" in compact or ("profit" in lowered and any(token in lowered for token in ("rate", "margin"))) or "margin" in lowered:
        return TurnPlan(question, expected_kind=expected_kind, capability_family="derived_metric_followup" if index > 0 else "derived_metric", required_operation="ranking")
    if any(token in compact for token in ("占比", "比例", "份额")) or any(token in lowered for token in ("share", "percentage", "proportion")):
        grouped_share = any(token in compact for token in ("各", "每个", "分别", "按")) or any(token in lowered for token in ("by ", "per ", "each"))
        top_share = any(token in compact for token in ("top", "Top", "前")) or "top" in lowered
        return TurnPlan(
            question,
            expected_kind=expected_kind,
            capability_family="share_followup" if index > 0 else "share",
            required_operation="aggregation" if grouped_share and not top_share else "top_k_share",
        )
    asks_growth_rank = any(
        token in compact
        for token in (
            "增长最快",
            "增长最多",
            "增速最快",
            "增幅最大",
            "提升最快",
            "提升最多",
            "下降最快",
            "下降最多",
            "变化最明显",
            "变化最大",
            "变化最多",
            "变动最大",
            "变动最多",
            "波动最大",
            "波动最多",
        )
    ) or any(
        token in lowered for token in ("fastest growth", "largest growth", "highest growth", "biggest increase", "largest increase", "fastest decline")
    )
    contextual_growth_entity = any(
        token in compact
        for token in (
            "增长最快的城市中",
            "增长最多的城市中",
            "增速最快的城市中",
            "增幅最大的城市中",
            "变化最大的城市中",
            "波动最大的城市中",
            "增长最快的那个城市里",
            "增长最快的那个城市中",
            "增长最快的城市里",
        )
    )
    asks_dimension_inside_growth_entity = any(token in compact for token in ("哪个产品", "哪种产品", "哪些产品", "哪个客户", "哪些客户", "客户细分", "客户群体", "客户分区", "客户分段", "客户段", "客群", "segment", "哪个服务线", "哪些服务线"))
    if asks_growth_rank and not (contextual_growth_entity and asks_dimension_inside_growth_entity):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="growth_ranking_followup" if index > 0 else "growth_ranking", required_operation="growth_ranking")
    if index > 0 and (
        any(
            token in compact
            for token in (
                "哪个产品",
                "哪种产品",
                "哪个客户",
                "客户是哪个",
                "利润最高的客户",
                "利润最多的客户",
                "哪个城市",
                "哪些城市",
                "哪几个城市",
                "城市是哪几个",
                "城市是哪",
                "城市有哪些",
                "几个城市",
                "哪个区域",
                "哪些区域",
                "哪几个区域",
                "哪个服务线",
                "哪些服务线",
                "哪几个服务线",
                "哪几条服务线",
                "产品贡献",
                "客户贡献",
                "城市贡献",
                "区域贡献",
                "贡献最大",
                "贡献最多",
            )
        )
        or any(
            token in lowered
            for token in (
                "which product",
                "which customer",
                "which city",
                "which region",
                "contributed most",
                "contributes most",
                "largest contribution",
                "biggest contribution",
            )
        )
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="generic_dimension_switch", required_operation="ranking")
    if any(token in compact for token in ("趋势", "按月份", "按时间", "月度", "增长率", "增长最快", "增速", "差距变化", "如何变化", "怎么变化")) or any(
        token in lowered for token in ("trend", "month by month", "monthly", "by quarter", "quarterly", "growth", "change over time")
    ) or any(
        pattern in compact_lower for pattern in ("bymonth", "byquarter")
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="trend_followup" if index > 0 else "trend", required_operation="aggregation")
    if index > 0 and (
        any(
            token in compact
            for token in (
                "按产品",
                "按客户",
                "按城市",
                "按区域",
                "按地区",
                "按团队",
                "按服务线",
                "拆一下",
                "拆开",
                "换成",
                "哪个产品",
                "哪个客户",
                "客户是哪个",
                "利润最高的客户",
                "利润最多的客户",
                "产品贡献",
                "客户贡献",
                "个产品",
                "个客户",
                "名产品",
                "名客户",
            )
        )
        or any(token in lowered for token in ("break down", "breakdown", "by product", "by customer", "by city", "by region", "by team"))
        or any(token in compact_lower for token in ("byproduct", "bycustomer", "bycity", "byregion", "byteam"))
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="generic_dimension_switch", required_operation="ranking")
    if any(token in compact for token in ("趋势", "按月份", "按时间", "月度", "增长率", "增长最快", "增速")) or any(
        token in lowered for token in ("trend", "month by month", "monthly", "by quarter", "quarterly", "growth", "change over time")
    ) or any(
        token in compact_lower for token in ("monthbymonth", "byquarter")
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="trend_followup" if index > 0 else "trend", required_operation="aggregation")
    top_n_entity = bool(re.search(r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?的?(?:城市|客户|产品|商品|服务线|业务线|品类|门店|区域|地区)", compact))
    if top_n_entity or any(token in compact for token in ("top", "Top", "排名", "排行", "排序", "排列", "从高到低", "从低到高", "排第几", "排名第几", "名次", "最高", "最低", "最多", "最少", "差距", "比较")) or any(
        token in lowered for token in ("top", "highest", "lowest", "rank", "ranking", "sort", "order by", "most", "least", "largest", "smallest", "gap", "compare")
    ):
        return TurnPlan(question, expected_kind=expected_kind, capability_family="ranking_followup" if index > 0 else "ranking", required_operation="ranking")
    return TurnPlan(question, expected_kind=expected_kind, capability_family="llm_followup" if index > 0 else "analysis")


def _scenario_file_paths(scenario: ConversationScenario, root: Path) -> list[Path]:
    if scenario.file_paths:
        return [Path(path) for path in scenario.file_paths]
    file_paths = []
    for filename, content in scenario.files.items():
        path = root / filename
        path.write_text(content, encoding="utf-8")
        file_paths.append(path)
    return file_paths


def _scenario_file_names(scenario: ConversationScenario) -> list[str]:
    if scenario.file_paths:
        return [Path(path).name for path in scenario.file_paths]
    return list(scenario.files)


def _turn_evidence(index: int, turn: TurnPlan, response: dict[str, Any], *, tables: dict[str, Any] | None = None) -> TurnEvidence:
    logic = _representative_logic_from_response(response, required_operation=turn.required_operation)
    expected_metric = _expected_metric_from_question(turn.question)
    expected_dimension = _expected_dimension_from_question(turn.question)
    context = response.get("current_analysis_context") if isinstance(response.get("current_analysis_context"), dict) else {}
    followup = response.get("followup_context") if isinstance(response.get("followup_context"), dict) else {}
    correction = response.get("correction_context") if isinstance(response.get("correction_context"), dict) else {}
    actions = _structured_actions(response)
    section_count = _answer_section_count(response)
    turn_role = _turn_role(index, turn.expected_kind)
    contract_report = _contract_report_from_response(response)
    oracle_result = response.get("oracle_result") if isinstance(response.get("oracle_result"), dict) else {}
    if not oracle_result.get("oracle_available"):
        oracle_result = _deterministic_fixture_oracle_result(logic, response, tables or {}, turn=turn) or oracle_result
    return TurnEvidence(
        index=index,
        question=turn.question,
        expected_kind=turn.expected_kind,
        capability_family=turn.capability_family,
        required_operation=turn.required_operation,
        success=bool(response.get("success")),
        answer_type=str(response.get("answer_type") or ""),
        operation=str(logic.get("operation") or response.get("debug", {}).get("operation") or ""),
        conversation_id=str(response.get("conversation_id") or ""),
        state_name=str(context.get("state_name") or ""),
        expected_metric=expected_metric,
        expected_dimension=expected_dimension,
        actual_metric=_actual_metric_from_logic(logic),
        actual_dimension=_actual_dimension_from_logic(logic),
        followup_reason=str(followup.get("reason") or ""),
        action_count=len(actions),
        issue_count=len(response.get("errors") or []),
        structured_answer=section_count >= 5,
        section_count=section_count,
        turn_role=turn_role,
        conversation_turn=index > 1,
        context_status=_context_status(turn_role, followup=followup, correction=correction),
        semantic_status=str(response.get("semantic_status") or _semantic_status_from_response(response)),
        contract_satisfied=response.get("contract_satisfied") if isinstance(response.get("contract_satisfied"), bool) else None,
        contract_family=str(response.get("contract_family") or (contract_report or {}).get("task_family") or ""),
        contract_checked=isinstance(contract_report, dict) and bool(contract_report),
        contract_violation_codes=_contract_violation_codes(contract_report),
        contract_violation_error_codes=_contract_violation_error_codes(contract_report),
        oracle_available=bool(oracle_result.get("oracle_available")),
        oracle_passed=oracle_result.get("passed") if isinstance(oracle_result.get("passed"), bool) else None,
        oracle_issue_codes=[str(item) for item in oracle_result.get("issue_codes") or []],
        oracle_issue_metadata=dict(oracle_result.get("issue_metadata") or {}),
        expected_result=oracle_result.get("expected_result"),
        actual_result=oracle_result.get("actual_result"),
        answer_preview=_preview_text(response.get("answer"), limit=520),
        llm_judge_failed=_extract_llm_judge_failed(response),
        next_action_questions=_action_questions(actions),
    )
def _turn_role(index: int, expected_kind: str) -> str:
    if index == 1:
        return "初始问题"
    if expected_kind == "followup_analysis":
        return "连续追问"
    return "独立分析"


def _context_status(turn_role: str, *, followup: dict[str, Any], correction: dict[str, Any]) -> str:
    if followup.get("is_followup"):
        reason = str(followup.get("reason") or "followup")
        return f"已识别追问:{reason}"
    if correction.get("is_correction"):
        return "已识别修正"
    if turn_role != "连续追问":
        return "新会话入口"
    return "未识别为追问"


def _turn_issues(
    index: int,
    turn: TurnPlan,
    response: dict[str, Any],
    *,
    previous_conversation_id: str,
    evidence: TurnEvidence | None = None,
) -> list[str]:
    issues: list[str] = []
    expected_kind = turn.expected_kind
    answer = str(response.get("answer") or "")
    lowered = answer.lower()
    if "not applicable" in lowered:
        issues.append(f"turn_{index}:unexpected_not_applicable")
    if any(token in lowered for token in ("raw prompt", "chain_of_thought", "standard answer", "scorer")):
        issues.append(f"turn_{index}:internal_artifact_leak")
    if expected_kind in ANALYSIS_TURN_KINDS:
        if not str(response.get("answer") or "").strip():
            issues.append(f"turn_{index}:missing_answer")
    actions = _structured_actions(response)
    malformed_actions = [
        action
        for action in actions
        if not (
            action.get("operation")
            and action.get("question")
            and isinstance(action.get("inherited_parameters"), dict)
            and isinstance(action.get("parameters"), dict)
            and action.get("capability_family")
            and action.get("support_boundary") is not None
        )
    ]
    if malformed_actions:
        issues.append(f"turn_{index}:malformed_structured_action")
    if index > 1 and expected_kind == "followup_analysis":
        followup = response.get("followup_context") if isinstance(response.get("followup_context"), dict) else {}
        correction = response.get("correction_context") if isinstance(response.get("correction_context"), dict) else {}
        if not followup.get("is_followup") and not correction.get("is_correction"):
            issues.append(f"turn_{index}:missing_conversation_intent_context")
        if previous_conversation_id and str(response.get("conversation_id") or "") != previous_conversation_id:
            issues.append(f"turn_{index}:conversation_not_preserved")
    context = response.get("current_analysis_context") if isinstance(response.get("current_analysis_context"), dict) else {}
    if expected_kind in {"analysis", "followup_analysis"} and context.get("state_name") not in {"analysis_ready", "analysis_failed"}:
        issues.append(f"turn_{index}:missing_analysis_state")
    if expected_kind in {"analysis", "followup_analysis"}:
        logic = _representative_logic_from_response(response, required_operation=turn.required_operation)
        operation = str(logic.get("operation") or response.get("debug", {}).get("operation") or "")
        if _operation_present("ranking", {operation}) or operation in {"aggregation", "top_k_share", "growth_ranking"}:
            expected_dimensions = _expected_dimensions_from_question(turn.question)
            expected_dimension = expected_dimensions[0] if expected_dimensions else ""
            actual_dimension = _actual_dimension_from_logic(logic)
            if expected_dimensions and actual_dimension and not any(_dimension_matches(expected, actual_dimension) for expected in expected_dimensions):
                issues.append(f"turn_{index}:dimension_mismatch:expected={'|'.join(expected_dimensions)}:actual={actual_dimension}")
            expected_metric = _expected_metric_from_question(turn.question)
            actual_metric = _actual_metric_from_logic(logic)
            if expected_metric and actual_metric and not _metric_matches(expected_metric, actual_metric):
                issues.append(f"turn_{index}:metric_mismatch:expected={expected_metric}:actual={actual_metric}")
    semantic_status = str(response.get("semantic_status") or _semantic_status_from_response(response))
    if semantic_status == "failed":
        issues.append(f"turn_{index}:semantic_contract_failed")
    if semantic_status == "needs_clarification":
        issues.append(f"turn_{index}:semantic_contract_needs_clarification")
    oracle_result = response.get("oracle_result") if isinstance(response.get("oracle_result"), dict) else {}
    oracle_passed = evidence.oracle_passed if evidence is not None else oracle_result.get("passed")
    oracle_issue_codes = evidence.oracle_issue_codes if evidence is not None else [str(item) for item in oracle_result.get("issue_codes") or []]
    if oracle_passed is False or (isinstance(oracle_issue_codes, list) and _has_oracle_failure_issue_codes(oracle_issue_codes)):
        code_suffix = "|".join(oracle_issue_codes) if oracle_issue_codes else "oracle_mismatch"
        issues.append(f"turn_{index}:oracle_result_failed:{code_suffix}")
    llm_judge_failed = evidence.llm_judge_failed if evidence is not None else _extract_llm_judge_failed(response)
    if bool(llm_judge_failed):
        issues.append(f"turn_{index}:llm_judge_failed")
    return issues


def _scenario_issues(scenario: ConversationScenario, turns: list[TurnEvidence]) -> list[str]:
    issues: list[str] = []
    expected_turns = scenario.turn_templates[: len(turns)] if scenario.turn_templates else []
    required_operations = list(
        dict.fromkeys(
            turn.required_operation
            for turn in expected_turns
            if turn.required_operation
        )
    ) or list(scenario.required_operations)
    required_families = list(
        dict.fromkeys(
            turn.capability_family
            for turn in expected_turns
            if turn.capability_family
        )
    ) or list(scenario.required_capability_families)
    operations = {turn.operation for turn in turns if turn.operation}
    for operation in required_operations:
        if not _operation_present(operation, operations):
            issues.append(f"missing_required_operation:{operation}")
    families = {turn.capability_family for turn in turns if turn.capability_family}
    for family in required_families:
        if family not in families:
            issues.append(f"missing_required_capability_family:{family}")
    if scenario.min_turn_count and len(turns) < scenario.min_turn_count:
        issues.append(f"min_turn_count_not_met:{len(turns)}<{scenario.min_turn_count}")
    min_distinct_families = min(
        scenario.min_distinct_capability_families,
        len({turn.capability_family for turn in expected_turns if turn.capability_family}) or scenario.min_distinct_capability_families,
    )
    if min_distinct_families and len(families) < min_distinct_families:
        issues.append(f"min_distinct_capability_families_not_met:{len(families)}<{min_distinct_families}")
    expected_followups = [turn for turn in turns[1:] if turn.expected_kind == "followup_analysis"]
    if expected_followups and not any(_turn_has_context(turn) for turn in expected_followups):
        issues.append("no_followup_turn_was_classified")
    if not any(turn.action_count > 0 for turn in turns):
        issues.append("no_structured_actions_exposed")
    for turn in turns:
        for token in OLD_DEMO_QUESTION_TOKENS:
            if token in turn.question:
                issues.append(f"turn_{turn.index}:old_demo_question_token:{token}")
    return issues


def _required_families_for_turn_budget(scenario: ConversationScenario, *, max_followups: int) -> list[str]:
    if not scenario.turn_templates:
        return list(scenario.required_capability_families)
    turn_budget = max(1, int(max_followups or 0) + 1)
    expected_turns = scenario.turn_templates[:turn_budget]
    return list(dict.fromkeys(turn.capability_family for turn in expected_turns if turn.capability_family))


def _llm_generated_conversation_issues(turns: list[TurnEvidence]) -> list[str]:
    issues: list[str] = []
    for turn in turns:
        if turn.expected_kind in {"analysis", "followup_analysis", "overview", "quality"} and not turn.required_operation:
            issues.append(f"turn_{turn.index}:unclassified_required_operation")
        if turn.required_operation and not _operation_present(turn.required_operation, {turn.operation}):
            issues.append(f"turn_{turn.index}:operation_mismatch:expected={turn.required_operation}:actual={turn.operation or '-'}")
    if not turns[1:]:
        issues.append("llm_generated_no_followup_turns")
    if turns[1:] and not any(_turn_has_context(turn) for turn in turns[1:]):
        issues.append("no_followup_turn_was_classified")
    if not any(turn.action_count > 0 for turn in turns):
        issues.append("no_structured_actions_exposed")
    for turn in turns:
        for token in OLD_DEMO_QUESTION_TOKENS:
            if token in turn.question:
                issues.append(f"turn_{turn.index}:old_demo_question_token:{token}")
    return issues


def _operation_present(required: str, observed: set[str]) -> bool:
    accepted = OPERATION_EQUIVALENTS.get(required, {required})
    return bool(accepted & observed)


def _representative_logic_from_response(response: dict[str, Any], *, required_operation: str = "") -> dict[str, Any]:
    logic = response.get("logic_form") if isinstance(response.get("logic_form"), dict) else {}
    if str(logic.get("operation") or "") != "compound_followup":
        return logic
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    sub_results = [item for item in result.get("sub_results") or [] if isinstance(item, dict)]
    if required_operation:
        for item in reversed(sub_results):
            sub_logic = item.get("logic_form") if isinstance(item.get("logic_form"), dict) else {}
            sub_operation = str(sub_logic.get("operation") or "")
            if sub_operation and _operation_present(required_operation, {sub_operation}):
                return dict(sub_logic)
    for item in reversed(sub_results):
        if item.get("success") is False:
            continue
        sub_logic = item.get("logic_form") if isinstance(item.get("logic_form"), dict) else {}
        if sub_logic:
            return dict(sub_logic)
    return logic


def _contract_report_from_response(response: dict[str, Any]) -> dict[str, Any]:
    verification = response.get("verification") if isinstance(response.get("verification"), dict) else {}
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    for payload in (response, verification, debug):
        report = payload.get("contract_report") if isinstance(payload, dict) else None
        if isinstance(report, dict) and report:
            return report
    return {}


def _semantic_status_from_response(response: dict[str, Any]) -> str:
    verification = response.get("verification") if isinstance(response.get("verification"), dict) else {}
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    return str(verification.get("semantic_status") or debug.get("semantic_status") or "legacy_unverified")


def _contract_violation_codes(contract_report: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for item in contract_report.get("violations") or []:
        if isinstance(item, dict) and item.get("code"):
            codes.append(str(item["code"]))
    return codes


def _contract_violation_error_codes(contract_report: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for item in contract_report.get("violations") or []:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if not code:
            continue
        severity = str(item.get("severity") or "").strip().lower()
        if severity in {"warning", "warn", "needs_clarification", "info", "low"}:
            continue
        codes.append(str(code))
    return codes


def _has_oracle_failure_issue_codes(oracle_issue_codes: list[str]) -> bool:
    normalized = {str(item) for item in oracle_issue_codes}
    return bool(normalized & ORACLE_FAILURE_ISSUE_CODES)


def _extract_llm_judge_failed(response: dict[str, Any]) -> bool | None:
    judge_payload = response.get("llm_judge_failed")
    if isinstance(judge_payload, bool):
        return bool(judge_payload)
    judge_payload = response.get("llm_judge")
    if isinstance(judge_payload, bool):
        return bool(judge_payload)
    judge_payload = response.get("llm_judgement")
    if isinstance(judge_payload, dict):
        overall = str(judge_payload.get("overall") or "").strip().lower()
        if overall in {"failed", "fail", "no", "false"}:
            return True
        if overall in {"passed", "pass", "yes", "true"}:
            return False
        severity = str(judge_payload.get("severity") or "").strip().lower()
        if severity in {"high", "critical", "error"}:
            return True
        if severity in {"none", "low", "info", "warning"}:
            return False
        return None
    judge_payload = response.get("judge")
    if isinstance(judge_payload, dict):
        overall = str(judge_payload.get("overall") or "").strip().lower()
        if overall in {"failed", "fail", "no", "false"}:
            return True
        if overall in {"passed", "pass", "yes", "true"}:
            return False
    return None


def _is_turn_semantically_successful(turn_record: TurnEvidence | dict[str, Any]) -> bool:
    semantic_status = getattr(turn_record, "semantic_status", None)
    if semantic_status is None and isinstance(turn_record, dict):
        semantic_status = turn_record.get("semantic_status")
    semantic_status = str(semantic_status).strip().lower() if semantic_status is not None else ""
    if semantic_status in {"failed", "needs_clarification"}:
        return False
    if semantic_status and semantic_status not in {
        "passed",
        "corrected_passed",
        "legacy_unverified",
        "passed_with_insufficient_data",
        "partial",
    }:
        return False

    contract_satisfied = getattr(turn_record, "contract_satisfied", None)
    if contract_satisfied is None and isinstance(turn_record, dict):
        contract_satisfied = turn_record.get("contract_satisfied")  # type: ignore[assignment]
    if contract_satisfied is False:
        return False

    contract_violation_error_codes = getattr(turn_record, "contract_violation_error_codes", None)
    if contract_violation_error_codes is None:
        if isinstance(turn_record, dict):
            contract_violation_error_codes = turn_record.get("contract_violation_error_codes") or turn_record.get("contract_violation_codes", [])
        else:
            contract_violation_error_codes = getattr(turn_record, "contract_violation_codes", [])
    if contract_violation_error_codes:
        return False

    oracle_passed = getattr(turn_record, "oracle_passed", None)
    if oracle_passed is None and isinstance(turn_record, dict):
        oracle_passed = turn_record.get("oracle_passed")  # type: ignore[assignment]
    if oracle_passed is False:
        return False

    oracle_issue_codes = list(getattr(turn_record, "oracle_issue_codes", None) or [])
    if oracle_issue_codes is None:
        if isinstance(turn_record, dict):
            oracle_issue_codes = list(turn_record.get("oracle_issue_codes") or [])
        else:
            oracle_issue_codes = []
    if _has_oracle_failure_issue_codes(oracle_issue_codes):
        return False

    llm_judge_failed = getattr(turn_record, "llm_judge_failed", None)
    if llm_judge_failed is None and isinstance(turn_record, dict):
        llm_judge_failed = turn_record.get("llm_judge_failed")  # type: ignore[assignment]
    if bool(llm_judge_failed):
        return False

    return True


def _deterministic_fixture_oracle_result(
    logic: dict[str, Any],
    response: dict[str, Any],
    tables: dict[str, Any],
    *,
    turn: TurnPlan | None = None,
) -> dict[str, Any]:
    operation = str(logic.get("operation") or "")
    if turn is not None and turn.capability_family == "multi_table_join_ranking":
        return _deterministic_fixture_oracle_result_multi_table_join_ranking(logic, response, tables, turn=turn)
    if operation not in {"ranking", "aggregation", "dataset_overview", "multi_table_dataset_overview"}:
        if _operation_present("cleaning_policy", {operation}) or (
            turn is not None and _operation_present("cleaning_policy", {turn.required_operation or ""})
        ):
            quality_expected = _build_quality_oracle_expected_payload(tables)
            if not quality_expected:
                return {}
            quality_actual = _extract_quality_oracle_actual_payload(response)
            oracle_result = oracle_quality_field_counts(quality_expected, quality_actual)
            return {
                "oracle_available": oracle_result.oracle_available,
                "expected_result": oracle_result.expected_result,
                "actual_result": oracle_result.actual_result,
                "passed": oracle_result.passed,
                "diff_summary": oracle_result.diff_summary,
                "issue_codes": oracle_result.issue_codes,
                "source": "deterministic_eval_fixture",
            }
        return {}
    if not _deterministic_fixture_oracle_supported(logic, response, turn=turn):
        return {}
    if operation in {"dataset_overview", "multi_table_dataset_overview"}:
        overview_payload = _extract_overview_report(response)
        if not isinstance(overview_payload, Mapping):
            return {}
        expected_payload = _build_overview_expected_result_from_logic(logic, tables, is_multi=(operation == "multi_table_dataset_overview"))
        actual_payload = _build_overview_actual_result_payload(operation=operation, report=overview_payload)
        if not expected_payload or actual_payload is None:
            return {}
        oracle_result = (
            oracle_multi_file_dataset_overview(expected_payload, actual_payload)
            if operation == "multi_table_dataset_overview"
            else oracle_overview_schema_field_coverage(expected_payload, actual_payload)
        )
        return {
            "oracle_available": oracle_result.oracle_available,
            "expected_result": oracle_result.expected_result,
            "actual_result": oracle_result.actual_result,
            "passed": oracle_result.passed,
            "diff_summary": oracle_result.diff_summary,
            "issue_codes": oracle_result.issue_codes,
            "source": "deterministic_eval_fixture",
        }
    if turn is not None and turn.capability_family == "trend_followup":
        return _deterministic_fixture_oracle_result_trend_followup(logic, response)
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    metric = _actual_metric_from_logic(logic)
    dimension = _actual_dimension_from_logic(logic)
    limit = _positive_int(params.get("limit") or params.get("top_n") or params.get("k"))
    question = str(turn.question if turn is not None else response.get("question") or "")
    is_ranking_followup_gap = turn is not None and turn.expected_kind == "followup_analysis" and _is_ranking_followup_gap_question(question)
    if is_ranking_followup_gap:
        response_rows = _extract_gap_followup_rows(response)
        inferred_dimension, inferred_metric = _infer_ranking_gap_columns(
            response_rows,
            preferred_dimension=dimension or _expected_dimension_from_question(question),
            preferred_metric=metric or _expected_metric_from_question(question),
        )
        if inferred_dimension:
            dimension = inferred_dimension
        if inferred_metric:
            metric = inferred_metric
        if response_rows and metric and dimension:
            if not limit:
                response_rows_count = len(response_rows)
                limit = response_rows_count
            if limit:
                response_rows = response_rows[:limit]
            expected_payload = _build_gap_fixture_payload(
                rows=response_rows,
                dimension=dimension,
                metric=metric,
            )
            actual_payload = _extract_gap_payload_from_response(response, dimension=dimension, metric=metric)
            oracle_result = oracle_topn_followup_gap(
                expected_payload,
                actual_payload,
                answer=str(response.get("answer") or ""),
            )
            return {
                "oracle_available": oracle_result.oracle_available,
                "expected_result": oracle_result.expected_result,
                "actual_result": oracle_result.actual_result,
                "passed": oracle_result.passed,
                "diff_summary": oracle_result.diff_summary,
                "issue_codes": oracle_result.issue_codes,
                "source": "deterministic_eval_fixture",
            }
    if not metric or not dimension:
        return {}
    if not tables:
        return {}
    table = _select_oracle_table(tables, params=params, metric=metric, dimension=dimension)
    if table is None:
        return {}
    dimension_column = _find_oracle_column(table, dimension, role="dimension")
    metric_column = _find_oracle_column(table, metric, role="metric")
    metric_mode = "sum"
    if not metric_column and _metric_matches(metric, "利润率"):
        profit_column = _find_oracle_column(table, "profit", role="metric")
        sales_column = _find_oracle_column(table, "sales", role="metric")
        if profit_column and sales_column:
            metric_column = profit_column
            metric_mode = "profit_rate"
    if not dimension_column or not metric_column:
        return {}
    filtered = _apply_oracle_filters(table, logic.get("filters") if isinstance(logic.get("filters"), dict) else {})
    if filtered is None or getattr(filtered, "empty", True):
        return {}
    try:
        if metric_mode == "profit_rate":
            grouped = filtered.groupby(dimension_column, dropna=True).agg({metric_column: "sum", sales_column: "sum"}).reset_index()  # type: ignore[name-defined]
            grouped[metric] = grouped.apply(
                lambda row: None if not _oracle_float(row.get(sales_column)) else (_oracle_float(row.get(metric_column)) or 0.0) / (_oracle_float(row.get(sales_column)) or 1.0),
                axis=1,
            )
            value_column = metric
        else:
            grouped = filtered.groupby(dimension_column, dropna=True)[metric_column].sum().reset_index()
            value_column = metric_column
    except Exception:
        return {}
    ascending = str(params.get("sort_order") or "").lower() == "asc"
    if operation == "ranking":
        limit = _positive_int(params.get("limit") or params.get("top_n") or params.get("k"))
        grouped = grouped.sort_values(value_column, ascending=ascending)
        if limit:
            grouped = grouped.head(limit)
    else:
        grouped = grouped.sort_values(dimension_column, ascending=True)
    if turn is not None and turn.expected_kind == "followup_analysis" and _is_ranking_followup_gap_question(question):
        if not limit:
            response_rows = _extract_gap_followup_rows(response)
            if response_rows:
                limit = len(response_rows)
        if limit:
            grouped = grouped.head(limit)
        expected_payload = _build_gap_fixture_payload(
            rows=[
                {dimension: row[dimension_column], metric: _round_oracle_value(row[value_column])}
                for _, row in grouped.iterrows()
                if row.get(dimension_column) not in (None, "")
            ],
            dimension=dimension,
            metric=metric,
        )
        actual_payload = _extract_gap_payload_from_response(response, dimension=dimension, metric=metric)
        oracle_result = oracle_topn_followup_gap(
            expected_payload,
            actual_payload,
            answer=str(response.get("answer") or ""),
        )
        return {
            "oracle_available": oracle_result.oracle_available,
            "expected_result": oracle_result.expected_result,
            "actual_result": oracle_result.actual_result,
            "passed": oracle_result.passed,
            "diff_summary": oracle_result.diff_summary,
            "issue_codes": oracle_result.issue_codes,
            "source": "deterministic_eval_fixture",
        }
    expected_rows = [
        {dimension: row[dimension_column], metric: _round_oracle_value(row[value_column])}
        for _, row in grouped.iterrows()
        if row.get(dimension_column) not in (None, "")
    ]
    actual_rows = _oracle_actual_rows(response, dimension=dimension, metric=metric)
    passed = _oracle_rows_match(expected_rows, actual_rows, dimension=dimension, metric=metric)
    return {
        "oracle_available": True,
        "expected_result": {"rows": expected_rows},
        "actual_result": {"rows": actual_rows},
        "passed": passed,
        "diff_summary": None if passed else "Deterministic fixture result differs from Agent result rows.",
        "issue_codes": [] if passed else ["deterministic_fixture_oracle_mismatch"],
        "source": "deterministic_eval_fixture",
    }


def _deterministic_fixture_oracle_result_multi_table_join_ranking(
    logic: dict[str, Any],
    response: dict[str, Any],
    tables: dict[str, Any],
    *,
    turn: TurnPlan | None = None,
) -> dict[str, Any]:
    expected_result = _build_multi_table_join_ranking_expected_result(logic=logic, response=response, tables=tables, turn=turn)
    if not expected_result:
        return {}
    actual_result = _extract_multi_table_join_ranking_actual_result(logic=logic, response=response, expected=expected_result)
    if actual_result is None:
        return {}
    oracle_result = oracle_multi_table_join_ranking(expected_result, actual_result)
    return {
        "oracle_available": oracle_result.oracle_available,
        "expected_result": oracle_result.expected_result,
        "actual_result": oracle_result.actual_result,
        "passed": oracle_result.passed,
        "diff_summary": oracle_result.diff_summary,
        "issue_codes": oracle_result.issue_codes,
        "source": "deterministic_eval_fixture",
    }


def _build_multi_table_join_ranking_expected_result(
    logic: dict[str, Any],
    response: dict[str, Any],
    tables: dict[str, Any],
    turn: TurnPlan | None = None,
) -> dict[str, Any] | None:
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    logic_source_tables = _coerce_text_list(
        logic.get("source_tables")
        or logic.get("tables")
        or logic.get("source_table")
        or params.get("source_tables")
        or params.get("tables")
        or params.get("source_table")
    )
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    debug_source_tables = []
    if isinstance(response.get("logic_form"), Mapping):
        debug_source_tables = _coerce_text_list(response["logic_form"].get("source_tables"))
    debug_source_tables.extend(_coerce_text_list(debug.get("source_tables")))
    source_tables = _dedupe_preserve(logic_source_tables + debug_source_tables)
    if not source_tables:
        source_tables = [str(name) for name in tables.keys()]
    table_candidates = [name for name in source_tables if name in tables and tables.get(name) is not None]
    available_tables = {name: tables[name] for name in table_candidates}
    if len(available_tables) < 2:
        available_tables = {str(name): table for name, table in tables.items() if table is not None}
        source_tables = list(available_tables.keys())
    if len(available_tables) < 2:
        return None
    metric = _actual_metric_from_logic(logic)
    dimension = _actual_dimension_from_logic(logic)
    if turn is not None and _question_asks_city_dimension(turn.question) and _tables_have_column(available_tables, "city"):
        dimension = "city"
    if not metric or not dimension:
        return None
    if "," in metric:
        return None
    join_key = _extract_multi_table_join_key(logic=logic, response=response)
    join_plan = _resolve_join_key_for_compute(join_key=join_key, tables=available_tables, source_tables=list(available_tables.keys()))
    if not join_plan:
        return None
    ranking_rows = _compute_join_ranking_rows(
        tables=available_tables,
        join_plan=join_plan,
        dimension=dimension,
        metric=metric,
        params=params,
    )
    if not ranking_rows:
        return None
    top_object = dict(ranking_rows[0])
    top_object.pop("rank", None)
    return {
        "source_tables": list(available_tables.keys()),
        "join_key": join_key,
        "dimension": dimension,
        "metric": metric,
        "required_n": _positive_int(params.get("limit") or params.get("top_n") or params.get("k")),
        "distinct_count": len(ranking_rows),
        "ranking_rows": ranking_rows,
        "top_object": top_object,
        "top_value": top_object.get(metric),
    }


def _compute_join_ranking_rows(
    *,
    tables: dict[str, Any],
    join_plan: dict[str, str],
    dimension: str,
    metric: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    left_table_name = str(join_plan.get("left_table") or "").strip()
    right_table_name = str(join_plan.get("right_table") or "").strip()
    left_key = str(join_plan.get("left_key") or "").strip()
    right_key = str(join_plan.get("right_key") or "").strip()
    if left_table_name not in tables or right_table_name not in tables:
        return []
    if not left_key or not right_key:
        return []
    left_table = tables[left_table_name]
    right_table = tables[right_table_name]
    try:
        joined = left_table.merge(right_table, left_on=left_key, right_on=right_key, how="inner")
    except Exception:
        try:
            joined = left_table.merge(right_table, on=[left_key], how="inner")
        except Exception:
            return []
    dimension_column = _find_oracle_column(joined, dimension, role="dimension")
    metric_column = _find_oracle_column(joined, metric, role="metric")
    if not dimension_column or not metric_column:
        return []
    try:
        grouped = joined.groupby(dimension_column, dropna=True)[metric_column].sum(numeric_only=False).reset_index()
    except Exception:
        return []
    if grouped is None:
        return []
    grouped = grouped.copy()
    grouped[metric_column] = grouped[metric_column].map(_oracle_float)
    grouped = grouped.dropna(subset=[dimension_column, metric_column])
    if grouped.empty:
        return []
    ascending = str(params.get("sort_order") or "").lower() == "asc"
    grouped = grouped.sort_values([metric_column, dimension_column], ascending=[ascending, True], kind="mergesort")
    limit = _positive_int(params.get("limit") or params.get("top_n") or params.get("k"))
    if limit:
        grouped = grouped.head(limit)
    rows: list[dict[str, Any]] = []
    for _, row in grouped.iterrows():
        dimension_value = row.get(dimension_column)
        metric_value = row.get(metric_column)
        if str(dimension_value).strip() == "":
            continue
        rows.append(
            {
                "rank": len(rows) + 1,
                dimension: dimension_value,
                metric: _round_oracle_value(metric_value),
            }
        )
    return rows


def _extract_multi_table_join_ranking_actual_result(
    logic: dict[str, Any],
    response: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> dict[str, Any] | None:
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    metric = _actual_metric_from_logic(logic)
    dimension = _actual_dimension_from_logic(logic)
    if not metric or not dimension:
        metric = str(expected.get("metric") or "")
        dimension = str(expected.get("dimension") or "")
    if not metric or not dimension:
        return None
    source_tables = _coerce_text_list(
        logic.get("source_tables")
        or logic.get("tables")
        or logic.get("source_table")
        or params.get("source_tables")
        or params.get("tables")
        or params.get("source_table")
    )
    if not source_tables:
        logic_form = response.get("logic_form") if isinstance(response.get("logic_form"), Mapping) else {}
        source_tables = _coerce_text_list(logic_form.get("source_tables"))
    if not source_tables:
        source_tables = _coerce_text_list(response.get("debug", {}).get("source_tables") if isinstance(response.get("debug"), Mapping) else [])
    if not source_tables:
        source_tables = [str(item) for item in expected.get("source_tables", [])]
    ranking_rows = _extract_multi_table_join_ranking_rows(response=response, dimension=dimension, metric=metric)
    top_object = ranking_rows[0] if ranking_rows else {}
    top_object = {k: v for k, v in dict(top_object).items() if k != "rank"}
    return {
        "source_tables": source_tables,
        "join_key": _extract_multi_table_join_key(logic=logic, response=response),
        "dimension": dimension,
        "metric": metric,
        "required_n": expected.get("required_n"),
        "distinct_count": _extract_response_distinct_count(response) or len(ranking_rows),
        "answer": str(response.get("answer") or ""),
        "ranking_rows": ranking_rows,
        "top_object": top_object,
        "top_value": top_object.get(metric),
    }


def _question_asks_city_dimension(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    return "城市" in compact or "city" in compact


def _tables_have_column(tables: dict[str, Any], column_name: str) -> bool:
    normalized = str(column_name or "").lower()
    for table in tables.values():
        if normalized in {str(column).lower() for column in _table_columns(table)}:
            return True
    return False


def _extract_response_distinct_count(response: dict[str, Any]) -> int | None:
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    artifact = debug.get("result_artifacts") if isinstance(debug.get("result_artifacts"), Mapping) else {}
    count = _positive_int(artifact.get("distinct_count"))
    if count is not None:
        return count
    result = response.get("result") if isinstance(response.get("result"), Mapping) else {}
    value = result.get("value") if isinstance(result, Mapping) else {}
    if isinstance(value, Mapping):
        return _positive_int(value.get("distinct_count"))
    return None


def _extract_multi_table_join_ranking_rows(
    response: dict[str, Any],
    *,
    dimension: str,
    metric: str,
) -> list[dict[str, Any]]:
    result = response.get("result") if isinstance(response.get("result"), Mapping) else {}
    rows = [row for row in result.get("rows") or result.get("candidate_table") or [] if isinstance(row, Mapping)]
    direct_rows = response.get("rows")
    if isinstance(direct_rows, list):
        rows.extend(row for row in direct_rows if isinstance(row, Mapping))
    if not rows:
        debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
        result_artifacts = debug.get("result_artifacts") if isinstance(debug.get("result_artifacts"), Mapping) else {}
        top_objects = [row for row in result_artifacts.get("top_objects") or [] if isinstance(row, Mapping)]
        rows = [
            {
                "rank": row.get("rank"),
                "value": row.get("value"),
                "metric_value": row.get("metric_value"),
            }
            for row in top_objects
            if row.get("value") not in (None, "")
        ]
    payload: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidate_dimension = row.get(dimension)
        if candidate_dimension in (None, ""):
            candidate_dimension = row.get("value")
        if candidate_dimension in (None, ""):
            continue
        candidate_metric = row.get(metric)
        if candidate_metric is None and "metric_value" in row:
            candidate_metric = row.get("metric_value")
        payload.append(
            {
                dimension: candidate_dimension,
                metric: _round_oracle_value(candidate_metric),
            }
        )
        raw_rank = row.get("rank")
        payload[-1]["rank"] = int(raw_rank) if isinstance(raw_rank, int) else len(payload)
    if not payload:
        return payload
    payload.sort(key=lambda item: int(item.get("rank") or 0))
    return payload


def _extract_multi_table_join_key(logic: dict[str, Any], response: dict[str, Any]) -> dict[str, str] | None:
    candidates: list[Any] = []
    sources = [
        logic,
        logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {},
        response.get("debug") if isinstance(response.get("debug"), Mapping) else {},
        response.get("verification") if isinstance(response.get("verification"), Mapping) else {},
    ]
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        if source.get("join_plan") is not None:
            candidates.append(source.get("join_plan"))
        candidate_join_keys = source.get("candidate_join_keys")
        if isinstance(candidate_join_keys, list):
            candidates.extend(candidate_join_keys)
        elif candidate_join_keys:
            candidates.append(candidate_join_keys)
    for candidate in candidates:
        parsed = _coerce_oracle_join_key(candidate)
        if parsed is not None:
            return parsed
    return None


def _resolve_join_key_for_compute(
    join_key: dict[str, str] | None,
    tables: dict[str, Any],
    *,
    source_tables: list[str],
) -> dict[str, str] | None:
    if len(source_tables) < 2:
        return None
    if join_key:
        left_table, left_key = _resolve_join_side(join_key.get("left", ""), tables=tables, source_tables=source_tables)
        right_table, right_key = _resolve_join_side(join_key.get("right", ""), tables=tables, source_tables=source_tables)
        if left_table and left_key and right_table and right_key:
            return {"left_table": left_table, "left_key": left_key, "right_table": right_table, "right_key": right_key}
    inferred = _infer_join_key_from_tables(tables, source_tables=source_tables)
    if inferred:
        return {
            "left_table": inferred[0],
            "left_key": inferred[2],
            "right_table": inferred[1],
            "right_key": inferred[3],
        }
    return None


def _resolve_join_side(value: str, tables: dict[str, Any], *, source_tables: list[str]) -> tuple[str, str]:
    normalized = str(value).strip().strip("`")
    if not normalized:
        return "", ""
    if "." in normalized:
        left_table, left_key = _normalize_join_side(normalized)
        table_columns = _table_columns(tables.get(left_table, []))
        if left_key and left_table in tables and left_key in table_columns:
            return left_table, left_key
    else:
        for table_name in source_tables:
            if table_name not in tables:
                continue
            if normalized in _table_columns(tables[table_name]):
                return table_name, normalized
    return "", ""


def _infer_join_key_from_tables(tables: dict[str, Any], *, source_tables: list[str]) -> tuple[str, str, str, str] | None:
    for left_table in source_tables:
        if left_table not in tables:
            continue
        for right_table in source_tables:
            if right_table not in tables or right_table == left_table:
                continue
            left_columns = set(_table_columns(tables[left_table]))
            right_columns = set(_table_columns(tables[right_table]))
            overlap = left_columns & right_columns
            if not overlap:
                continue
            for candidate in ("customer_id", "user_id", "order_id", "id", "customerid", "orderid"):
                if candidate in overlap:
                    return left_table, right_table, candidate, candidate
            fallback = sorted(overlap)[0]
            return left_table, right_table, fallback, fallback
    return None


def _normalize_join_side(value: str) -> tuple[str, str]:
    normalized = str(value).strip().strip("`")
    if "." not in normalized:
        return "", normalized
    left, right = normalized.rsplit(".", 1)
    return left.strip(), right.strip()


def _coerce_oracle_join_key(value: Any) -> dict[str, str] | None:
    if not value:
        return None
    if isinstance(value, Mapping):
        left = str(value.get("left") or value.get("left_table") or value.get("left_source") or "").strip()
        right = str(value.get("right") or value.get("right_table") or value.get("right_source") or "").strip()
        left_key = str(value.get("left_key") or value.get("left_field") or value.get("left_column") or "").strip()
        right_key = str(value.get("right_key") or value.get("right_field") or value.get("right_column") or "").strip()
        if left and "." in left and not left_key:
            left, left_key = _normalize_join_side(left)
        if right and "." in right and not right_key:
            right, right_key = _normalize_join_side(right)
        if left and not right_key and "_" in left:
            left_key = left.split(".")[-1]
        if right and not right_key and "_" in right:
            right_key = right.split(".")[-1]
        if left and not left_key:
            return {"left": left, "right": right} if left and right else None
        if right and not right_key:
            return {"left": left, "right": right} if left and right else None
        if left and left_key and right and right_key:
            return {"left": left if "." in left else f"{left}.{left_key}", "right": right if "." in right else f"{right}.{right_key}"}
        if isinstance(value.get("text"), str):
            return _coerce_oracle_join_key(value.get("text"))
        return None

    if isinstance(value, str):
        text = str(value).strip()
        if "->" in text:
            left, right = [item.strip() for item in text.split("->", 1)]
            if left and right:
                return {"left": left, "right": right}
        if "=" in text:
            left, right = [item.strip() for item in text.split("=", 1)]
            if left and right:
                return {"left": left, "right": right}
    return None


def _table_columns(table: Any) -> list[str]:
    columns = getattr(table, "columns", [])
    if isinstance(columns, list):
        return [str(item) for item in columns]
    if hasattr(columns, "tolist"):
        return [str(item) for item in columns.tolist()]
    return []


def _extract_overview_report(response: dict[str, Any]) -> dict[str, Any] | None:
    direct = response.get("overview_report") if isinstance(response.get("overview_report"), Mapping) else None
    if direct is not None:
        return direct
    result = response.get("result") if isinstance(response.get("result"), Mapping) else {}
    value = result.get("value") if isinstance(result.get("value"), Mapping) else {}
    for item in (direct, value.get("overview_report"), result.get("overview_report")):
        if isinstance(item, Mapping):
            return item
    return None


def _build_quality_oracle_expected_payload(tables: dict[str, Any]) -> dict[str, Any] | None:
    if not tables:
        return None
    report = report_to_dict(build_data_quality_report(tables, generated_from="random_conversation_quality_oracle"))
    if not isinstance(report, Mapping):
        return None
    if "field_level_table" not in report and "field_level_quality" not in report:
        return None
    return report


def _extract_quality_oracle_actual_payload(response: dict[str, Any]) -> Any:
    if not isinstance(response, Mapping):
        return None
    candidates: list[Any] = [response]
    if isinstance(response.get("quality_report"), Mapping):
        candidates.append(response.get("quality_report"))
    if isinstance(response.get("result"), Mapping):
        candidates.append(response.get("result"))
        result = response["result"]
        if isinstance(result.get("quality_report"), Mapping):
            candidates.append(result.get("quality_report"))
        if isinstance(result.get("value"), Mapping):
            candidates.append(result.get("value"))
    if isinstance(response.get("verification"), Mapping) and isinstance(response["verification"], Mapping):
        verification = response["verification"]
        if isinstance(verification.get("quality_report"), Mapping):
            candidates.append(verification.get("quality_report"))
        candidates.append(verification)
    if isinstance(response.get("debug"), Mapping):
        debug = response["debug"]
        if isinstance(debug.get("quality_report"), Mapping):
            candidates.append(debug.get("quality_report"))
        if isinstance(debug.get("result"), Mapping):
            candidates.append(debug.get("result"))
        candidates.append(debug)

    for payload in candidates:
        if not isinstance(payload, Mapping):
            continue
        if (
            "field_level_table" in payload
            or "field_level_quality" in payload
            or "duplicate_rules" in payload
            or "duplicate_checks" in payload
            or "outlier_rules" in payload
        ):
            return dict(payload)
    return None


def _build_overview_expected_result_from_logic(
    logic: dict[str, Any],
    tables: dict[str, Any],
    *,
    is_multi: bool,
) -> dict[str, Any] | None:
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    requested_names = _coerce_text_list(params.get("tables") or params.get("source_tables") or [])
    if not requested_names:
        requested_name = str(params.get("table") or params.get("source_table") or "").strip()
        if requested_name:
            requested_names = [requested_name]
    if not requested_names and tables:
        requested_names = [str(name) for name in tables.keys()]
    if not requested_names and not is_multi and len(tables) == 1:
        requested_names = [str(next(iter(tables.keys())))]
    expected_tables: list[dict[str, Any]] = []
    metric_candidates: list[str] = []
    dimension_candidates: list[str] = []
    time_columns: list[str] = []

    for table_name in requested_names:
        table_payload = tables.get(table_name)
        if table_payload is None:
            continue
        table_columns = [str(column) for column in getattr(table_payload, "columns", [])]
        if not table_columns:
            continue
        fields: list[dict[str, Any]] = []
        for column in table_columns:
            series = table_payload[column] if table_name is not None and isinstance(table_payload, Mapping) else None
            if hasattr(table_payload, "__getitem__"):
                series = table_payload[column] if column in table_payload.columns else None
            role = _infer_overview_field_role(column, series, table_columns)
            dtype = getattr(series, "dtype", "")
            fields.append({"name": column, "role": role, "type": str(dtype) if dtype is not None else ""})
            if role == "time":
                time_columns.append(column)
            elif role == "metric":
                metric_candidates.append(column)
            elif not _looks_like_identifier_column(column):
                dimension_candidates.append(column)
        expected_tables.append(
            {
                "name": table_name,
                "fields": fields,
                "required_fields": [field["name"] for field in fields],
            }
        )

    if not expected_tables:
        return None

    expected_result = {
        "tables": expected_tables,
        "metric_candidates": _dedupe_preserve(metric_candidates),
        "dimension_candidates": _dedupe_preserve(dimension_candidates),
        "time_columns": _dedupe_preserve(time_columns),
        "analysis_directions": _infer_overview_analysis_directions(
            metric_candidates=_dedupe_preserve(metric_candidates),
            dimension_candidates=_dedupe_preserve(dimension_candidates),
            time_columns=_dedupe_preserve(time_columns),
        ),
    }
    if is_multi:
        expected_result["join_keys"] = _infer_overview_join_keys(expected_tables)
    return expected_result


def _build_overview_actual_result_payload(
    *,
    operation: str,
    report: dict[str, Any],
) -> dict[str, Any] | None:
    if operation == "dataset_overview":
        table_name = str(report.get("table") or "").strip()
        fields = _coerce_overview_field_list(report.get("field_meanings"))
        if not table_name or not fields:
            return None
        metric_candidates = _coerce_text_list(report.get("metric_candidates"))
        dimension_candidates = _coerce_text_list(report.get("dimension_candidates"))
        time_columns = _coerce_text_list(report.get("time_columns"))
        analysis_directions = _coerce_text_list(report.get("analysis_directions"))
        if not analysis_directions:
            analysis_directions = _infer_overview_analysis_directions(
                metric_candidates=metric_candidates,
                dimension_candidates=dimension_candidates,
                time_columns=time_columns,
            )
        return {
            "tables": [
                {
                    "name": table_name,
                    "fields": fields,
                    "required_fields": [field["name"] for field in fields],
                }
            ],
            "metric_candidates": metric_candidates,
            "dimension_candidates": dimension_candidates,
            "time_columns": time_columns,
            "analysis_directions": analysis_directions,
        }

    table_summaries = [item for item in report.get("tables_summary") or [] if isinstance(item, Mapping)]
    tables: list[dict[str, Any]] = []
    metric_candidates: list[str] = []
    dimension_candidates: list[str] = []
    time_columns: list[str] = []
    for summary in table_summaries:
        table_name = str(summary.get("table") or "").strip()
        fields = _coerce_overview_field_list(summary.get("field_meanings"))
        if not table_name or not fields:
            continue
        tables.append({"name": table_name, "fields": fields, "required_fields": [field["name"] for field in fields]})
        metric_candidates.extend(_coerce_text_list(summary.get("metric_candidates")))
        dimension_candidates.extend(_coerce_text_list(summary.get("dimension_candidates")))
        time_columns.extend(_coerce_text_list(summary.get("time_columns")))
    if not tables:
        return None
    analysis_directions = _coerce_text_list(report.get("analysis_directions"))
    if not analysis_directions:
        analysis_directions = _infer_overview_analysis_directions(
            metric_candidates=_dedupe_preserve(metric_candidates),
            dimension_candidates=_dedupe_preserve(dimension_candidates),
            time_columns=_dedupe_preserve(time_columns),
        )
    return {
        "tables": tables,
        "metric_candidates": _dedupe_preserve(metric_candidates),
        "dimension_candidates": _dedupe_preserve(dimension_candidates),
        "time_columns": _dedupe_preserve(time_columns),
        "join_keys": _coerce_overview_join_key_records(report.get("candidate_join_keys")),
        "analysis_directions": analysis_directions,
    }


def _infer_overview_field_role(column: str, series: Any, columns: list[str]) -> str:
    if _looks_like_time_column(column):
        return "time"
    if _series_is_numeric(series):
        return "metric"
    if _looks_like_identifier_column(column):
        return "dimension"
    if _normalized_field_name(column) in {"city", "customer", "product", "segment", "service", "order", "region"}:
        return "dimension"
    if _looks_like_identifier_column(column):
        return "dimension"
    if column not in columns:
        return "dimension"
    return "dimension"


def _infer_overview_analysis_directions(*, metric_candidates: list[str], dimension_candidates: list[str], time_columns: list[str]) -> list[str]:
    return _dedupe_preserve(_coerce_text_list(metric_candidates) + _coerce_text_list(dimension_candidates) + _coerce_text_list(time_columns))


def _coerce_overview_field_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    fields: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("field") or item.get("name") or item.get("field_name") or "").strip()
        if not name:
            continue
        fields.append(
            {
                "name": name,
                "role": str(item.get("role") or "").strip(),
                "type": str(item.get("type") or item.get("field_type") or "").strip(),
            }
        )
    return fields


def _infer_overview_join_keys(tables: list[dict[str, Any]]) -> list[dict[str, str]]:
    if len(tables) < 2:
        return []
    field_by_table = {
        str(item.get("name") or ""): {str(field.get("name") or "") for field in item.get("fields", []) if str(field.get("name") or "").strip()}
        for item in tables
        if item.get("name") and isinstance(item.get("fields"), list)
    }
    names = [name for name in field_by_table.keys() if name]
    if len(names) < 2:
        return []
    for left in range(len(names) - 1):
        left_name = names[left]
        for right_name in names[left + 1 :]:
            overlap = field_by_table.get(left_name, set()) & field_by_table.get(right_name, set())
            candidate_names = [
                column
                for column in ("customer_id", "user_id", "order_id", "id", "customerid", "orderid")
                if column in overlap
            ]
            if not candidate_names:
                candidate_names = sorted(overlap)
            if not candidate_names:
                continue
            key = candidate_names[0]
            if key:
                return [{"left": f"{left_name}.{key}", "right": f"{right_name}.{key}"}]
    return []


def _coerce_overview_join_key_records(value: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not value:
        return records
    items = value if isinstance(value, list) else [value]
    for item in items:
        if not isinstance(item, (Mapping, str)):
            continue
        parsed = _coerce_overview_join_key_item(item)
        if parsed is not None and parsed not in records:
            records.append(parsed)
    return records


def _coerce_text_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _coerce_overview_join_key_item(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        text = item.strip()
    elif isinstance(item, Mapping):
        if item.get("text") and isinstance(item.get("text"), str):
            text = str(item.get("text")).strip()
        else:
            text = ""
            left = str(item.get("left") or item.get("left_table") or item.get("left_source") or "").strip()
            right = str(item.get("right") or item.get("right_table") or item.get("right_source") or "").strip()
            if left and right:
                return {"left": left, "right": right}
    else:
        return None

    if text:
        if "->" in text:
            left, right = [part.strip() for part in text.split("->", 1)]
            if left and right:
                return {"left": left, "right": right}
        if "=" in text:
            left, right = [part.strip() for part in text.split("=", 1)]
            if left and right:
                return {"left": left, "right": right}
    return None


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value:
            continue
        item = str(value).strip()
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _normalized_field_name(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


def _deterministic_fixture_oracle_result_trend_followup(
    logic: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    trend_series = _extract_trend_followup_series(logic=logic, response=response)
    expected_result = oracle_trend_followup_series([{"month": item["month"], "value": item["value"]} for item in trend_series])
    actual_result = _build_actual_trend_followup_payload(logic, response, trend_series=trend_series)
    issue_codes = _trend_followup_oracle_issue_codes(expected_result, actual_result, answer=str(response.get("answer") or ""))
    passed = not issue_codes
    return {
        "oracle_available": True,
        "expected_result": expected_result,
        "actual_result": actual_result,
        "passed": passed,
        "diff_summary": None if passed else "Trend follow-up deterministic oracle payload differs from expected.",
        "issue_codes": issue_codes,
        "source": "deterministic_eval_fixture_trend_followup",
    }


def _extract_trend_followup_series(logic: dict[str, Any], response: dict[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
    if not rows:
        return []
    metric = _actual_metric_from_logic(logic)
    period = _actual_dimension_from_logic(logic)
    metric_key = str(metric or "").split(",")[0].strip() if metric else ""
    period_key = str(period or "").strip()
    sample = rows[0]
    metric_column = _resolve_metric_column(sample, metric_key=metric_key, period_key=period_key)
    period_column = _resolve_period_column(sample, period_key=period_key)
    if not period_column:
        return []
    values: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        month_value = row.get(period_column)
        if month_value is None:
            continue
        if metric_column and metric_column in row:
            series_value = _oracle_float(row.get(metric_column))
        else:
            series_value = _first_numeric_not_period(row, period_column)
        if series_value is None:
            continue
        values.append({"month": str(month_value), "value": series_value})
    return values


def _build_actual_trend_followup_payload(
    logic: dict[str, Any],
    response: dict[str, Any],
    *,
    trend_series: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = oracle_trend_followup_series(trend_series)
    trend_shape = _normalize_trend_shape(_extract_trend_followup_description(response, fallback=str(payload.get("trend_description") or "")))
    if trend_shape:
        payload["trend_shape"] = trend_shape
    trend_description = _extract_trend_followup_description(response, fallback=str(payload.get("trend_description") or ""))
    if trend_description:
        payload["trend_description"] = trend_description
    payload["series"] = trend_series
    payload["forbidden_descriptions"] = list(TREND_FOLLOWUP_FORBIDDEN_DESCRIPTIONS)
    if logic:
        payload["operation"] = str(logic.get("operation") or "")
    return payload


def _trend_followup_oracle_issue_codes(
    expected_result: dict[str, Any],
    actual_result: dict[str, Any],
    *,
    answer: str,
) -> list[str]:
    issue_codes: list[str] = []
    if not _trend_series_matches(expected_result.get("series"), actual_result.get("series")):
        issue_codes.append("trend_followup_oracle_series_mismatch")
    if not _trend_shape_equivalent(
        str(expected_result.get("trend_shape") or ""),
        str(actual_result.get("trend_shape") or ""),
    ):
        issue_codes.append("trend_followup_oracle_shape_mismatch")
    if not _trend_extreme_point_matches(expected_result.get("peak"), actual_result.get("peak")):
        issue_codes.append("trend_followup_oracle_peak_mismatch")
    if not _trend_extreme_point_matches(expected_result.get("low"), actual_result.get("low")):
        issue_codes.append("trend_followup_oracle_low_mismatch")
    if not _trend_max_change_matches(expected_result.get("max_change"), actual_result.get("max_change")):
        issue_codes.append("trend_followup_oracle_max_change_mismatch")
    if _contains_forbidden_trend_description(answer, expected_result):
        issue_codes.append("trend_followup_forbidden_trend_description_present")
    return sorted(set(issue_codes))


def _trend_series_matches(expected: Any, actual: Any) -> bool:
    if len(expected or []) != len(actual or []):
        return False
    for expected_point, actual_point in zip(expected or [], actual or [], strict=False):
        if not isinstance(expected_point, dict) or not isinstance(actual_point, dict):
            return False
        if str(expected_point.get("month") or "") != str(actual_point.get("month") or ""):
            return False
        if not _trend_number_matches(expected_point.get("value"), actual_point.get("value")):
            return False
    return True


def _trend_extreme_point_matches(expected: Any, actual: Any) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return expected == actual
    if str(expected.get("month") or "") != str(actual.get("month") or ""):
        return False
    if not _trend_number_matches(expected.get("value"), actual.get("value")):
        return False
    return True


def _extract_trend_followup_description(response: dict[str, Any], *, fallback: str) -> str:
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    artifacts = debug.get("result_artifacts") if isinstance(debug.get("result_artifacts"), dict) else {}
    description = str(artifacts.get("trend_description") or "")
    if description:
        return description
    answer = str(response.get("answer") or "")
    if answer:
        return answer.splitlines()[0].strip()
    return fallback


def _contains_forbidden_trend_description(answer: str, expected_result: dict[str, Any]) -> bool:
    normalized_shape = _normalize_trend_shape(str(expected_result.get("trend_shape") or ""))
    if normalized_shape not in {"up_then_down", "down_then_up", "fluctuation"}:
        return False
    compact = "".join(str(answer or "").split())
    for token in expected_result.get("forbidden_descriptions") or []:
        if token in compact:
            return True
    return False


def _normalize_trend_shape(shape: str) -> str:
    compact = "".join(str(shape or "").split())
    if any(token in compact for token in ("先升后降", "up_then_down", "fluctuation_backdown", "先上升后下降", "peak", "波动后", "峰值后", "先升")):
        return "up_then_down"
    if any(token in compact for token in ("先降后升", "down_then_up", "先下降后上升")):
        return "down_then_up"
    if any(token in compact for token in ("整体上升", "持续上升", "单调上升", "上升", "increasing", "increase", "上涨")):
        return "increasing"
    if any(token in compact for token in ("整体下降", "持续下降", "单调下降", "下降", "decreasing", "decrease", "下跌")):
        return "decreasing"
    if any(token in compact for token in ("波动", "fluctuation", "mixed", "振幅")):
        return "fluctuation"
    if "无法判断" in compact or "insufficient_periods_for_trend" in compact:
        return "insufficient_periods_for_trend"
    return compact


def _trend_max_change_matches(expected: Any, actual: Any) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False
    if str(expected.get("from") or "") != str(actual.get("from") or ""):
        return False
    if str(expected.get("to") or "") != str(actual.get("to") or ""):
        return False
    return _trend_number_matches(expected.get("delta"), actual.get("delta"))


def _trend_number_matches(expected: Any, actual: Any) -> bool:
    expected_value = _oracle_float(expected)
    actual_value = _oracle_float(actual)
    if expected_value is None or actual_value is None:
        return str(expected) == str(actual)
    return math.isclose(expected_value, actual_value, rel_tol=1e-6, abs_tol=0.01)


def _trend_shape_equivalent(expected: str, actual: str) -> bool:
    return _normalize_trend_shape(expected) == _normalize_trend_shape(actual)


def _resolve_period_column(sample_row: dict[str, Any], *, period_key: str) -> str:
    if period_key:
        for key in sample_row:
            if key == period_key or _dimension_matches(period_key, str(key)):
                return key
    for key in sample_row:
        if str(key) in {"month", "月份", "月度", "时点", "日期", "date", "period", "time"}:
            return key
    for key in sample_row:
        if str(key).lower() in {"month", "date", "time"}:
            return key
    return ""


def _resolve_metric_column(sample_row: dict[str, Any], *, metric_key: str, period_key: str) -> str:
    if metric_key:
        for key in sample_row:
            if key == metric_key or (_metric_matches(metric_key, str(key)) and str(key) != period_key):
                return key
    for key in sample_row:
        if str(key) == period_key:
            continue
        if _oracle_float(sample_row.get(key)) is not None:
            return key
    return ""


def _first_numeric_not_period(row: dict[str, Any], period_column: str) -> float | None:
    for key, value in row.items():
        if str(key) == period_column:
            continue
        value_number = _oracle_float(value)
        if value_number is not None:
            return value_number
    return None


def _deterministic_fixture_oracle_supported(logic: dict[str, Any], response: dict[str, Any], *, turn: TurnPlan | None) -> bool:
    if response.get("success") is not True:
        return False
    is_derived_metric_followup = turn is not None and turn.capability_family == "derived_metric_followup"
    if turn is not None and turn.expected_kind == "followup_analysis":
        if turn.capability_family == "trend_followup":
            return True
        if _is_ranking_followup_gap_question(str(turn.question or response.get("question") or "")):
            return True
        if not is_derived_metric_followup:
            return False
    question = str(turn.question if turn is not None else response.get("question") or "")
    compact = "".join(question.split())
    if _is_ranking_followup_gap_question(question):
        return True
    if not is_derived_metric_followup and any(token in compact for token in ("这个指标", "这些Top", "这些top", "这些前", "这些排名", "这些对象", "刚才", "上面", "上一轮", "继续")):
        return False
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    filters = logic.get("filters") if isinstance(logic.get("filters"), dict) else {}
    if filters:
        return False
    if params.get("referent_values") or params.get("referent_contract") or logic.get("referent_contract"):
        return False
    metric = _actual_metric_from_logic(logic)
    if _metric_matches(metric, "利润率"):
        return turn is not None and turn.capability_family == "derived_metric_followup"
    if "," in metric:
        return False
    return True


def _infer_ranking_gap_columns(
    rows: list[dict[str, Any]],
    *,
    preferred_dimension: str,
    preferred_metric: str,
) -> tuple[str, str]:
    excluded_metric_like_keys = {
        "rank",
        "index",
        "idx",
        "row_number",
        "rownum",
        "ranking",
        "序号",
    }
    dimension = str(preferred_dimension).strip()
    metric = str(preferred_metric).strip()
    candidate_dimension: str = ""
    candidate_metric: str = ""
    if not rows:
        return dimension, metric
    if not dimension:
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            for key, value in row.items():
                if str(key).strip() in {"", "_oracle_expected_result_missing"}:
                    continue
                if _oracle_float(value) is None and str(value) not in {"", "-"}:
                    candidate_dimension = str(key)
                    break
            if candidate_dimension:
                break
        if candidate_dimension:
            dimension = candidate_dimension
    if not metric:
        preferred_metric_key = preferred_metric.strip()
        if preferred_metric_key and any(
            _oracle_float(dict(row).get(preferred_metric_key) if isinstance(row, Mapping) else None) is not None
            for row in rows
        ):
            metric = preferred_metric_key
    if not metric:
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            for key, value in row.items():
                key_text = str(key)
                if key_text.lower() in excluded_metric_like_keys or key_text in excluded_metric_like_keys:
                    continue
                if dimension and key_text == dimension:
                    continue
                if _oracle_float(value) is not None:
                    candidate_metric = key_text
                    break
            if candidate_metric:
                break
        if not metric and candidate_metric:
            metric = candidate_metric
    if not metric and preferred_metric:
        metric = str(preferred_metric).strip()
    return dimension, metric


def _is_ranking_followup_gap_question(question: str) -> bool:
    compact = "".join(str(question or "").split())
    lowered = compact.lower()
    if not compact:
        return False
    gap_signal = any(token in lowered for token in ("gap", "difference", "差距", "相差", "差额"))
    if not gap_signal:
        return False
    top_signal = any(token in compact for token in ("Top", "top", "前", "排名")) or any(token in lowered for token in ("top", "top3", "top5"))
    return top_signal and any(token in lowered for token in ("比较", "比", "compare", "对比", "差距", "difference", "gap"))


def _extract_gap_followup_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result")
    if isinstance(result, dict):
        candidate = result.get("candidate_table")
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
        candidate = result.get("rows")
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    direct = response.get("rows")
    if isinstance(direct, list):
        return [row for row in direct if isinstance(row, dict)]
    return []


def _extract_gap_payload_from_response(response: dict[str, Any], *, dimension: str, metric: str) -> dict[str, Any]:
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    result_artifacts = debug.get("result_artifacts")
    if isinstance(result_artifacts, Mapping):
        payload = _coerce_gap_payload(result_artifacts)
        if payload:
            return payload
    rows = _extract_gap_followup_rows(response)
    return _build_gap_fixture_payload(rows=rows, dimension=dimension, metric=metric)


def _coerce_gap_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    top_objects = []
    for item in value.get("top_objects") or []:
        if not isinstance(item, Mapping):
            continue
        top_objects.append(
            {
                "rank": item.get("rank"),
                "value": item.get("value"),
                "metric_value": item.get("metric_value"),
            }
        )
    adjacent_gaps = list(value.get("adjacent_gaps") or [])
    gap_to_leader = list(value.get("gap_to_leader") or [])
    should_derive = len(gap_to_leader) != len(top_objects) or len(adjacent_gaps) != max(len(top_objects) - 1, 0)
    if should_derive:
        derived = _build_gap_fixture_payload(
            rows=[
                {"value": item.get("value"), "metric_value": item.get("metric_value")}
                for item in top_objects
            ],
            dimension="value",
            metric="metric_value",
        )
        if len(gap_to_leader) != len(derived["gap_to_leader"]):
            gap_to_leader = derived["gap_to_leader"]
        if len(adjacent_gaps) != len(derived["adjacent_gaps"]):
            adjacent_gaps = derived["adjacent_gaps"]
    return {
        "top_objects": top_objects,
        "adjacent_gaps": adjacent_gaps,
        "gap_to_leader": gap_to_leader,
    }


def _build_gap_fixture_payload(*, rows: list[dict[str, Any]], dimension: str, metric: str) -> dict[str, Any]:
    top_objects: list[dict[str, Any]] = []
    payload_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            continue
        raw_value = row.get(dimension)
        if raw_value in (None, ""):
            continue
        metric_value = row.get(metric)
        top_objects.append(
            {
                "rank": index,
                "value": raw_value,
                "metric_value": metric_value,
            }
        )
        payload_rows.append(
            {
                "metric_value": metric_value,
                "gap_to_leader": row.get("gap_to_leader"),
                "gap_from_previous": row.get("gap_from_previous"),
            }
        )
    if not top_objects:
        return {"top_objects": [], "adjacent_gaps": [], "gap_to_leader": []}
    adjacent_gaps: list[Any] = []
    gap_to_leader: list[Any] = []
    leader_float = _oracle_float(payload_rows[0].get("metric_value"))
    previous_float = leader_float
    for index, item in enumerate(payload_rows):
        metric_float = _oracle_float(item.get("metric_value"))
        explicit_to_leader = item.get("gap_to_leader")
        explicit_prev_gap = item.get("gap_from_previous")
        if explicit_to_leader is not None:
            gap_to_leader.append(_oracle_float(explicit_to_leader))
        else:
            if index == 0 and leader_float is not None:
                gap_to_leader.append(0.0)
            else:
                gap_to_leader.append(_round_oracle_gap(leader_float - metric_float) if leader_float is not None and metric_float is not None else None)
        if index > 0:
            if explicit_prev_gap is not None:
                adjacent_gaps.append(_oracle_float(explicit_prev_gap))
            else:
                adjacent_gaps.append(
                    _round_oracle_gap(previous_float - metric_float) if previous_float is not None and metric_float is not None else None
                )
        previous_float = metric_float
    return {"top_objects": top_objects, "adjacent_gaps": adjacent_gaps, "gap_to_leader": gap_to_leader}


def _round_oracle_gap(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def _select_oracle_table(tables: dict[str, Any], *, params: dict[str, Any], metric: str, dimension: str) -> Any:
    requested = str(params.get("table") or params.get("source_table") or "").strip()
    if requested and requested in tables:
        return tables[requested]
    candidates = list(tables.values())
    for table in candidates:
        if _find_oracle_column(table, dimension, role="dimension") and (
            _find_oracle_column(table, metric, role="metric")
            or (_metric_matches(metric, "利润率") and _find_oracle_column(table, "profit", role="metric") and _find_oracle_column(table, "sales", role="metric"))
        ):
            return table
    return candidates[0] if len(candidates) == 1 else None


def _find_oracle_column(table: Any, value: str, *, role: str) -> str:
    columns = [str(column) for column in getattr(table, "columns", [])]
    for column in columns:
        if column == value:
            return column
    matcher = _metric_matches if role == "metric" else _dimension_matches
    for column in columns:
        if matcher(value, column):
            return column
    return ""


def _apply_oracle_filters(table: Any, filters: dict[str, Any]) -> Any:
    filtered = table
    for key, raw_values in filters.items():
        column = _find_oracle_column(filtered, str(key), role="dimension") or str(key)
        if column not in getattr(filtered, "columns", []):
            continue
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        values_text = {str(value) for value in values if value not in (None, "")}
        if values_text:
            filtered = filtered[filtered[column].astype(str).isin(values_text)]
    return filtered


def _oracle_actual_rows(response: dict[str, Any], *, dimension: str, metric: str) -> list[dict[str, Any]]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
    actual: list[dict[str, Any]] = []
    for row in rows:
        dimension_key = next((key for key in row if _dimension_matches(dimension, str(key))), dimension)
        metric_key = next((key for key in row if _metric_matches(metric, str(key))), metric)
        if dimension_key not in row or metric_key not in row:
            continue
        actual.append({dimension: row.get(dimension_key), metric: _round_oracle_value(row.get(metric_key))})
    return actual


def _oracle_rows_match(expected: list[dict[str, Any]], actual: list[dict[str, Any]], *, dimension: str, metric: str) -> bool:
    if len(expected) != len(actual):
        return False
    for expected_row, actual_row in zip(expected, actual, strict=False):
        if str(expected_row.get(dimension)) != str(actual_row.get(dimension)):
            return False
        expected_value = _oracle_float(expected_row.get(metric))
        actual_value = _oracle_float(actual_row.get(metric))
        if expected_value is None or actual_value is None:
            if str(expected_row.get(metric)) != str(actual_row.get(metric)):
                return False
        elif not math.isclose(expected_value, actual_value, rel_tol=1e-6, abs_tol=0.01):
            return False
    return True


def _round_oracle_value(value: Any) -> Any:
    number = _oracle_float(value)
    if number is None:
        return value
    return round(number, 4)


def _oracle_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _turn_has_context(turn: TurnEvidence) -> bool:
    return bool(turn.followup_reason) or str(turn.context_status or "").startswith("已识别")


def _expected_dimension_from_question(question: str) -> str:
    compact = "".join(str(question or "").split())
    lowered = str(question or "").lower()
    if not compact and not lowered:
        return ""
    if _is_focus_set_scalar_total_question(compact) or _is_scalar_total_over_time_question(compact):
        return ""
    if any(token in compact for token in ("趋势", "月度趋势", "季度趋势", "如何变化", "怎么变化", "怎样变化", "变化趋势")) or any(
        token in lowered for token in ("trend", "month by month")
    ):
        return "month"
    ranking_signal = any(token in compact for token in ("找出", "哪个", "哪些", "排名", "排行", "最高", "最低", "最多", "最少", "最大", "最小"))
    if ranking_signal:
        target_dimension = _rank_target_dimension_from_question(compact, lowered)
        if target_dimension:
            return target_dimension
    if any(
        token in compact
        for token in (
            "增长最快",
            "增长最多",
            "增速最快",
            "增幅最大",
            "提升最快",
            "提升最多",
            "下降最快",
            "下降最多",
            "变化最明显",
            "变化最大",
            "变化最多",
            "变动最大",
            "变动最多",
            "波动最大",
            "波动最多",
        )
    ) or any(
        token in lowered for token in ("fastest growth", "largest growth", "highest growth", "biggest increase", "largest increase", "fastest decline")
    ):
        scoped_answer_dimension = _dimension_after_growth_entity_scope(compact, lowered)
        if scoped_answer_dimension:
            return scoped_answer_dimension
        if any(token in compact for token in ("哪个客户", "哪些客户", "这些客户", "前5个客户", "前五个客户", "客户中")) or any(
            token in lowered for token in ("which customer", "by customer", "customer growth")
        ):
            return "customer_id"
        if any(token in compact for token in ("哪个城市", "哪些城市", "这些城市", "前3个城市", "前三个城市", "城市中")) or any(
            token in lowered for token in ("which city", "by city", "city growth")
        ):
            return "city"
        if any(token in compact for token in ("哪个产品", "哪些产品", "哪种产品", "这些产品", "产品中")) or any(
            token in lowered for token in ("which product", "by product", "product growth")
        ):
            return "product"
        if any(token in compact for token in ("哪个服务线", "哪些服务线", "服务线中", "哪个业务线", "哪些业务线")) or any(
            token in lowered for token in ("service line growth", "business line growth")
        ):
            return "service_line"
    if any(token in compact for token in ("趋势", "月度", "按月份", "按季度", "各月", "每月", "如何变化", "怎么变化", "怎样变化", "变化趋势", "季度变化")) or any(
        token in lowered for token in ("trend", "monthly", "month by month", "quarterly", "by quarter")
    ):
        return "month"
    if (
        re.search(r"\d{1,2}月(?:到|至|-|~|—|和|与)\d{1,2}月", compact)
        and any(token in compact for token in ("分别", "是多少", "多少"))
        and not any(token in compact for token in ("各城市", "各个城市", "每个城市", "按城市", "不同城市", "所有城市"))
    ):
        return "month"
    if any(token in compact for token in ("客户细分", "客户群体", "客户分区", "客户分段", "客户段", "细分市场", "按客群", "哪个客群", "哪些客群", "客群排名")) or "segment" in lowered:
        return "segment"
    if any(
        token in compact
        for token in ("排名前三的客户", "排名前3的客户", "前3名客户", "前三名客户", "前3个客户", "前三个客户", "客户是哪些", "哪些客户", "哪个客户")
    ) or any(token in lowered for token in ("which customer", "top customers", "top customer")):
        return "customer_id"
    if any(
        token in compact
        for token in ("按产品", "哪个产品", "哪种产品", "产品排名", "产品维度", "产品是什么", "产品是哪", "的产品是什么", "的产品是哪")
    ) or any(token in lowered for token in ("by product", "which product", "product ranking")):
        return "product"
    if any(token in compact for token in ("按服务线", "各服务线", "每个服务线", "各条服务线", "每条服务线", "哪个服务线", "哪些服务线", "服务线分布", "服务线是哪些", "服务线排名", "按业务线", "各业务线", "每个业务线", "各条业务线", "每条业务线", "哪个业务线", "哪些业务线", "业务线分布", "业务线排名")) or any(
        token in lowered for token in ("by service line", "service line", "business line")
    ):
        return "service_line"
    if any(token in compact for token in ("各城市", "各个城市", "每个城市", "所有城市", "哪个城市", "哪些城市", "城市分布", "城市是哪个", "城市是哪", "按城市", "城市排名", "城市之间", "名城市", "个城市是哪些", "个城市有哪些", "城市销售额", "城市的客户")) or any(
        token in lowered for token in ("by city", "which city", "city ranking")
    ):
        return "city"
    if any(token in compact for token in ("哪个客户", "客户是谁", "客户是什么", "客户是哪个", "客户是哪些", "按客户", "客户排名", "客户贡献", "客户维度", "利润最高的客户", "利润最多的客户")) or any(
        token in lowered for token in ("by customer", "which customer", "customer ranking")
    ):
        return "customer_id"
    if any(token in compact for token in ("按月份", "按月度", "月度趋势", "月份趋势")) or any(
        token in lowered for token in ("by month", "monthly", "month by month")
    ):
        return "month"
    if any(token in compact for token in ("按区域", "哪个区域", "按地区", "哪个地区")) or any(token in lowered for token in ("by region", "which region")):
        return "region"
    return ""


def _dimension_after_growth_entity_scope(compact: str, lowered: str) -> str:
    scope_match = re.search(
        r"(?:增长最快|增长最多|增速最快|增幅最大|提升最快|提升最多|下降最快|下降最多|变化最明显|变化最大|变化最多|变动最大|变动最多|波动最大|波动最多)的?(?:那个|该|这个)?(?:城市|客户|产品|服务线|业务线)(?:中|里|内)?",
        compact,
    )
    suffix = compact[scope_match.end() :] if scope_match else ""
    if not suffix and any(token in lowered for token in ("fastest growing city", "city with fastest growth", "fastest growth city")):
        suffix = lowered
    if not suffix:
        return ""
    checks = (
        ("segment", ("客户细分", "客户群体", "客户分区", "客户分段", "客户段", "细分市场", "哪个客群", "哪些客群", "segment")),
        ("customer_id", ("哪个客户", "哪些客户", "客户是哪个", "客户是哪", "客户是谁", "按客户", "which customer", "by customer")),
        ("product", ("哪个产品", "哪种产品", "哪些产品", "产品是哪个", "产品是哪", "按产品", "which product", "by product")),
        ("service_line", ("哪个服务线", "哪些服务线", "哪个业务线", "哪些业务线", "按服务线", "按业务线", "which service line", "by service line", "business line")),
        ("city", ("哪个城市", "哪些城市", "按城市", "which city", "by city")),
    )
    for dimension, patterns in checks:
        if any((pattern in suffix if any("\u4e00" <= char <= "\u9fff" for char in pattern) else pattern in lowered) for pattern in patterns):
            return dimension
    return ""


def _is_focus_set_scalar_total_question(compact: str) -> bool:
    if not re.search(r"(?:前|top|Top)\s*(?:\d+|[一二两三四五六七八九十]+)", compact):
        return False
    if not any(token in compact for token in ("总和", "合计", "汇总", "总计", "总共", "一共", "加起来")):
        return False
    return any(token in compact for token in ("是多少", "多少", "有多少", "算一下", "计算"))


def _is_scalar_total_over_time_question(compact: str) -> bool:
    if not re.search(r"\d{1,2}月(?:到|至|-|~|—|和|与)\d{1,2}月|20\d{2}年\d{1,2}月(?:到|至|-|~|—)(?:20\d{2}年)?\d{1,2}月", compact):
        return False
    if not any(token in compact for token in ("是多少", "多少", "有多少", "算一下", "计算")):
        return False
    if any(token in compact for token in ("各城市", "各个城市", "每个城市", "按城市", "不同城市", "所有城市", "各客户", "每个客户", "按客户", "各产品", "每个产品", "按产品", "各服务线", "每个服务线", "按服务线")):
        return False
    return any(token in compact for token in ("总金额", "总订单金额", "订单总金额", "总利润", "总收入", "总额", "合计"))


def _rank_target_dimension_from_question(compact: str, lowered: str) -> str:
    if any(token in compact for token in ("哪个月份", "哪个月", "哪月份", "哪月", "几月份", "几月")) and any(
        token in compact for token in ("最高", "最低", "最大", "最小", "最多", "最少", "排名", "排行")
    ):
        if any(
            token in compact
            for token in (
                "列出前3名城市",
                "列出前三名城市",
                "前3名城市",
                "前三名城市",
                "前3个城市",
                "前三个城市",
                "哪些城市",
                "哪几个城市",
                "前三大客户",
                "前3大客户",
                "前3名客户",
                "前三名客户",
                "前3个客户",
                "前三个客户",
                "哪些客户",
                "哪几个客户",
                "前3名产品",
                "前三名产品",
                "前3个产品",
                "前三个产品",
                "哪些产品",
                "哪几个产品",
                "前3名服务线",
                "前三名服务线",
                "哪几条服务线",
                "哪些服务线",
            )
        ):
            return ""
        return "month"
    if any(token in compact for token in ("按服务线分", "按业务线分", "按服务线拆分", "按业务线拆分")) and any(
        token in compact for token in ("城市是哪", "哪些城市", "哪几个城市", "城市排名", "最高的城市")
    ):
        return ""
    if any(token in compact for token in ("按城市分", "按城市拆分")) and any(
        token in compact for token in ("服务线是哪", "哪些服务线", "哪几条服务线", "最高的服务线", "业务线是哪", "哪些业务线")
    ):
        return ""
    checks = (
        ("segment", ("哪个客群", "哪些客群", "客户细分", "客户群体", "客户分区", "客户分段", "客户段", "细分市场")),
        ("customer_id", ("哪个客户", "哪些客户", "前3名客户", "前三名客户", "前3个客户", "前三个客户", "客户是哪些", "客户是谁", "客户排名")),
        ("product", ("哪个产品", "哪种产品", "哪些产品", "前3名产品", "前三名产品", "前3个产品", "前三个产品", "产品排名")),
        ("service_line", ("哪个服务线", "哪些服务线", "各服务线", "各条服务线", "每个服务线", "每条服务线", "哪个业务线", "哪些业务线", "各业务线", "各条业务线", "每个业务线", "每条业务线", "服务线排名", "业务线排名")),
        ("city", ("哪个城市", "哪些城市", "前3名城市", "前三名城市", "前3个城市", "前三个城市", "利润率最高的城市", "销售额最高的城市", "城市排名")),
    )
    for dimension, patterns in checks:
        if any(pattern in compact for pattern in patterns):
            return dimension
    if any(token in lowered for token in ("which city", "top city", "city ranking")):
        return "city"
    if any(token in lowered for token in ("which customer", "top customer", "customer ranking")):
        return "customer_id"
    if any(token in lowered for token in ("which product", "top product", "product ranking")):
        return "product"
    if any(token in lowered for token in ("service line", "business line")):
        return "service_line"
    return ""


def _expected_dimensions_from_question(question: str) -> list[str]:
    primary = _expected_dimension_from_question(question)
    dimensions = [primary] if primary else []
    compact = "".join(str(question or "").split())
    lowered = str(question or "").lower()
    split_rank_pairs = (
        ("service_line", "city", any(token in compact for token in ("按服务线分", "按业务线分", "按服务线拆分", "按业务线拆分")) and any(token in compact for token in ("城市是哪", "哪些城市", "哪几个城市", "城市排名", "最高的城市"))),
        ("city", "service_line", any(token in compact for token in ("按城市分", "按城市拆分")) and any(token in compact for token in ("服务线是哪", "哪些服务线", "哪几条服务线", "最高的服务线", "业务线是哪", "哪些业务线"))),
    )
    for left, right, present in split_rank_pairs:
        if present:
            for dimension in (left, right):
                if dimension and dimension not in dimensions:
                    dimensions.append(dimension)
    compound_distribution = any(token in compact for token in ("分布", "分布情况", "基本情况", "概述", "概览", "总览")) and any(
        token in compact for token in ("和", "以及", "及", "、")
    )
    if compound_distribution:
        compound_checks = (
            ("city", any(token in compact for token in ("各城市", "各个城市", "每个城市", "所有城市", "城市分布", "按城市")) or "by city" in lowered),
            ("segment", any(token in compact for token in ("客户细分", "客户群体", "客户分区", "客户分段", "客户段", "细分市场", "客群")) or "segment" in lowered),
            ("service_line", any(token in compact for token in ("各服务线", "每个服务线", "各条服务线", "每条服务线", "服务线分布", "各业务线", "每个业务线", "各条业务线", "每条业务线", "业务线分布"))),
            ("product", any(token in compact for token in ("各产品", "每个产品", "产品分布", "各商品", "每个商品", "商品分布")) or "by product" in lowered),
            ("customer_id", any(token in compact for token in ("各客户", "每个客户", "客户分布", "按客户")) or "by customer" in lowered),
        )
        for dimension, present in compound_checks:
            if present and dimension not in dimensions:
                dimensions.append(dimension)
    return dimensions


def _expected_metric_from_question(question: str) -> str:
    compact = "".join(str(question or "").split())
    lowered = str(question or "").lower()
    asks_profit_rate = "利润率" in compact or "毛利率" in compact or any(token in lowered for token in ("profit margin", "gross margin", "profit rate"))
    asks_amount = any(token in compact for token in ("订单总金额", "订单总额", "订单金额", "订单额", "总金额", "总额", "金额", "收入", "营收")) or any(
        token in lowered for token in ("amount", "revenue")
    )
    asks_sales = any(token in compact for token in ("销售额", "销售金额", "销售总额", "总销售额", "销售趋势", "销售排名")) or any(token in lowered for token in ("sales", "sale amount"))
    asks_tickets = any(token in compact for token in ("工单量", "工单数", "票据数", "工单数量")) or any(token in lowered for token in ("tickets", "ticket count"))
    amount_topn_context = asks_profit_rate and asks_amount and any(
        token in compact for token in ("金额最高的前", "总额最高的前", "订单额最高的前", "订单金额最高的前", "订单总金额最高的前", "订单总额最高的前")
    ) and any(token in compact for token in ("中哪个", "中，哪个", "中哪", "中，哪", "中的哪个", "中的哪"))
    if amount_topn_context:
        return "利润率"
    profit_rate_context = asks_profit_rate and any(
        token in compact for token in ("利润率最高的", "毛利率最高的", "profitmarginhighest")
    )
    profit_rate_tail = compact.split("中", 1)[-1] if "中" in compact else compact
    if profit_rate_context and asks_sales and any(token in profit_rate_tail for token in ("销售额", "销售金额", "销售总额", "总销售额", "销售排名")):
        return "sales"
    if profit_rate_context and asks_tickets and any(token in profit_rate_tail for token in ("工单量", "工单数", "票据数", "工单数量")):
        return "tickets"
    if profit_rate_context and asks_amount and any(
        token in compact
        for token in (
            "订单额最高",
            "订单金额最高",
            "订单总金额最高",
            "订单总额最高",
            "金额最高",
            "总额最高",
            "订单额最大",
            "订单金额最大",
            "订单总金额最大",
            "订单总额最大",
            "金额最大",
            "总额最大",
        )
    ):
        return "amount"
    if asks_profit_rate and asks_amount and any(token in compact for token in ("利润率最高", "毛利率最高")):
        return "利润率"
    if asks_profit_rate and asks_amount and any(token in compact for token in ("其利润率", "利润率在", "利润率变化", "利润率趋势", "利润率的变化")):
        return "利润率"
    if asks_profit_rate and asks_amount and any(
        token in compact for token in ("利润率是多少", "利润率多少", "每个月的利润率", "每月利润率", "各月利润率", "月度利润率")
    ):
        return "利润率"
    if asks_profit_rate and asks_amount and not profit_rate_context and any(token in compact for token in ("订单额最高", "订单金额最高", "订单总金额最高", "订单总额最高", "金额最高", "总额最高")):
        return "amount"
    if asks_profit_rate and asks_amount and any(token in compact for token in ("分别", "各", "每个")):
        return ""
    if asks_profit_rate:
        return "利润率"
    asks_profit = any(token in compact for token in ("贡献利润", "利润贡献", "最多的利润", "利润最高", "总利润", "利润排名", "利润")) or "profit" in lowered
    contextual_month_match = re.search(
        r"(?:利润|利润率|毛利率|销售额|销售金额|订单金额|订单总金额|订单总额|订单额|金额|收入|营收)"
        r"[^，,。？?；;]{0,16}(?:最高|最多|最大|最低|最少|最小)的?(?:那个月|这个月|该月|月份|月)",
        compact,
    )
    if contextual_month_match:
        target_clause = compact[contextual_month_match.end() :]
    else:
        condition_split = re.split(r"(?:那个月|该月|这个月|该月份|这个月份)", compact, maxsplit=1)
        target_clause = condition_split[1] if len(condition_split) > 1 else ""
    if asks_amount and asks_profit and target_clause and any(token in target_clause for token in ("订单总金额", "订单总额", "订单金额", "订单额", "总金额", "总额", "收入", "营收", "最大", "最高", "最多")):
        return "amount"
    if asks_profit and any(token in compact for token in ("贡献利润", "利润贡献", "贡献的利润最多", "利润最多", "最多的利润")):
        return "profit"
    tail = compact.split("中", 1)[-1] if "中" in compact else compact
    prefix = compact.split("中", 1)[0] if "中" in compact else ""
    if asks_amount and asks_profit and any(token in prefix for token in ("利润最高", "利润最多", "总利润最高", "总利润最多")) and any(
        token in tail for token in ("订单总金额", "订单总额", "订单金额", "订单额", "总金额", "总额", "收入", "营收", "金额")
    ):
        return "amount"
    if asks_amount and asks_profit and "利润" in tail and any(token in tail for token in ("是多少", "多少")):
        return "profit"
    if asks_amount and asks_profit:
        return "amount,profit"
    if asks_sales and asks_tickets:
        return "sales,tickets"
    if any(token in compact for token in ("贡献利润", "利润贡献", "贡献的利润最多", "利润最多", "最多的利润", "利润最高", "总利润", "利润排名")) or "profit" in lowered:
        return "profit"
    if asks_sales:
        return "sales"
    if asks_tickets:
        return "tickets"
    if any(token in compact for token in ("订单总金额", "订单总额", "订单金额", "订单额", "总额", "金额", "收入", "营收")) or any(
        token in lowered for token in ("amount", "revenue")
    ):
        return "amount"
    if "利润" in compact:
        return "profit"
    return ""


def _actual_dimension_from_logic(logic: dict[str, Any]) -> str:
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    entity_grain = logic.get("entity_grain") if isinstance(logic.get("entity_grain"), dict) else {}
    return str(params.get("dimension") or logic.get("group_by") or entity_grain.get("field") or "")


def _actual_metric_from_logic(logic: dict[str, Any]) -> str:
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    metrics = params.get("metrics")
    if isinstance(metrics, list) and len(metrics) > 1:
        return ",".join(str(item) for item in metrics if str(item))
    derived_metric = params.get("derived_metric") if isinstance(params.get("derived_metric"), dict) else {}
    metric_definition = logic.get("metric_definition") if isinstance(logic.get("metric_definition"), dict) else {}
    return str(derived_metric.get("name") or params.get("metric") or logic.get("metric") or metric_definition.get("name") or "")


def _dimension_matches(expected: str, actual: str) -> bool:
    expected_aliases = _dimension_aliases(expected)
    actual_aliases = _dimension_aliases(actual)
    return bool(expected_aliases & actual_aliases)


def _metric_matches(expected: str, actual: str) -> bool:
    expected_parts = [part.strip() for part in str(expected or "").split(",") if part.strip()]
    actual_parts = [part.strip() for part in str(actual or "").split(",") if part.strip()]
    if len(expected_parts) > 1:
        return all(any(_single_metric_matches(part, actual_part) for actual_part in actual_parts) for part in expected_parts)
    if len(actual_parts) > 1 and expected_parts:
        return any(_single_metric_matches(expected_parts[0], actual_part) for actual_part in actual_parts)
    return _single_metric_matches(expected, actual)


def _single_metric_matches(expected: str, actual: str) -> bool:
    expected_aliases = _metric_aliases(expected)
    actual_aliases = _metric_aliases(actual)
    return bool(expected_aliases & actual_aliases)


def _dimension_aliases(value: str) -> set[str]:
    key = str(value or "").strip().lower()
    aliases = {
        "city": {"city", "城市"},
        "customer_id": {"customer_id", "customer", "cust_id", "客户"},
        "product": {"product", "product_name", "sku", "sku_name", "产品"},
        "service_line": {"service_line", "business_line", "服务线", "业务线"},
        "segment": {"segment", "客群"},
        "month": {"month", "月份", "月度"},
        "region": {"region", "区域", "地区"},
    }
    for canonical, values in aliases.items():
        if key == canonical or key in values:
            return values | {canonical}
    return {key} if key else set()


def _metric_aliases(value: str) -> set[str]:
    key = str(value or "").strip().lower()
    aliases = {
        "amount": {"amount", "revenue", "sales", "金额", "订单金额", "订单额", "订单总金额", "订单总额", "总额", "收入", "营收", "销售额", "销售金额"},
        "sales": {"sales", "amount", "revenue", "销售额", "销售金额", "金额"},
        "profit": {"profit", "利润", "毛利"},
        "利润率": {"利润率", "毛利率", "profit_margin", "profit margin", "margin"},
    }
    for canonical, values in aliases.items():
        if key == canonical.lower() or key in {item.lower() for item in values}:
            return {item.lower() for item in values | {canonical}}
    return {key} if key else set()


def _structured_actions(response: dict[str, Any]) -> list[dict[str, Any]]:
    actions = response.get("agent_actions")
    if not isinstance(actions, list):
        insight = response.get("insight") if isinstance(response.get("insight"), dict) else {}
        actions = insight.get("next_actions") if isinstance(insight.get("next_actions"), list) else []
    context = response.get("current_analysis_context") if isinstance(response.get("current_analysis_context"), dict) else {}
    if not actions and isinstance(context.get("available_followup_actions"), list):
        actions = context["available_followup_actions"]
    return [dict(action) for action in actions if isinstance(action, dict)]


def _answer_section_count(response: dict[str, Any]) -> int:
    sections = response.get("structured_answer_sections")
    if isinstance(sections, dict):
        return sum(1 for heading in _structured_answer_headings() if isinstance(sections.get(heading), list) and sections.get(heading))
    answer = str(response.get("answer") or "")
    return sum(1 for heading in _structured_answer_headings() if heading in answer)


def _structured_answer_headings() -> tuple[str, ...]:
    return (
        "数据摘要（关键指标）",
        "分析洞察（发现了什么）",
        "业务建议（可以采取什么行动）",
        "口径与边界",
        "下一步可继续分析",
    )


def _coverage_summary(results: list[ScenarioResult]) -> dict[str, Any]:
    capability_counts: dict[str, int] = {}
    scenario_family_counts: dict[str, int] = {}
    scenario_family_conversations: dict[str, dict[str, int]] = {}
    scenario_family_turn_metrics: dict[str, dict[str, int]] = {}
    scenario_family_violation_counts: dict[str, dict[str, int]] = {}
    operation_counts: dict[str, int] = {}
    requested_followup_turns = 0
    followup_turns = 0
    missing_followup_context_turns = 0
    post_initial_turns = 0
    contextualized_post_initial_turns = 0
    missing_post_initial_context_turns = 0
    structured_action_turns = 0
    structured_answer_turns = 0
    semantic_contract_turns = 0
    oracle_result_turns = 0
    oracle_available_turns = 0
    oracle_passed_turns = 0
    oracle_failed_turns = 0
    oracle_expected_result_present_turns = 0
    oracle_actual_result_present_turns = 0
    oracle_expected_result_missing_turns = 0
    oracle_actual_result_missing_turns = 0
    contract_checked_turns = 0
    contract_satisfied_turns = 0
    semantic_passed_turns = 0
    semantic_failed_turns = 0
    corrected_passed_turns = 0
    needs_clarification_turns = 0
    llm_judge_failed_turns = 0
    legacy_unverified_turns = 0
    transport_success_turns = 0
    violation_counts: dict[str, int] = {}
    all_violation_counts: dict[str, int] = {}
    total_turns = 0
    for result in results:
        scenario_family = result.scenario_family or "not_available"
        scenario_family_conversation = scenario_family_conversations.setdefault(
            scenario_family,
            {"conversation_count": 0, "passed_conversation_count": 0},
        )
        scenario_family_conversation["conversation_count"] += 1
        if result.passed:
            scenario_family_conversation["passed_conversation_count"] += 1
        for turn in result.turns:
            total_turns += 1
            turn_scenario_family = turn.scenario_family or scenario_family
            scenario_family_counts[turn_scenario_family] = scenario_family_counts.get(turn_scenario_family, 0) + 1
            family_metrics = scenario_family_turn_metrics.setdefault(
                turn_scenario_family,
                {
                    "turn_count": 0,
                    "semantic_contract_turns": 0,
                    "semantic_passed_turns": 0,
                    "semantic_failed_turns": 0,
                    "oracle_available_turns": 0,
                    "oracle_passed_turns": 0,
                    "oracle_failed_turns": 0,
                    "expected_contract_checked_turns": 0,
                    "expected_contract_passed_turns": 0,
                    "expected_contract_failed_turns": 0,
                },
            )
            family_metrics["turn_count"] += 1
            if turn.success:
                transport_success_turns += 1
            if turn.capability_family:
                capability_counts[turn.capability_family] = capability_counts.get(turn.capability_family, 0) + 1
            if turn.operation:
                operation_counts[turn.operation] = operation_counts.get(turn.operation, 0) + 1
            if turn.index > 1:
                post_initial_turns += 1
                if _turn_has_context(turn):
                    contextualized_post_initial_turns += 1
                else:
                    missing_post_initial_context_turns += 1
            if turn.expected_kind == "followup_analysis":
                requested_followup_turns += 1
                if _turn_has_context(turn):
                    followup_turns += 1
                else:
                    missing_followup_context_turns += 1
            if turn.action_count > 0:
                structured_action_turns += 1
            if turn.structured_answer:
                structured_answer_turns += 1
            if turn.contract_family:
                semantic_contract_turns += 1
                family_metrics["semantic_contract_turns"] += 1
            if turn.oracle_issue_codes or turn.oracle_available or turn.oracle_passed is not None:
                oracle_result_turns += 1
            if turn.oracle_available:
                oracle_available_turns += 1
                family_metrics["oracle_available_turns"] += 1
            if turn.oracle_passed is True:
                oracle_passed_turns += 1
                family_metrics["oracle_passed_turns"] += 1
            if turn.oracle_passed is False:
                oracle_failed_turns += 1
                family_metrics["oracle_failed_turns"] += 1
            has_oracle_payload = bool(turn.oracle_issue_codes or turn.oracle_available or turn.oracle_passed is not None)
            if has_oracle_payload:
                if turn.expected_result is not None:
                    oracle_expected_result_present_turns += 1
                else:
                    oracle_expected_result_missing_turns += 1
                if turn.actual_result is not None:
                    oracle_actual_result_present_turns += 1
                else:
                    oracle_actual_result_missing_turns += 1
            if turn.contract_checked:
                contract_checked_turns += 1
            if turn.contract_satisfied is True:
                contract_satisfied_turns += 1
            if turn.semantic_status in {
                "passed",
                "corrected_passed",
                "passed_with_insufficient_data",
                "partial",
            }:
                semantic_passed_turns += 1
                family_metrics["semantic_passed_turns"] += 1
            if turn.semantic_status == "failed":
                semantic_failed_turns += 1
                family_metrics["semantic_failed_turns"] += 1
            if turn.semantic_status == "corrected_passed":
                corrected_passed_turns += 1
            if turn.semantic_status == "needs_clarification":
                needs_clarification_turns += 1
            if turn.semantic_status in {"legacy_unverified", "not_available", ""}:
                legacy_unverified_turns += 1
            for code in turn.contract_violation_codes:
                violation_counts[code] = violation_counts.get(code, 0) + 1
                all_violation_counts[code] = all_violation_counts.get(code, 0) + 1
                family_codes = scenario_family_violation_counts.setdefault(turn_scenario_family, {})
                family_codes[code] = family_codes.get(code, 0) + 1
            for code in turn.oracle_issue_codes:
                all_violation_counts[code] = all_violation_counts.get(code, 0) + 1
                family_codes = scenario_family_violation_counts.setdefault(turn_scenario_family, {})
                family_codes[code] = family_codes.get(code, 0) + 1
            if turn.llm_judge_failed:
                llm_judge_failed_turns += 1
                family_codes = scenario_family_violation_counts.setdefault(turn_scenario_family, {})
                family_codes["llm_judge_failed"] = family_codes.get("llm_judge_failed", 0) + 1
    family_summary = _family_summary_from_counts(
        scenario_family_conversations,
        scenario_family_turn_metrics,
        scenario_family_violation_counts,
    )
    return {
        "conversation_count": len(results),
        "turn_count": total_turns,
        "transport_success_turns": transport_success_turns,
        "requested_followup_turns": requested_followup_turns,
        "followup_turns": followup_turns,
        "missing_followup_context_turns": missing_followup_context_turns,
        "post_initial_turns": post_initial_turns,
        "contextualized_post_initial_turns": contextualized_post_initial_turns,
        "missing_post_initial_context_turns": missing_post_initial_context_turns,
        "structured_action_turns": structured_action_turns,
        "structured_answer_turns": structured_answer_turns,
        "semantic_contract_turns": semantic_contract_turns,
        "oracle_result_turns": oracle_result_turns,
        "oracle_available_turns": oracle_available_turns,
        "oracle_passed_turns": oracle_passed_turns,
        "oracle_failed_turns": oracle_failed_turns,
        "oracle_passed": oracle_passed_turns,
        "oracle_failed": oracle_failed_turns,
        "oracle_expected_result_present_turns": oracle_expected_result_present_turns,
        "oracle_actual_result_present_turns": oracle_actual_result_present_turns,
        "oracle_expected_result_missing_turns": oracle_expected_result_missing_turns,
        "oracle_actual_result_missing_turns": oracle_actual_result_missing_turns,
        "oracle_expected_missing": oracle_expected_result_missing_turns,
        "oracle_actual_missing": oracle_actual_result_missing_turns,
        "contract_checked_turns": contract_checked_turns,
        "contract_satisfied_turns": contract_satisfied_turns,
        "semantic_passed_turns": semantic_passed_turns,
        "semantic_failed_turns": semantic_failed_turns,
        "corrected_passed_turns": corrected_passed_turns,
        "needs_clarification_turns": needs_clarification_turns,
        "llm_judge_failed_turns": llm_judge_failed_turns,
        "legacy_unverified_turns": legacy_unverified_turns,
        "top_violation_codes": [
            {"code": code, "count": count}
            for code, count in sorted(all_violation_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
        "top_contract_violation_codes": [
            {"code": code, "count": count}
            for code, count in sorted(violation_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
        "scenario_families": sorted(scenario_family_counts),
        "scenario_family_counts": dict(sorted(scenario_family_counts.items())),
        "family_summary": family_summary,
        "family_level_pass_rate": {item["family"]: item["pass_rate"] for item in family_summary.get("families", [])},
        "family_level_semantic_pass_rate": {item["family"]: item["semantic_pass_rate"] for item in family_summary.get("families", [])},
        "family_level_oracle_pass_rate": {item["family"]: item["oracle_pass_rate"] for item in family_summary.get("families", [])},
        "family_level_expected_contract_pass_rate": {
            item["family"]: item["expected_contract_pass_rate"] for item in family_summary.get("families", [])
        },
        "top_violation_codes_by_family": {
            family: [
                {"code": code, "count": count}
                for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
            ]
            for family, counts in sorted(scenario_family_violation_counts.items())
        },
        "capability_families": sorted(capability_counts),
        "capability_family_counts": dict(sorted(capability_counts.items())),
        "operations": sorted(operation_counts),
        "operation_counts": dict(sorted(operation_counts.items())),
    }


def _scenario_pass_rate(results: list[ScenarioResult]) -> float:
    return 0.0 if not results else sum(1 for result in results if result.passed) / len(results)


def _family_summary_from_counts(
    conversations: dict[str, dict[str, int]],
    turn_metrics: dict[str, dict[str, int]],
    violation_counts: dict[str, dict[str, int]],
) -> dict[str, Any]:
    families = sorted(set(conversations) | set(turn_metrics))
    rows: list[dict[str, Any]] = []
    for family in families:
        conversation_counts = conversations.get(family, {})
        metrics = turn_metrics.get(family, {})
        top_codes = [
            {"code": code, "count": count}
            for code, count in sorted((violation_counts.get(family) or {}).items(), key=lambda item: (-item[1], item[0]))[:10]
        ]
        rows.append(
            {
                "family": family,
                "conversation_count": int(conversation_counts.get("conversation_count", 0)),
                "passed_conversation_count": int(conversation_counts.get("passed_conversation_count", 0)),
                "pass_rate": _coverage_rate(conversation_counts.get("passed_conversation_count", 0), conversation_counts.get("conversation_count", 0)),
                "total_turns": int(metrics.get("turn_count", 0)),
                "semantic_contract_turns": int(metrics.get("semantic_contract_turns", 0)),
                "semantic_passed_turns": int(metrics.get("semantic_passed_turns", 0)),
                "semantic_failed_turns": int(metrics.get("semantic_failed_turns", 0)),
                "semantic_pass_rate": _coverage_rate(metrics.get("semantic_passed_turns", 0), metrics.get("semantic_contract_turns", 0)),
                "oracle_available_turns": int(metrics.get("oracle_available_turns", 0)),
                "oracle_passed_turns": int(metrics.get("oracle_passed_turns", 0)),
                "oracle_failed_turns": int(metrics.get("oracle_failed_turns", 0)),
                "oracle_pass_rate": _coverage_rate(metrics.get("oracle_passed_turns", 0), metrics.get("oracle_available_turns", 0)),
                "expected_contract_checked_turns": int(metrics.get("expected_contract_checked_turns", 0)),
                "expected_contract_passed_turns": int(metrics.get("expected_contract_passed_turns", 0)),
                "expected_contract_failed_turns": int(metrics.get("expected_contract_failed_turns", 0)),
                "expected_contract_pass_rate": _coverage_rate(
                    metrics.get("expected_contract_passed_turns", 0),
                    metrics.get("expected_contract_checked_turns", 0),
                ),
                "top_violation_codes": top_codes,
            }
        )
    return {"status": "available" if rows else "not_available", "families": rows}


def _coverage_rate(numerator: Any, denominator: Any) -> float | str:
    try:
        denominator_int = int(denominator or 0)
    except (TypeError, ValueError):
        denominator_int = 0
    if denominator_int <= 0:
        return "not_available"
    try:
        numerator_int = int(numerator or 0)
    except (TypeError, ValueError):
        numerator_int = 0
    return numerator_int / denominator_int


def _sample_scenarios(scenarios: list[ConversationScenario], count: int, rng: random.Random) -> list[ConversationScenario]:
    if count <= 0 or count >= len(scenarios):
        shuffled = list(scenarios)
        rng.shuffle(shuffled)
        return shuffled
    return rng.sample(scenarios, count)


def _safe_question(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    blocked = ("task_id", "standard answer", "scorer", "raw prompt", "标准答案", "评分")
    if not text or any(token in text.lower() for token in blocked):
        return ""
    return text[:240]


def _schema_summary_from_tables(tables: dict[str, Any], files: list[Path]) -> dict[str, Any]:
    table_summaries = []
    for table_name, df in tables.items():
        columns = [str(column) for column in getattr(df, "columns", [])]
        numeric_columns = [column for column in columns if _series_is_numeric(df[column])]
        time_columns = [column for column in columns if _looks_like_time_column(column)]
        dimension_columns = [
            column
            for column in columns
            if column not in numeric_columns and column not in time_columns and not _looks_like_identifier_column(column)
        ]
        metric = _prefer_metric_column(numeric_columns)
        dimension = _prefer_dimension_column(dimension_columns)
        table_summaries.append(
            {
                "table_name": str(table_name),
                "row_count": int(len(df)),
                "columns": columns,
                "numeric_columns": numeric_columns,
                "dimension_columns": dimension_columns,
                "time_columns": time_columns,
                "metric": metric,
                "dimension": dimension,
                "time_column": time_columns[0] if time_columns else "",
            }
        )
    primary = _choose_primary_table(table_summaries)
    return {
        "files": [path.name for path in files],
        "table_count": len(table_summaries),
        "tables": table_summaries,
        "primary_table": primary,
    }


def _choose_primary_table(tables: list[dict[str, Any]]) -> dict[str, Any]:
    if not tables:
        return {}
    return max(
        tables,
        key=lambda table: (
            bool(table.get("metric")),
            bool(table.get("dimension")),
            bool(table.get("time_column")),
            int(table.get("row_count") or 0),
        ),
    )


def _series_is_numeric(series: Any) -> bool:
    dtype = getattr(getattr(series, "dtype", None), "kind", "")
    if dtype in {"b", "i", "u", "f", "c"}:
        return True
    sample = [value for value in list(series.head(20)) if value not in (None, "")]
    if not sample:
        return False
    numeric_count = 0
    for value in sample:
        try:
            float(value)
            numeric_count += 1
        except (TypeError, ValueError):
            pass
    return numeric_count >= max(3, int(len(sample) * 0.7))


def _prefer_metric_column(columns: list[str]) -> str:
    preferred = ("sales", "revenue", "amount", "amt", "profit", "收入", "销售额", "销售金额", "金额", "利润")
    for token in preferred:
        for column in columns:
            if token.lower() in column.lower():
                return column
    return columns[0] if columns else ""


def _prefer_dimension_column(columns: list[str]) -> str:
    preferred = ("city", "region", "product", "category", "customer", "store", "城市", "地区", "产品", "品类", "客户", "门店")
    for token in preferred:
        for column in columns:
            if token.lower() in column.lower():
                return column
    return columns[0] if columns else ""


def _looks_like_time_column(column: str) -> bool:
    return bool(re_search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column))


def _looks_like_identifier_column(column: str) -> bool:
    lowered = str(column or "").lower()
    return lowered in {"id", "ids"} or lowered.endswith("_id") or lowered.endswith("id") or any(token in lowered for token in ("编号", "编码", "代码"))


def _has_columns(table: dict[str, Any], *columns: str) -> bool:
    available = {str(column).lower() for column in table.get("columns") or []}
    return all(column.lower() in available for column in columns)


def _field_label(column: str) -> str:
    mapping = {
        "city": "城市",
        "region": "地区",
        "product": "产品",
        "category": "品类",
        "customer": "客户",
        "store": "门店",
        "team": "团队",
        "service_line": "服务线",
        "segment": "客群",
        "month": "月份",
        "date": "日期",
        "sales": "销售额",
        "revenue": "收入",
        "amount": "金额",
        "profit": "利润",
    }
    return mapping.get(str(column or "").strip().lower(), str(column or "字段"))


def _safe_id(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value or "").strip()).strip("_") or "uploaded_dataset"


def _resolve_path(path: str) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved
    return resolved


def re_search(pattern: str, value: str) -> bool:
    import re

    return re.search(pattern, str(value or ""), re.I) is not None


def _load_simulator_client(provider: str) -> LLMClient | None:
    if provider == "deterministic":
        return None
    if provider == "mock":
        return MockLLMClient()
    try:
        client = load_llm_client_from_env()
    except MissingLLMConfigError as exc:
        raise RuntimeError("LLM user simulator requires VDS_LLM_PROVIDER and matching API key.") from exc
    if isinstance(client, MockLLMClient):
        raise RuntimeError("Mock LLM is not valid for --simulator-provider env; use --simulator-provider mock for smoke checks.")
    return client


def _load_agent_client(provider: str) -> LLMClient:
    if provider == "mock":
        return MockLLMClient()
    try:
        return load_llm_client_from_env()
    except MissingLLMConfigError as exc:
        raise RuntimeError("Agent env provider requires VDS_LLM_PROVIDER and matching API key.") from exc


def write_eval_artifacts(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    """Write machine-readable and review-friendly eval artifacts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    index_path = output_dir / "index.html"
    turn_records_path = output_dir / "turn_records.csv"
    conversations_path = output_dir / "conversation_records.jsonl"

    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_report_markdown(report), encoding="utf-8")
    index_path.write_text(_report_html(report), encoding="utf-8")
    _write_turn_records_csv(report, turn_records_path)
    _write_conversation_records_jsonl(report, conversations_path)
    return {
        "index_html": str(index_path),
        "summary_json": str(summary_path),
        "report_md": str(report_path),
        "turn_records_csv": str(turn_records_path),
        "conversation_records_jsonl": str(conversations_path),
    }


def _report_markdown(report: dict[str, Any]) -> str:
    failure_rows = _failure_rows(report)
    lines = [
        "# Agent Random Conversation Eval Report",
        "",
        "Open `index.html` in the same folder for the visual report.",
        "",
        "Artifacts: `summary.json`, `turn_records.csv`, `conversation_records.jsonl`.",
        "",
        "## 结论",
        "",
        f"- 结果: {'PASS' if report.get('passed') else 'FAIL'}",
        f"- 通过率: {float(report.get('pass_rate') or 0.0):.2%}",
        f"- Gate passed: {report.get('gate_passed', (report.get('gate_result') or {}).get('gate_passed', False))}",
        f"- Gate failed reasons: {_join_or_none(report.get('gate_failed_reasons') or (report.get('gate_result') or {}).get('gate_failed_reasons') or [])}",
        f"- 对话数: {report.get('conversation_count')}；场景数: {report.get('scenario_count')}；每场景运行: {report.get('runs_per_scenario')}",
        f"- Scenario family: {report.get('scenario_family') or '-'}",
        f"- Scenario families: {_join_or_none(report.get('scenario_families') or [])}",
        f"- 随机种子: {report.get('seed')}；用户模拟器: {report.get('simulator_source')}",
        f"- 全局问题: {_join_or_none(report.get('global_issues') or [])}",
        "",
        "## 阅读指南",
        "",
        "- 每个“对话”代表一次上传数据后的连续会话。",
        "- “初始问题”是会话入口；第 2 轮以后都按会话内连续提问检查，必须复用同一个 conversation_id。",
        "- 如果上下文状态为“未识别为追问”，说明这一轮没有可靠继承上一轮分析口径，即使单轮 SQL 成功也不能算 Agent 连续对话能力稳定。",
        "- 内置场景的问题由 schema 和随机种子生成，不使用旧 BigCat 截图里的固定展示题。",
        "",
        "## Thresholds",
    ]
    thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), dict) else {}
    for key, value in thresholds.items():
        lines.append(f"- {key}: {value}")
    if isinstance(report.get("gate_result"), dict):
        lines.extend(["", eval_gate_markdown(report["gate_result"], title="Multi-metric Eval Gate")])
    lines.extend(["", "## Coverage"])
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    lines.append(f"- Turn count: {coverage.get('turn_count', 0)}")
    lines.append(f"- Conversation continuation turns: {coverage.get('post_initial_turns', coverage.get('requested_followup_turns', 0))}")
    lines.append(f"- Contextualized continuation turns: {coverage.get('contextualized_post_initial_turns', coverage.get('followup_turns', 0))}")
    lines.append(f"- Missing continuation context turns: {coverage.get('missing_post_initial_context_turns', coverage.get('missing_followup_context_turns', 0))}")
    lines.append(f"- Structured action turns: {coverage.get('structured_action_turns', 0)}")
    lines.append(f"- Structured answer turns: {coverage.get('structured_answer_turns', 0)}")
    lines.append(f"- Capability families: {_join_or_none(coverage.get('capability_families') or [])}")
    lines.append(f"- Scenario families: {_join_or_none(coverage.get('scenario_families') or [])}")
    lines.append(f"- Operations: {_join_or_none(coverage.get('operations') or [])}")
    lines.extend(["", "## Scenario Family Summary"])
    family_rows = (coverage.get("family_summary") or {}).get("families") if isinstance(coverage.get("family_summary"), dict) else []
    if family_rows:
        lines.extend(
            [
                "| family | conversations | pass_rate | semantic_pass_rate | oracle_pass_rate | expected_contract_pass_rate | top_violation_codes |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for item in family_rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_markdown_table_cell(item.get("family")),
                        str(item.get("conversation_count", 0)),
                        _display_summary_rate(item.get("pass_rate")),
                        _display_summary_rate(item.get("semantic_pass_rate")),
                        _display_summary_rate(item.get("oracle_pass_rate")),
                        _display_summary_rate(item.get("expected_contract_pass_rate")),
                        _escape_markdown_table_cell(", ".join(f"{code.get('code')}={code.get('count')}" for code in item.get("top_violation_codes", []) if isinstance(code, dict)) or "none"),
                    ]
                )
                + " |"
            )
    else:
        lines.append("not_available")
    lines.extend(["", "## Semantic Contract Summary"])
    lines.append(f"- Semantic contract turns: {coverage.get('semantic_contract_turns', 0)}")
    lines.append(f"- Oracle result turns: {coverage.get('oracle_result_turns', 0)}")
    lines.append(f"- Oracle available turns: {coverage.get('oracle_available_turns', 0)}")
    lines.append(f"- Oracle passed turns: {coverage.get('oracle_passed_turns', 0)}")
    lines.append(f"- Oracle failed turns: {coverage.get('oracle_failed_turns', 0)}")
    lines.append(f"- Oracle passed: {coverage.get('oracle_passed', coverage.get('oracle_passed_turns', 0))}")
    lines.append(f"- Oracle failed: {coverage.get('oracle_failed', coverage.get('oracle_failed_turns', 0))}")
    lines.append(f"- Oracle expected missing: {coverage.get('oracle_expected_missing', coverage.get('oracle_expected_result_missing_turns', 0))}")
    lines.append(f"- Oracle actual missing: {coverage.get('oracle_actual_missing', coverage.get('oracle_actual_result_missing_turns', 0))}")
    lines.append(f"- Contract checked turns: {coverage.get('contract_checked_turns', 0)}")
    lines.append(f"- Contract satisfied turns: {coverage.get('contract_satisfied_turns', 0)}")
    lines.append(f"- Semantic passed turns: {coverage.get('semantic_passed_turns', 0)}")
    lines.append(f"- Semantic failed turns: {coverage.get('semantic_failed_turns', 0)}")
    lines.append(f"- Corrected passed turns: {coverage.get('corrected_passed_turns', 0)}")
    lines.append(f"- Needs clarification turns: {coverage.get('needs_clarification_turns', 0)}")
    violation_rows = coverage.get("top_contract_violation_codes") if isinstance(coverage.get("top_contract_violation_codes"), list) else []
    if violation_rows:
        lines.append("- Top contract violation codes: " + ", ".join(f"{item.get('code')}={item.get('count')}" for item in violation_rows if isinstance(item, dict)))
    else:
        lines.append("- Top contract violation codes: none")
    lines.extend(["", "## 失败索引"])
    if failure_rows:
        lines.extend(
            [
                "| 对话 | 轮次 | 用户问题 | required_operation | actual_operation | 上下文 | Issues |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in failure_rows:
            lines.append(
                "| "
                + " | ".join(
                    _escape_markdown_table_cell(row.get(key, ""))
                    for key in ("conversation", "turn", "question", "required_operation", "operation", "context_status", "issues")
                )
                + " |"
            )
    else:
        lines.append("none")
    lines.extend(["", "## 对话流"])
    for conversation_index, result in enumerate(report.get("results") or [], start=1):
        title = f"{result.get('scenario_id')}#{result.get('run_index')}"
        turns = result.get("turns") or []
        requested_followups = sum(1 for turn in turns if int(turn.get("index") or 0) > 1)
        recognized_followups = sum(1 for turn in turns if int(turn.get("index") or 0) > 1 and _serialized_turn_has_context(turn))
        lines.extend(
            [
                f"### 对话 {conversation_index}: {title}",
                f"- 结果: {'PASS' if result.get('passed') else 'FAIL'}",
                f"- 能力族: {result.get('capability_family')}",
                f"- Scenario family: {result.get('scenario_family') or '-'}",
                f"- 轮次: {len(turns)}；会话内连续提问: {requested_followups}；已识别上下文: {recognized_followups}",
                f"- Issues: {_join_or_none(result.get('issues') or [])}",
                "",
            ]
        )
        for turn in turns:
            lines.extend(_turn_markdown_lines(turn))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _turn_markdown_lines(turn: dict[str, Any]) -> list[str]:
    action_questions = turn.get("next_action_questions") if isinstance(turn.get("next_action_questions"), list) else []
    actions = "; ".join(str(item) for item in action_questions) if action_questions else "none"
    return [
        f"#### 第 {turn.get('index')} 轮 · {turn.get('turn_role') or '-'}",
        f"- 用户问题: {turn.get('question')}",
        (
            f"- 执行结果: {'成功' if turn.get('success') else '失败'}；"
            f"required_operation={turn.get('required_operation') or '-'}；"
            f"actual_operation={turn.get('operation') or '-'}；answer_type={turn.get('answer_type') or '-'}；"
            f"capability={turn.get('capability_family') or '-'}；scenario_family={turn.get('scenario_family') or '-'}"
        ),
        (
            f"- 语义契约: status={turn.get('semantic_status') or 'legacy_unverified'}；"
            f"contract_family={turn.get('contract_family') or '-'}；"
            f"contract_satisfied={turn.get('contract_satisfied')}；"
            f"violations={_join_or_none(turn.get('contract_violation_codes') or [])}；"
            f"oracle_available={turn.get('oracle_available')}"
        ),
        (
            f"- 口径对齐: expected_metric={turn.get('expected_metric') or '-'}；actual_metric={turn.get('actual_metric') or '-'}；"
            f"expected_dimension={turn.get('expected_dimension') or '-'}；actual_dimension={turn.get('actual_dimension') or '-'}"
        ),
        f"- 上下文: {turn.get('context_status') or '-'}；conversation_id={turn.get('conversation_id') or '-'}",
        f"- 结构化回答: sections={turn.get('section_count', 0)}；structured={turn.get('structured_answer')}",
        f"- 回答摘要: {_preview_text(turn.get('answer_preview'), limit=260) or '未记录'}",
        f"- 下一步 actions: {actions}",
        "",
    ]


def _report_html(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    passed = bool(report.get("passed"))
    status_class = "pass" if passed else "fail"
    metric_cards = [
        ("通过率", _format_percent(report.get("pass_rate"))),
        ("对话数", str(report.get("conversation_count", 0))),
        ("Scenario families", str(len(coverage.get("scenario_families") or []))),
        ("总轮次", str(coverage.get("turn_count", 0))),
        ("会话内后续提问轮次", str(coverage.get("post_initial_turns", coverage.get("requested_followup_turns", 0)))),
        ("已识别上下文轮次", str(coverage.get("contextualized_post_initial_turns", coverage.get("followup_turns", 0)))),
        ("未识别上下文轮次", str(coverage.get("missing_post_initial_context_turns", coverage.get("missing_followup_context_turns", 0)))),
        ("结构化 action 轮次", str(coverage.get("structured_action_turns", 0))),
        ("语义契约轮次", str(coverage.get("semantic_contract_turns", 0))),
        ("契约满足轮次", str(coverage.get("contract_satisfied_turns", 0))),
        ("能力族数量", str(len(coverage.get("capability_families") or []))),
    ]
    threshold_rows = _threshold_rows(report, coverage)
    conversations = report.get("results") or []
    global_issues = report.get("global_issues") or []
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Random Conversation Eval</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f2;
      --surface: #ffffff;
      --text: #18201f;
      --muted: #66706b;
      --line: #d9dfd8;
      --pass: #177245;
      --pass-bg: #e7f5ed;
      --fail: #b42318;
      --fail-bg: #fde8e5;
      --warn: #9a6700;
      --warn-bg: #fff3c4;
      --accent: #285a83;
      --accent-bg: #e7f0f8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 44px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; line-height: 1.2; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 10px; font-size: 18px; letter-spacing: 0; }}
    h3 {{ margin: 0; font-size: 16px; letter-spacing: 0; }}
    .muted {{ color: var(--muted); }}
    .badge {{
      display: inline-flex; align-items: center; min-height: 30px; padding: 4px 10px;
      border-radius: 999px; font-weight: 700; border: 1px solid transparent; white-space: nowrap;
    }}
    .badge.pass {{ color: var(--pass); background: var(--pass-bg); border-color: #acd8bf; }}
    .badge.fail {{ color: var(--fail); background: var(--fail-bg); border-color: #f4b8b2; }}
    .grid {{ display: grid; gap: 10px; }}
    .metrics {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 16px 0 10px; }}
    .metric {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .metric .label {{ color: var(--muted); font-size: 12px; }}
    .metric .value {{ font-size: 22px; font-weight: 750; margin-top: 2px; }}
    .panel {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .artifacts a {{ display: inline-flex; margin: 6px 8px 0 0; padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px; color: var(--accent); text-decoration: none; background: #fbfcfa; }}
    .artifacts a:hover {{ border-color: #9fb7cb; background: var(--accent-bg); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; color: var(--muted); background: #f8faf7; }}
    tr:last-child td {{ border-bottom: 0; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .chip {{ display: inline-flex; gap: 5px; align-items: center; padding: 4px 8px; border-radius: 999px; background: var(--accent-bg); color: var(--accent); font-size: 12px; }}
    .chip.pass {{ background: var(--pass-bg); color: var(--pass); }}
    .chip.fail {{ background: var(--fail-bg); color: var(--fail); }}
    .chip.warn {{ background: var(--warn-bg); color: var(--warn); }}
    details {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; margin: 12px 0; }}
    summary {{ cursor: pointer; padding: 13px 14px; list-style: none; display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
    summary::-webkit-details-marker {{ display: none; }}
    .conversation-body {{ border-top: 1px solid var(--line); padding: 12px 14px 14px; }}
    .timeline {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 12px; }}
    .timeline-item {{ display: inline-grid; gap: 2px; min-width: 132px; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--line); background: #fbfcfa; }}
    .timeline-item.pass {{ border-color: #acd8bf; background: var(--pass-bg); }}
    .timeline-item.fail {{ border-color: #f4b8b2; background: var(--fail-bg); }}
    .timeline-label {{ font-size: 12px; font-weight: 750; }}
    .timeline-op {{ font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }}
    .failure-table td:nth-child(3) {{ min-width: 260px; }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; margin: 8px 0; }}
    .meta-cell {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: #fbfcfa; }}
    .meta-cell .label {{ color: var(--muted); font-size: 12px; }}
    .meta-cell .value {{ margin-top: 2px; font-weight: 650; overflow-wrap: anywhere; }}
    .turn {{ display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--line); }}
    .turn:last-child {{ border-bottom: 0; }}
    .turn-number {{ width: 58px; height: 58px; border: 1px solid var(--line); border-radius: 8px; display: grid; place-items: center; font-weight: 800; background: #fbfcfa; }}
    .turn-meta {{ display: flex; flex-wrap: wrap; gap: 7px; margin: 0 0 8px; }}
    .question, .answer {{ padding: 10px 12px; border-radius: 8px; margin-top: 8px; }}
    .question {{ background: #f1f5f9; border: 1px solid #d8e1ea; }}
    .answer {{ background: #fbfcfa; border: 1px solid var(--line); white-space: pre-wrap; }}
    .actions {{ margin: 9px 0 0; padding-left: 18px; }}
    .actions li {{ margin: 3px 0; }}
    .issues {{ color: var(--fail); }}
    @media (max-width: 720px) {{
      main {{ padding: 20px 12px 34px; }}
      header, summary {{ display: block; }}
      .badge {{ margin-top: 8px; }}
      .turn {{ grid-template-columns: 1fr; }}
      .turn-number {{ width: auto; height: 38px; justify-content: start; padding: 0 12px; }}
      table {{ display: block; overflow-x: auto; white-space: nowrap; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Agent Random Conversation Eval</h1>
        <div class="muted">generated_at={_html(report.get('generated_at'))} · seed={_html(report.get('seed'))} · simulator={_html(report.get('simulator_source'))}</div>
      </div>
      <div class="badge {status_class}">{'PASS' if passed else 'FAIL'}</div>
    </header>

    <section class="grid metrics">
      {_metric_cards_html(metric_cards)}
    </section>

    <section class="panel">
      <h2>结论</h2>
      <p>{_html(report.get('policy'))}</p>
      <p><strong>全局问题：</strong>{_issue_text_html(global_issues)}</p>
      <p class="muted">阅读方式：一个卡片是一段完整对话；第 1 轮是初始问题，第 2 轮以后需要显示已识别上下文，才说明 Agent 继承了前文口径。</p>
    </section>

    <section class="panel artifacts">
      <h2>可查看记录</h2>
      <a href="report.md">Markdown 报告</a>
      <a href="summary.json">完整 JSON</a>
      <a href="turn_records.csv">逐轮 CSV</a>
      <a href="conversation_records.jsonl">逐对话 JSONL</a>
    </section>

    <h2>门槛检查</h2>
    <table>
      <thead><tr><th>指标</th><th>实际</th><th>门槛</th><th>结果</th></tr></thead>
      <tbody>
        {_threshold_table_html(threshold_rows)}
      </tbody>
    </table>

    <h2>能力覆盖</h2>
    <div class="panel">
      <h3>Scenario Families</h3>
      <div class="chips">{_count_chips_html(coverage.get('scenario_family_counts') or {})}</div>
      <h3 style="margin-top: 16px;">Capability Families</h3>
      <div class="chips">{_count_chips_html(coverage.get('capability_family_counts') or {})}</div>
      <h3 style="margin-top: 16px;">Operations</h3>
      <div class="chips">{_count_chips_html(coverage.get('operation_counts') or {})}</div>
    </div>

    <h2>Scenario Family Summary</h2>
    <div class="panel">
      {_scenario_family_summary_html(coverage)}
    </div>

    <h2>Semantic Contract Summary</h2>
    <div class="panel">
      {_semantic_contract_summary_html(coverage)}
    </div>

    <h2>失败定位</h2>
    {_failure_overview_html(report)}

    <h2>对话记录</h2>
    {_conversations_html(conversations)}
  </main>
</body>
</html>
"""


def _metric_cards_html(cards: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<div class="metric"><div class="label">{_html(label)}</div><div class="value">{_html(value)}</div></div>'
        for label, value in cards
    )


def _threshold_rows(report: dict[str, Any], coverage: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), dict) else {}
    actuals = {
        "min_pass_rate": float(report.get("pass_rate") or 0.0),
        "min_conversations": int(report.get("conversation_count") or 0),
        "min_capability_families": len(coverage.get("capability_families") or []),
        "min_followup_turns": int(coverage.get("contextualized_post_initial_turns", coverage.get("followup_turns") or 0) or 0),
        "min_structured_action_turns": int(coverage.get("structured_action_turns") or 0),
        "min_structured_answer_turns": int(coverage.get("structured_answer_turns") or 0),
    }
    labels = {
        "min_pass_rate": "通过率",
        "min_conversations": "对话数",
        "min_capability_families": "能力族数量",
        "min_followup_turns": "已识别上下文轮次",
        "min_structured_action_turns": "结构化 action 轮次",
        "min_structured_answer_turns": "结构化回答轮次",
    }
    rows = []
    for key, threshold in thresholds.items():
        actual = actuals.get(key, 0)
        rows.append(
            {
                "label": labels.get(key, key),
                "actual": _format_threshold_value(key, actual),
                "threshold": _format_threshold_value(key, threshold),
                "passed": float(actual) >= float(threshold or 0),
            }
        )
    return rows


def _threshold_table_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="4" class="muted">no thresholds</td></tr>'
    rendered = []
    for row in rows:
        status = "PASS" if row["passed"] else "FAIL"
        klass = "pass" if row["passed"] else "fail"
        rendered.append(
            "<tr>"
            f"<td>{_html(row['label'])}</td>"
            f"<td>{_html(row['actual'])}</td>"
            f"<td>{_html(row['threshold'])}</td>"
            f'<td><span class="chip {klass}">{status}</span></td>'
            "</tr>"
        )
    return "\n".join(rendered)


def _scenario_family_summary_html(coverage: dict[str, Any]) -> str:
    summary = coverage.get("family_summary") if isinstance(coverage.get("family_summary"), dict) else {}
    rows = summary.get("families") if isinstance(summary.get("families"), list) else []
    if not rows:
        return '<span class="muted">not_available</span>'
    rendered = [
        "<table>",
        "<thead><tr><th>Family</th><th>Conversations</th><th>Pass</th><th>Semantic</th><th>Oracle</th><th>Expected contract</th><th>Top violations</th></tr></thead>",
        "<tbody>",
    ]
    for row in rows:
        top_codes = ", ".join(
            f"{item.get('code')}={item.get('count')}"
            for item in row.get("top_violation_codes", [])
            if isinstance(item, dict)
        ) or "none"
        rendered.append(
            "<tr>"
            f"<td>{_html(row.get('family'))}</td>"
            f"<td>{_html(row.get('conversation_count', 0))}</td>"
            f"<td>{_html(_display_summary_rate(row.get('pass_rate')))}</td>"
            f"<td>{_html(_display_summary_rate(row.get('semantic_pass_rate')))}</td>"
            f"<td>{_html(_display_summary_rate(row.get('oracle_pass_rate')))}</td>"
            f"<td>{_html(_display_summary_rate(row.get('expected_contract_pass_rate')))}</td>"
            f"<td>{_html(top_codes)}</td>"
            "</tr>"
        )
    rendered.extend(["</tbody>", "</table>"])
    return "\n".join(rendered)


def _semantic_contract_summary_html(coverage: dict[str, Any]) -> str:
    metrics = [
        ("semantic_contract_turns", "Semantic contract turns"),
        ("oracle_result_turns", "Oracle result turns"),
        ("oracle_available_turns", "Oracle available turns"),
        ("oracle_passed_turns", "Oracle passed turns"),
        ("oracle_failed_turns", "Oracle failed turns"),
        ("oracle_passed", "Oracle passed"),
        ("oracle_failed", "Oracle failed"),
        ("oracle_expected_missing", "Oracle expected missing"),
        ("oracle_actual_missing", "Oracle actual missing"),
        ("contract_checked_turns", "Contract checked turns"),
        ("contract_satisfied_turns", "Contract satisfied turns"),
        ("semantic_passed_turns", "Semantic passed turns"),
        ("semantic_failed_turns", "Semantic failed turns"),
        ("corrected_passed_turns", "Corrected passed turns"),
        ("needs_clarification_turns", "Needs clarification turns"),
    ]
    cells = [
        f'<div class="meta-cell"><div class="label">{_html(label)}</div><div class="value">{_html(coverage.get(key, 0))}</div></div>'
        for key, label in metrics
    ]
    violations = coverage.get("top_contract_violation_codes") if isinstance(coverage.get("top_contract_violation_codes"), list) else []
    if violations:
        violation_html = _inline_chips_html(
            [
                ("fail", f"{item.get('code')}={item.get('count')}")
                for item in violations
                if isinstance(item, dict)
            ]
        )
    else:
        violation_html = '<span class="chip pass">no contract violations</span>'
    return f'<div class="meta-grid">{"".join(cells)}</div><h3 style="margin-top: 16px;">Top Contract Violation Codes</h3><div class="chips">{violation_html}</div>'


def _conversations_html(results: list[dict[str, Any]]) -> str:
    if not results:
        return '<div class="panel muted">没有对话记录。</div>'
    return "\n".join(_conversation_html(result) for result in results)


def _conversation_html(result: dict[str, Any]) -> str:
    passed = bool(result.get("passed"))
    status_class = "pass" if passed else "fail"
    turns = result.get("turns") or []
    issues = result.get("issues") or []
    requested_followups = sum(1 for turn in turns if int(turn.get("index") or 0) > 1)
    recognized_followups = sum(1 for turn in turns if int(turn.get("index") or 0) > 1 and _serialized_turn_has_context(turn))
    title = f"{result.get('scenario_id')}#{result.get('run_index')}"
    issues_by_turn = _issues_by_turn(issues)
    conversation_issues = _conversation_level_issues(issues)
    return f"""
<details open>
  <summary>
    <div>
      <h3>{_html(title)}</h3>
      <div class="muted">{len(turns)} 轮 · 会话内后续提问 {requested_followups} 轮 · 已识别上下文 {recognized_followups} 轮 · scenario_family={_html(result.get('scenario_family'))} · capability={_html(result.get('capability_family'))}</div>
    </div>
    <span class="badge {status_class}">{'PASS' if passed else 'FAIL'}</span>
  </summary>
  <div class="conversation-body">
    <div><strong>Conversation issues:</strong> {_issue_text_html(conversation_issues)}</div>
    {_timeline_html(turns, issues_by_turn)}
    {_turns_html(turns, issues_by_turn)}
  </div>
</details>
"""


def _turns_html(turns: list[dict[str, Any]], issues_by_turn: dict[int, list[str]]) -> str:
    return "\n".join(_turn_html(turn, issues_by_turn.get(int(turn.get("index") or 0), [])) for turn in turns)


def _turn_html(turn: dict[str, Any], turn_issues: list[str]) -> str:
    success = bool(turn.get("success")) and not turn_issues and _serialized_turn_operation_matches(turn)
    structured = bool(turn.get("structured_answer"))
    action_questions = turn.get("next_action_questions") if isinstance(turn.get("next_action_questions"), list) else []
    context_status = str(turn.get("context_status") or "-")
    context_class = "pass" if context_status.startswith("已识别") or context_status == "新会话入口" else "warn"
    operation_match = _serialized_turn_operation_matches(turn)
    operation_text = f"{turn.get('required_operation') or '-'} -> {turn.get('operation') or '-'}"
    chips = [
        ("pass" if success else "fail", "turn ok" if success else "turn failed"),
        ("", str(turn.get("turn_role") or "-")),
        (context_class, context_status),
        ("", str(turn.get("capability_family") or "capability:-")),
        ("pass" if operation_match else "fail", f"operation {operation_text}"),
        ("", str(turn.get("answer_type") or "answer:-")),
        ("pass" if structured else "warn", f"sections={turn.get('section_count', 0)}"),
    ]
    semantic_status = str(turn.get("semantic_status") or "legacy_unverified")
    semantic_class = "pass" if semantic_status in {"passed", "corrected_passed"} else "fail" if semantic_status == "failed" else "warn"
    chips.append((semantic_class, f"semantic={semantic_status}"))
    if turn.get("contract_family"):
        chips.append(("", f"contract={turn.get('contract_family')}"))
    if turn.get("contract_violation_codes"):
        chips.append(("fail", "violations=" + ",".join(str(item) for item in turn.get("contract_violation_codes") or [])))
    if turn.get("followup_reason"):
        chips.append(("pass", str(turn.get("followup_reason"))))
    return f"""
<div class="turn">
  <div class="turn-number">Turn {_html(turn.get('index'))}</div>
  <div>
    <div class="turn-meta">{_inline_chips_html(chips)}</div>
    <div class="question"><strong>用户问题：</strong>{_html(turn.get('question'))}</div>
    <div class="meta-grid">
      <div class="meta-cell"><div class="label">预期能力</div><div class="value">{_html(turn.get('capability_family') or '-')}</div></div>
      <div class="meta-cell"><div class="label">预期 / 实际 operation</div><div class="value">{_html(operation_text)}</div></div>
      <div class="meta-cell"><div class="label">预期 / 实际指标</div><div class="value">{_html(turn.get('expected_metric') or '-')} -> {_html(turn.get('actual_metric') or '-')}</div></div>
      <div class="meta-cell"><div class="label">预期 / 实际维度</div><div class="value">{_html(turn.get('expected_dimension') or '-')} -> {_html(turn.get('actual_dimension') or '-')}</div></div>
      <div class="meta-cell"><div class="label">上下文状态</div><div class="value">{_html(context_status)}</div></div>
      <div class="meta-cell"><div class="label">语义契约</div><div class="value">{_html(semantic_status)} / {_html(turn.get('contract_family') or '-')} / satisfied={_html(turn.get('contract_satisfied'))}</div></div>
      <div class="meta-cell"><div class="label">本轮问题</div><div class="value">{_issue_text_html(turn_issues)}</div></div>
    </div>
    <div class="answer"><strong>Agent 回答摘要：</strong>{_html(turn.get('answer_preview') or '未记录回答摘要')}</div>
    <div><strong>下一步 actions：</strong>{_actions_html(action_questions)}</div>
  </div>
</div>
"""


def _timeline_html(turns: list[dict[str, Any]], issues_by_turn: dict[int, list[str]]) -> str:
    if not turns:
        return ""
    items = []
    for turn in turns:
        index = int(turn.get("index") or 0)
        turn_ok = bool(turn.get("success")) and not issues_by_turn.get(index) and _serialized_turn_operation_matches(turn)
        klass = "pass" if turn_ok else "fail"
        items.append(
            f'<div class="timeline-item {klass}" title="{_html(turn.get("question"))}">'
            f'<div class="timeline-label">T{_html(index)} · {_html(turn.get("turn_role") or "-")}</div>'
            f'<div class="timeline-op">{_html(turn.get("required_operation") or "-")} -> {_html(turn.get("operation") or "-")}</div>'
            "</div>"
        )
    return '<div class="timeline">' + "".join(items) + "</div>"


def _failure_overview_html(report: dict[str, Any]) -> str:
    rows = _failure_rows(report)
    if not rows:
        return '<div class="panel"><span class="chip pass">没有失败轮次</span></div>'
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{_html(row.get('conversation'))}</td>"
            f"<td>{_html(row.get('turn'))}</td>"
            f"<td>{_html(row.get('question'))}</td>"
            f"<td>{_html(row.get('required_operation') or '-')}</td>"
            f"<td>{_html(row.get('operation') or '-')}</td>"
            f"<td>{_html(row.get('context_status') or '-')}</td>"
            f"<td>{_html(row.get('issues') or '-')}</td>"
            "</tr>"
        )
    return (
        '<table class="failure-table">'
        "<thead><tr><th>对话</th><th>轮次</th><th>用户问题</th><th>预期 operation</th><th>实际 operation</th><th>上下文</th><th>失败原因</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _failure_rows(report: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for result in report.get("results") or []:
        title = f"{result.get('scenario_id')}#{result.get('run_index')}"
        issues = [str(issue) for issue in result.get("issues") or []]
        issues_by_turn = _issues_by_turn(issues)
        for issue in _conversation_level_issues(issues):
            rows.append(
                {
                    "conversation": title,
                    "turn": "conversation",
                    "question": "-",
                    "required_operation": "-",
                    "operation": "-",
                    "context_status": "-",
                    "issues": issue,
                }
            )
        for turn in result.get("turns") or []:
            index = int(turn.get("index") or 0)
            turn_issues = list(issues_by_turn.get(index, []))
            if not _serialized_turn_operation_matches(turn):
                turn_issues.append(
                    f"operation_mismatch:expected={turn.get('required_operation') or '-'}:actual={turn.get('operation') or '-'}"
                )
            expected_kind = str(turn.get("expected_kind") or "")
            if expected_kind in ANALYSIS_TURN_KINDS and not _is_turn_semantically_successful(turn) and not any(
                issue.endswith(":analysis_failed") for issue in turn_issues
            ):
                turn_issues.append("analysis_failed")
            if not turn_issues:
                continue
            rows.append(
                {
                    "conversation": title,
                    "turn": str(index),
                    "question": str(turn.get("question") or ""),
                    "required_operation": str(turn.get("required_operation") or "-"),
                    "operation": str(turn.get("operation") or "-"),
                    "context_status": str(turn.get("context_status") or "-"),
                    "issues": "; ".join(dict.fromkeys(turn_issues)),
                }
            )
    for issue in report.get("global_issues") or []:
        rows.insert(
            0,
            {
                "conversation": "global",
                "turn": "-",
                "question": "-",
                "required_operation": "-",
                "operation": "-",
                "context_status": "-",
                "issues": str(issue),
            },
        )
    return rows


def _issues_by_turn(issues: list[Any]) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = {}
    for issue in issues:
        index = _issue_turn_index(issue)
        if index is not None:
            grouped.setdefault(index, []).append(str(issue))
    return grouped


def _conversation_level_issues(issues: list[Any]) -> list[str]:
    return [str(issue) for issue in issues if _issue_turn_index(issue) is None]


def _issue_turn_index(issue: Any) -> int | None:
    text = str(issue or "")
    if not text.startswith("turn_"):
        return None
    turn_part = text[5:].split(":", 1)[0]
    return int(turn_part) if turn_part.isdigit() else None


def _serialized_turn_has_context(turn: dict[str, Any]) -> bool:
    return bool(turn.get("followup_reason")) or str(turn.get("context_status") or "").startswith("已识别")


def _serialized_turn_operation_matches(turn: dict[str, Any]) -> bool:
    required = str(turn.get("required_operation") or "")
    if not required:
        return True
    observed = str(turn.get("operation") or "")
    return _operation_present(required, {observed})


def _inline_chips_html(chips: list[tuple[str, str]]) -> str:
    return "".join(f'<span class="chip {klass}">{_html(text)}</span>' for klass, text in chips)


def _actions_html(actions: list[Any]) -> str:
    if not actions:
        return '<span class="muted">none</span>'
    items = "".join(f"<li>{_html(action)}</li>" for action in actions)
    return f'<ol class="actions">{items}</ol>'


def _count_chips_html(counts: dict[str, Any]) -> str:
    if not counts:
        return '<span class="muted">none</span>'
    return "".join(f'<span class="chip">{_html(key)} <strong>{_html(value)}</strong></span>' for key, value in sorted(counts.items()))


def _issue_text_html(issues: list[Any]) -> str:
    if not issues:
        return '<span class="chip pass">none</span>'
    return " ".join(f'<span class="chip fail">{_html(issue)}</span>' for issue in issues)


def _format_percent(value: Any) -> str:
    return f"{float(value or 0.0):.0%}"


def _display_summary_rate(value: Any) -> str:
    if isinstance(value, (float, int)):
        return f"{float(value):.2%}"
    return str(value or "not_available")


def _format_threshold_value(key: str, value: Any) -> str:
    if key == "min_pass_rate":
        return _format_percent(value)
    return str(value)


def _html(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _write_turn_records_csv(report: dict[str, Any], path: Path) -> None:
    fieldnames = [
        "scenario_id",
        "scenario_family",
        "run_index",
        "turn_index",
        "turn_role",
        "conversation_turn",
        "scenario_passed",
        "capability_family",
        "expected_kind",
        "required_operation",
        "operation",
        "operation_match",
        "expected_metric",
        "actual_metric",
        "expected_dimension",
        "actual_dimension",
        "answer_type",
        "semantic_status",
        "contract_satisfied",
        "contract_family",
        "contract_checked",
        "contract_violation_codes",
        "violations",
        "oracle_available",
        "oracle_passed",
        "oracle_issue_codes",
        "oracle_issue_metadata",
        "expected_result_present",
        "actual_result_present",
        "context_status",
        "followup_reason",
        "action_count",
        "section_count",
        "question",
        "answer_preview",
        "next_action_questions",
        "turn_issues",
        "issues",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in report.get("results") or []:
            issues = ";".join(str(issue) for issue in result.get("issues") or [])
            issues_by_turn = _issues_by_turn(result.get("issues") or [])
            for turn in result.get("turns") or []:
                turn_index = int(turn.get("index") or 0)
                turn_issues = issues_by_turn.get(turn_index, [])
                writer.writerow(
                    {
                        "scenario_id": result.get("scenario_id"),
                        "scenario_family": result.get("scenario_family") or turn.get("scenario_family") or "",
                        "run_index": result.get("run_index"),
                        "turn_index": turn_index,
                        "turn_role": turn.get("turn_role") or "",
                        "conversation_turn": bool(turn.get("conversation_turn")),
                        "scenario_passed": result.get("passed"),
                        "capability_family": turn.get("capability_family"),
                        "expected_kind": turn.get("expected_kind"),
                        "required_operation": turn.get("required_operation") or "",
                        "operation": turn.get("operation"),
                        "operation_match": _serialized_turn_operation_matches(turn),
                        "expected_metric": turn.get("expected_metric") or "",
                        "actual_metric": turn.get("actual_metric") or "",
                        "expected_dimension": turn.get("expected_dimension") or "",
                        "actual_dimension": turn.get("actual_dimension") or "",
                        "answer_type": turn.get("answer_type"),
                        "semantic_status": turn.get("semantic_status") or "",
                        "contract_satisfied": turn.get("contract_satisfied"),
                        "contract_family": turn.get("contract_family") or "",
                        "contract_checked": bool(turn.get("contract_checked")),
                        "contract_violation_codes": ";".join(str(item) for item in turn.get("contract_violation_codes") or []),
                        "violations": ";".join(str(item) for item in turn.get("contract_violation_codes") or []),
                        "oracle_available": bool(turn.get("oracle_available")),
                        "oracle_passed": turn.get("oracle_passed"),
                        "oracle_issue_codes": ";".join(str(item) for item in turn.get("oracle_issue_codes") or []),
                        "oracle_issue_metadata": json.dumps(turn.get("oracle_issue_metadata") or {}),
                        "expected_result_present": bool(turn.get("expected_result") is not None),
                        "actual_result_present": bool(turn.get("actual_result") is not None),
                        "context_status": turn.get("context_status") or "",
                        "followup_reason": turn.get("followup_reason") or "",
                        "action_count": turn.get("action_count", 0),
                        "section_count": turn.get("section_count", 0),
                        "question": turn.get("question"),
                        "answer_preview": turn.get("answer_preview") or "",
                        "next_action_questions": " | ".join(str(item) for item in turn.get("next_action_questions") or []),
                        "turn_issues": ";".join(str(issue) for issue in turn_issues),
                        "issues": issues,
                    }
                )


def _write_conversation_records_jsonl(report: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for result in report.get("results") or []:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")


def _join_or_none(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values) if values else "none"


def _preview_text(value: Any, *, limit: int = 320) -> str:
    text = " ".join(str(value or "").strip().split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _action_questions(actions: list[dict[str, Any]]) -> list[str]:
    previews = []
    for action in actions[:6]:
        question = _preview_text(action.get("question") or action.get("label") or "", limit=140)
        operation = str(action.get("operation") or "").strip()
        capability = str(action.get("capability_family") or "").strip()
        if not question and operation:
            question = operation
        if capability and capability not in question:
            question = f"{question} [{capability}]"
        if question:
            previews.append(question)
    return previews


def _escape_markdown_table_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _summary_text(report: dict[str, Any]) -> str:
    lines = [
        f"agent_random_conversation_eval: {'PASS' if report['passed'] else 'FAIL'}",
        f"seed={report['seed']} scenarios={report['scenario_count']} conversations={report.get('conversation_count', report['scenario_count'])} pass_rate={report['pass_rate']:.2%}",
    ]
    gate_result = report.get("gate_result") if isinstance(report.get("gate_result"), dict) else {}
    if gate_result:
        lines.append(
            "gate: "
            f"passed={gate_result.get('gate_passed')} "
            f"semantic_pass_rate={gate_result.get('semantic_pass_rate')} "
            f"oracle_pass_rate={gate_result.get('oracle_pass_rate')} "
            f"legacy_unverified_rate={gate_result.get('legacy_unverified_rate')}"
        )
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    if coverage:
        lines.append(
            "coverage: "
            f"scenario_families={','.join(coverage.get('scenario_families') or []) or '-'} "
            f"families={','.join(coverage.get('capability_families') or []) or '-'} "
            f"operations={','.join(coverage.get('operations') or []) or '-'} "
            f"continuation_turns={coverage.get('post_initial_turns', coverage.get('requested_followup_turns', 0))} "
            f"contextualized_turns={coverage.get('contextualized_post_initial_turns', coverage.get('followup_turns', 0))} "
            f"missing_context_turns={coverage.get('missing_post_initial_context_turns', coverage.get('missing_followup_context_turns', 0))} "
            f"actions={coverage.get('structured_action_turns', 0)} "
            f"structured_answers={coverage.get('structured_answer_turns', 0)}"
        )
    thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), dict) else {}
    if thresholds:
        lines.append(
            "thresholds: "
            f"min_pass_rate={thresholds.get('min_pass_rate')} "
            f"min_conversations={thresholds.get('min_conversations')} "
            f"min_families={thresholds.get('min_capability_families')} "
            f"min_followups={thresholds.get('min_followup_turns')} "
            f"min_actions={thresholds.get('min_structured_action_turns')} "
            f"min_structured_answers={thresholds.get('min_structured_answer_turns')}"
        )
    for issue in report.get("global_issues") or []:
        lines.append(f"- global: {issue}")
    for result in report["results"]:
        suffix = f"#{result.get('run_index')}" if result.get("run_index") else ""
        lines.append(f"- {result['scenario_id']}{suffix}: {'PASS' if result['passed'] else 'FAIL'}")
        for issue in result["issues"]:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
