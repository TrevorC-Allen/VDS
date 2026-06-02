"""LLM stage helpers for the single-agent data analysis chain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_agent_core.contracts.analysis_contracts import LogicForm
from data_agent_core.core.logic_form import make_logic_form
from data_agent_core.llm.client import LLMClient


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "data_agent_system_prompt.md"


SUPPORTED_OPERATIONS = {
    "aggregation",
    "row_count",
    "distinct_count",
    "metric_per_distinct_entity",
    "repeat_entity_percentage",
    "repeat_entity_count",
    "schema_field_lookup",
    "null_check",
    "missing_columns_choice",
    "outlier_count",
    "top_k_share",
    "filtered_metric_ranking",
    "growth_ranking",
    "top_count",
    "ranking",
    "filtering",
    "detail_lookup",
    "trend",
    "comparison",
    "group_average",
    "average_fee_for_filters",
    "fee_ids_for_filters",
    "applicable_fee_ids",
    "total_fees",
    "fee_rate_delta",
    "card_scheme_steering",
    "cheapest_card_scheme_for_transaction",
    "fee_restriction_affected_merchants",
    "fraud_rate_comparison",
    "fraud_rate_filtered",
    "mcc_change_delta",
    "best_fraud_aci_choice",
    "aci_fee_extreme",
    "fee_extreme_by_dimension",
    "field_values",
    "boolean_percentage",
    "boolean_count_ratio",
    "duplicate_check",
    "data_quality_report",
    "not_applicable",
    "vds_period_rank_change",
    "vds_period_delta_top",
    "vds_period_growth_count_share",
    "vds_period_threshold_count",
    "vds_period_rate_top",
    "vds_current_threshold_top",
    "vds_current_category_share_top",
    "vds_peer_anomaly",
}


@dataclass
class LLMPlanResult:
    """LLM planning result plus metadata safe for traces."""

    logic_form: LogicForm
    raw: dict[str, Any]
    confidence: float
    reasoning_summary: str


@dataclass
class LLMStageResult:
    """Safe LLM stage summary for traces and debug output."""

    stage_name: str
    raw: dict[str, Any]
    confidence: float
    reasoning_summary: str


def complete_stage_with_llm(
    *,
    llm_client: LLMClient,
    stage_name: str,
    stage_goal: str,
    question: str,
    guidelines: str,
    context_summary: dict[str, Any],
    payload: dict[str, Any],
    required_output: dict[str, Any],
    temperature: float = 0.0,
) -> LLMStageResult:
    """Run one named LLM stage and return a trace-safe summary."""

    messages = [
        {"role": "system", "content": PROMPT_PATH.read_text()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "stage_name": stage_name,
                    "stage_goal": stage_goal,
                    "question": question,
                    "guidelines": guidelines,
                    "context_summary": context_summary,
                    "payload": payload,
                    "required_output": required_output,
                    "constraints": {
                        "do_not_calculate_final_answer": True,
                        "do_not_use_benchmark_task_id": True,
                        "do_not_use_benchmark_answer": True,
                        "no_full_chain_of_thought": True,
                    },
                },
                ensure_ascii=False,
                default=_json_default,
            ),
        },
    ]
    raw = llm_client.complete_json(messages, temperature=temperature)
    return LLMStageResult(
        stage_name=stage_name,
        raw=_safe_stage_raw(raw),
        confidence=float(raw.get("confidence") or 0.0),
        reasoning_summary=str(_safe_stage_raw(raw.get("reasoning_summary") or raw.get("summary") or "")),
    )


def plan_with_llm(
    *,
    llm_client: LLMClient,
    question: str,
    guidelines: str,
    context_summary: dict[str, Any],
) -> LLMPlanResult:
    """Ask the LLM for a structured plan draft."""

    messages = [
        {"role": "system", "content": PROMPT_PATH.read_text()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "stage_name": "analysis_planner",
                    "question": question,
                    "guidelines": guidelines,
                    "context_summary": context_summary,
                    "supported_operations": sorted(SUPPORTED_OPERATIONS),
                    "required_output": {
                        "task_type": "string",
                        "operation": "one supported operation",
                        "metric_definition": "object with metric name, aggregation, and business definition",
                        "numerator": "object for numerator definition when relevant",
                        "denominator": "object for denominator definition when relevant",
                        "entity_grain": "object with entity field and grain role",
                        "time_window": "object with temporal scope",
                        "candidate_set": "object with option or data-derived candidate scope",
                        "filters": "object",
                        "parameters": "object",
                        "output_contract": "object with answer_type and expected result shape",
                        "output_format": "object",
                        "confidence": "number between 0 and 1",
                        "reasoning_summary": "short summary, not chain of thought",
                    },
                },
                ensure_ascii=False,
                default=_json_default,
            ),
        },
    ]
    raw = llm_client.complete_json(messages, temperature=0.0)
    logic_form = _logic_form_from_raw(raw)
    return LLMPlanResult(
        logic_form=logic_form,
        raw=_safe_raw(raw),
        confidence=float(raw.get("confidence") or 0.0),
        reasoning_summary=str(_safe_stage_raw(raw.get("reasoning_summary") or "")),
    )


def _logic_form_from_raw(raw: dict[str, Any]) -> LogicForm:
    operation = str(raw.get("operation") or "not_applicable")
    if operation not in SUPPORTED_OPERATIONS:
        operation = "not_applicable"
    return make_logic_form(
        task_type=str(raw.get("task_type") or "unknown"),
        operation=operation,
        metric=raw.get("metric"),
        metric_definition=_dict_or_empty(raw.get("metric_definition")),
        numerator=_dict_or_empty(raw.get("numerator")),
        denominator=_dict_or_empty(raw.get("denominator")),
        entity_grain=_dict_or_empty(raw.get("entity_grain")),
        time_window=_dict_or_empty(raw.get("time_window")),
        candidate_set=_dict_or_empty(raw.get("candidate_set")),
        group_by=raw.get("group_by"),
        objective=raw.get("objective"),
        options=_dict_or_empty(raw.get("options")),
        filters=_dict_or_empty(raw.get("filters")),
        parameters=_dict_or_empty(raw.get("parameters")),
        output_format=_dict_or_empty(raw.get("output_format")),
        output_contract=_dict_or_empty(raw.get("output_contract")),
    )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_raw(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "task_type",
        "operation",
        "metric",
        "metric_definition",
        "numerator",
        "denominator",
        "entity_grain",
        "time_window",
        "candidate_set",
        "group_by",
        "objective",
        "options",
        "filters",
        "parameters",
        "output_contract",
        "output_format",
        "confidence",
        "reasoning_summary",
        "display_summary",
        "decision_points",
        "assumptions",
        "caveats",
    }
    return {key: _safe_stage_raw(raw.get(key)) for key in allowed if key in raw}


def _safe_stage_raw(value: Any) -> Any:
    blocked = {
        "accepted" + "_answer",
        "accepted" + "_answers",
        "api_key",
        "chain_of_thought",
        "cot",
        "full_reasoning",
        "hidden" + "_answer",
        "hidden_reasoning",
        "public" + "_proxy",
        "raw_prompt",
        "raw_reasoning",
        "reasoning_tokens",
        "scorer",
        "standard" + "_answer",
        "task" + "_id",
    }
    if isinstance(value, dict):
        return {key: _safe_stage_raw(item) for key, item in value.items() if str(key).lower() not in blocked}
    if isinstance(value, list):
        return [_safe_stage_raw(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, str):
        return _redact_stage_text(value)
    return value


def _redact_stage_text(value: str) -> str:
    text = str(value)
    for marker in (
        "accepted-" + "answer",
        "accepted " + "answer",
        "accepted" + "_answer",
        "api key",
        "api_key",
        "chain of thought",
        "chain_of_thought",
        "full reasoning",
        "full_reasoning",
        "hidden " + "answer",
        "hidden" + "_answer",
        "hidden benchmark",
        "hidden_reasoning",
        "public " + "proxy",
        "public" + "_proxy",
        "raw prompt",
        "raw reasoning",
        "raw_prompt",
        "raw_reasoning",
        "reasoning tokens",
        "reasoning_tokens",
        "scorer",
        "standard " + "answer",
        "standard" + "_answer",
        "task_id",
    ):
        text = _replace_case_insensitive(text, marker, "[redacted]")
    return text


def _replace_case_insensitive(text: str, needle: str, replacement: str) -> str:
    start = 0
    result = ""
    lowered = text.lower()
    needle_lower = needle.lower()
    while True:
        index = lowered.find(needle_lower, start)
        if index < 0:
            return result + text[start:]
        result += text[start:index] + replacement
        start = index + len(needle)


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)
