"""Final response builder for stable analyze responses."""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec, FinalResponse, InsightResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import CAPABILITY_GAP, OUTPUT_CONTRACT_VALIDATION_FAILED
from data_agent_core.output.output_contract import canonicalize_final_answer


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

    canonical_answer = canonicalize_final_answer(execution_result.value, plan.logic_form.output_format)
    answer = canonical_answer.answer
    not_applicable_attribution = classify_not_applicable(execution_result.value, plan)
    success = (
        execution_result.success
        and verification.passed
        and canonical_answer.validation.passed
        and not_applicable_attribution.get("category") != "capability_gap"
    )
    warnings = list(execution_result.warnings)
    errors = list(execution_result.errors)
    debug_payload = dict(debug or {})
    debug_payload["output_contract_validation"] = canonical_answer.validation.to_dict()
    debug_payload["canonical_answer"] = {
        "normalized_from": canonical_answer.normalized_from,
        "answer_type": canonical_answer.validation.answer_type,
    }
    debug_payload["validation_driven_retry"] = {
        "output_contract_retryable": canonical_answer.validation.retryable,
        "output_contract_action": "none" if canonical_answer.validation.passed else "controlled_failure",
        "output_contract_issues": list(canonical_answer.validation.issues),
    }
    if not canonical_answer.validation.passed:
        message = "Final answer failed output contract validation: " + ", ".join(canonical_answer.validation.issues)
        warnings.append(message)
        errors.append(
            ErrorResult(
                error_type=OUTPUT_CONTRACT_VALIDATION_FAILED,
                error_message=message,
                failed_step=plan.logic_form.operation,
                recoverable=canonical_answer.validation.retryable,
                suggested_fix="Trigger controlled retry or return a contract-safe final answer string.",
            ).to_dict()
        )
    if not_applicable_attribution.get("category") == "capability_gap":
        warnings.append(str(not_applicable_attribution["message"]))
        errors.append(
            ErrorResult(
                error_type=CAPABILITY_GAP,
                error_message=str(not_applicable_attribution["message"]),
                failed_step=plan.logic_form.operation,
                recoverable=True,
                suggested_fix="Add or route to a reusable capability family instead of returning plain Not Applicable.",
            ).to_dict()
        )
    if not_applicable_attribution.get("category"):
        debug_payload["not_applicable_attribution"] = not_applicable_attribution
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
        debug=debug_payload,
    )


def format_answer(value: Any, output_format: dict[str, Any]) -> str:
    """Format a raw execution value according to benchmark/API guidelines."""

    return canonicalize_final_answer(value, output_format).answer


def classify_not_applicable(value: Any, plan: AnalysisPlan) -> dict[str, Any]:
    """Classify Not Applicable as true unsupported or a capability gap."""

    if value != "Not Applicable":
        return {"category": None, "message": ""}
    logic = plan.logic_form
    reason = str(logic.parameters.get("reason") or "")
    configured = str(logic.output_format.get("not_applicable_type") or logic.parameters.get("not_applicable_type") or "")
    if configured:
        category = configured
    elif logic.operation == "not_applicable" and _looks_true_unsupported(reason):
        category = "true_unsupported"
    else:
        category = "capability_gap"
    if category == "true_unsupported":
        message = reason or "The uploaded schema or rules do not define the requested business concept."
    else:
        message = reason or f"Operation {logic.operation} returned Not Applicable without a true unsupported reason."
    return {
        "category": category,
        "reason": reason,
        "operation": logic.operation,
        "message": message,
    }


def _looks_true_unsupported(reason: str) -> bool:
    lowered = reason.lower()
    return any(
        token in lowered
        for token in (
            "do not define",
            "does not define",
            "not define",
            "undefined",
            "no uploaded rule",
            "没有定义",
            "未定义",
            "无定义",
        )
    )


def _format_number(value: float, decimals: int | None = None) -> str:
    if decimals is None:
        if math.isclose(value, round(value)):
            return str(int(round(value)))
        return str(value)
    return _format_decimal(value, decimals)


def _format_percentage(value: float, decimals: int | None = None) -> str:
    places = 2 if decimals is None else decimals
    return f"{_format_decimal(value, places)}%"


def _format_decimal(value: float, places: int) -> str:
    quantum = Decimal("1").scaleb(-places)
    return str(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


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
