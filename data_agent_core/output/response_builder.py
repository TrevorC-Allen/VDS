"""Final response builder for stable analyze responses."""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec, FinalResponse, InsightResult
from data_agent_core.contracts.verification_contracts import VerificationResult


def build_response(
    *,
    run_id: str,
    user_question: UserQuestion,
    plan: AnalysisPlan,
    execution_result: ExecutionResult,
    verification: VerificationResult,
    debug: dict[str, Any] | None = None,
) -> FinalResponse:
    """Build a FinalResponse with stable fields and formatted answer."""

    answer = format_answer(execution_result.value, plan.logic_form.output_format)
    success = execution_result.success and verification.passed
    warnings = list(execution_result.warnings)
    errors = list(execution_result.errors)
    return FinalResponse(
        response_version="v1",
        success=success,
        run_id=run_id,
        dataset_id=user_question.dataset_id,
        question=user_question.question,
        answer_type=str(plan.logic_form.output_format.get("answer_type", "text")),
        execution_mode=user_question.execution_mode,
        answer=answer,
        logic_form=_to_dict(plan.logic_form),
        result={"columns": execution_result.columns, "rows": execution_result.rows, "value": execution_result.value},
        verification=_to_dict(verification),
        insight=InsightResult(summary=answer if success else ""),
        chart=ChartSpec(),
        warnings=warnings,
        errors=errors,
        debug=debug or {},
    )


def format_answer(value: Any, output_format: dict[str, Any]) -> str:
    """Format a raw execution value according to benchmark/API guidelines."""

    answer_type = output_format.get("answer_type")
    decimals = output_format.get("decimals")
    if value is None:
        return "Not Applicable"
    if value == "Not Applicable":
        return "Not Applicable"
    if isinstance(value, dict) and "answer" in value:
        return str(value["answer"])
    if answer_type == "number":
        return _format_number(float(value), decimals)
    if answer_type == "list":
        return ", ".join(str(item) for item in value)
    if answer_type == "scheme_fee":
        return f"{value['card_scheme']}:{_format_number(float(value['fee']), decimals)}"
    if answer_type == "card_scheme" and isinstance(value, dict):
        return str(value["card_scheme"])
    if answer_type == "grouped_amounts":
        return _format_grouped_amounts(value, decimals)
    return str(value)


def _format_number(value: float, decimals: int | None = None) -> str:
    if decimals is None:
        if math.isclose(value, round(value)):
            return str(int(round(value)))
        return str(value)
    return f"{value:.{decimals}f}"


def _format_grouped_amounts(rows: list[dict[str, Any]], decimals: int | None) -> str:
    if not rows:
        return "Not Applicable"
    group_key = next(key for key in rows[0] if key != "eur_amount")
    parts = [f"{row[group_key]}: {_format_number(float(row['eur_amount']), decimals)}" for row in rows]
    return "[" + ", ".join(parts) + "]"


def _to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value
