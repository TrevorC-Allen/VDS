"""Rule checker for verified final responses."""

from __future__ import annotations

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import ComparisonResult, VerificationResult


def verify_execution(
    primary: ExecutionResult,
    comparison: ComparisonResult | None = None,
    *,
    plan: AnalysisPlan | None = None,
    user_question: UserQuestion | None = None,
) -> VerificationResult:
    """Verify that the primary path succeeded and optional comparison agrees."""

    issues: list[str] = []
    semantic_notes: list[str] = []
    correction_action: dict[str, object] | None = None
    if not primary.success:
        issues.append("Primary execution path failed.")
    if primary.value is None:
        issues.append("Primary execution returned no value.")
    if comparison is not None and not comparison.consistent:
        issues.extend(comparison.issues)
    semantic_passed = True
    if plan is not None and user_question is not None:
        semantic_passed, semantic_notes, correction_action = _verify_semantic_contract(plan, user_question, primary)
        if not semantic_passed:
            issues.append("Semantic metric definition does not match the user question.")
    passed = not issues
    return VerificationResult(
        passed=passed,
        confidence=0.9 if passed else 0.0,
        pandas_sql_consistent=None if comparison is None else comparison.consistent,
        semantic_passed=semantic_passed,
        issues=issues,
        notes=["Verifier checked execution success, optional backend consistency, and semantic metric contract."],
        semantic_verification_notes=semantic_notes,
        correction_action=correction_action,
    )


def _verify_semantic_contract(
    plan: AnalysisPlan,
    user_question: UserQuestion,
    primary: ExecutionResult,
) -> tuple[bool, list[str], dict[str, object] | None]:
    logic = plan.logic_form
    question = user_question.question.lower()
    notes: list[str] = []
    correction_action: dict[str, object] | None = None
    is_fraud_ranking = (
        logic.task_type == "ranking"
        and "fraud" in question
        and any(token in question for token in ("top", "highest", "lowest", "rank"))
    )
    if is_fraud_ranking:
        metric_name = logic.metric or logic.parameters.get("metric")
        if metric_name in {"fraud_volume_rate", "fraud_transaction_rate"} and logic.numerator and logic.denominator:
            notes.append(f"Fraud ranking uses semantic metric {metric_name}.")
        else:
            notes.append("Fraud ranking requires a rate metric derived from manual-defined fraud volume over total volume.")
            correction_action = {
                "action": "replace_logic_form",
                "from_operation": logic.operation,
                "to_operation": "rank_by_metric",
                "metric": "fraud_volume_rate",
                "reason": "Manual defines fraud as fraudulent volume divided by total volume.",
            }
            return False, notes, correction_action
    if isinstance(primary.value, dict) and primary.value.get("candidate_table"):
        notes.append("Execution returned a candidate table for verifier inspection.")
        if logic.options and primary.value.get("selected") not in {str(value) for value in logic.options.values()}:
            notes.append("Selected value is not one of the provided multiple-choice candidates.")
            return False, notes, {"action": "reselect_from_candidate_table", "reason": "Selected value must come from options."}
    if logic.metric_definition:
        notes.append("LogicForm includes a metric_definition for audit.")
    return True, notes, correction_action
