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
    "top_count",
    "group_average",
    "average_fee_for_filters",
    "fee_ids_for_filters",
    "applicable_fee_ids",
    "total_fees",
    "fee_rate_delta",
    "card_scheme_steering",
    "fee_restriction_affected_merchants",
    "mcc_change_delta",
    "best_fraud_aci_choice",
    "not_applicable",
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
            ),
        },
    ]
    raw = llm_client.complete_json(messages, temperature=0.0)
    return LLMStageResult(
        stage_name=stage_name,
        raw=_safe_stage_raw(raw),
        confidence=float(raw.get("confidence") or 0.0),
        reasoning_summary=str(raw.get("reasoning_summary") or raw.get("summary") or ""),
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
                        "filters": "object",
                        "parameters": "object",
                        "output_format": "object",
                        "confidence": "number between 0 and 1",
                        "reasoning_summary": "short summary, not chain of thought",
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = llm_client.complete_json(messages, temperature=0.0)
    logic_form = _logic_form_from_raw(raw)
    return LLMPlanResult(
        logic_form=logic_form,
        raw=_safe_raw(raw),
        confidence=float(raw.get("confidence") or 0.0),
        reasoning_summary=str(raw.get("reasoning_summary") or ""),
    )


def _logic_form_from_raw(raw: dict[str, Any]) -> LogicForm:
    operation = str(raw.get("operation") or "not_applicable")
    if operation not in SUPPORTED_OPERATIONS:
        operation = "not_applicable"
    return make_logic_form(
        task_type=str(raw.get("task_type") or "unknown"),
        operation=operation,
        filters=_dict_or_empty(raw.get("filters")),
        parameters=_dict_or_empty(raw.get("parameters")),
        output_format=_dict_or_empty(raw.get("output_format")),
    )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_raw(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {"task_type", "operation", "filters", "parameters", "output_format", "confidence", "reasoning_summary"}
    return {key: raw.get(key) for key in allowed if key in raw}


def _safe_stage_raw(value: Any) -> Any:
    blocked = {"chain_of_thought", "cot", "hidden_reasoning", "full_reasoning"}
    if isinstance(value, dict):
        return {key: _safe_stage_raw(item) for key, item in value.items() if key not in blocked}
    if isinstance(value, list):
        return [_safe_stage_raw(item) for item in value]
    return value
