"""Rule checker for verified final responses."""

from __future__ import annotations

from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import ComparisonResult, VerificationResult
from data_agent_core.core.analysis_planner import complete_generalization_contract
from data_agent_core.core.capability_registry import capability_for_operation


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
        complete_generalization_contract(plan.logic_form)
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
    contract_passed, contract_notes, contract_action = _verify_generalization_contract(plan, user_question, primary)
    notes.extend(contract_notes)
    if not contract_passed:
        return False, notes, contract_action
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


def _verify_generalization_contract(
    plan: AnalysisPlan,
    user_question: UserQuestion,
    primary: ExecutionResult,
) -> tuple[bool, list[str], dict[str, object] | None]:
    logic = plan.logic_form
    question = user_question.question.lower()
    notes: list[str] = []
    capability = capability_for_operation(logic.operation)
    notes.append(f"Capability family: {capability.capability_family}.")
    missing = [
        field_name
        for field_name in ("entity_grain", "time_window", "candidate_set", "output_contract")
        if not getattr(logic, field_name)
    ]
    if missing:
        notes.append("Planner generalization contract is incomplete: " + ", ".join(missing))
        return False, notes, {"action": "complete_planner_contract", "missing_fields": missing}
    if logic.operation != "distinct_count" and _asks_per_unique_entity(question) and not _has_unique_entity_denominator(logic.denominator, logic.entity_grain):
        notes.append("Question asks for a per-unique-entity denominator, but the plan does not define a unique entity denominator.")
        return False, notes, {"action": "repair_denominator", "required": "unique_entity"}
    if _asks_candidate_selection(question) and _candidate_set_missing(logic.candidate_set):
        notes.append("Question asks for candidate selection, but the plan does not define a candidate set.")
        return False, notes, {"action": "complete_candidate_set"}
    if _asks_explicit_filter(user_question.question) and not logic.filters and not _has_structured_filter_context(logic):
        notes.append("Question includes an explicit filter expression, but the plan has no filters.")
        return False, notes, {"action": "repair_filters", "reason": "explicit_filter_missing"}
    if _asks_grouped_count(question) and logic.operation == "row_count":
        notes.append("Question asks for grouped counts, but the plan returns only a scalar row count.")
        return False, notes, {"action": "replace_operation", "to_operation": "aggregation", "aggregation": "count"}
    if _asks_count_metric(question) and not _count_metric_request_satisfied(logic, question):
        notes.append("Question asks for a count metric, but the plan uses a non-count metric definition.")
        return False, notes, {"action": "repair_metric_definition", "required_aggregation": "count"}
    if _asks_mode_or_most_common(question) and logic.operation != "top_count" and not _business_top_count_operation(logic):
        notes.append("Question asks for the most common value or mode, but the plan is not top_count.")
        return False, notes, {"action": "replace_operation", "to_operation": "top_count"}
    share_passed, share_action = _verify_share_contract(question, logic.denominator, logic.parameters)
    if not share_passed:
        notes.append("Top-K share denominator does not match the requested count-vs-metric semantics.")
        return False, notes, share_action
    output_passed, output_note = _verify_output_contract(logic.output_contract, primary.value)
    notes.append(output_note)
    if not output_passed:
        return False, notes, {"action": "repair_output_contract", "expected": logic.output_contract}
    return True, notes, None


def _asks_per_unique_entity(question: str) -> bool:
    return any(token in question for token in ("per unique", "unique shopper", "unique email", "每个唯一", "去重", "唯一"))


def _has_unique_entity_denominator(denominator: dict[str, Any], entity_grain: dict[str, Any]) -> bool:
    return denominator.get("role") == "unique_entity" or denominator.get("aggregation") in {"nunique", "distinct_count"}


def _asks_candidate_selection(question: str) -> bool:
    return any(token in question for token in ("which", "choose", "choice", "top", "highest", "lowest", "排名", "最多", "最高", "最低"))


def _candidate_set_missing(candidate_set: dict[str, Any]) -> bool:
    return not candidate_set or candidate_set.get("source") in {None, ""}


def _asks_explicit_filter(question: str) -> bool:
    for match in re_finditer(
        r"[\u4e00-\u9fffA-Za-z0-9_]{1,20}\s*(?:=|为)\s*[\u4e00-\u9fffA-Za-z0-9_.-]{1,30}",
        question,
    ):
        expression_tail = question[match.start() : match.start() + 80]
        if _looks_like_metric_formula(expression_tail):
            continue
        return True
    return False


def _looks_like_metric_formula(text: str) -> bool:
    segment = text.split("。", 1)[0].split(".", 1)[0].split("?", 1)[0].split("？", 1)[0]
    return "=" in segment and any(operator in segment for operator in ("/", "+", "*"))


def _has_structured_filter_context(logic: Any) -> bool:
    params = getattr(logic, "parameters", {}) or {}
    time_window = getattr(logic, "time_window", {}) or {}
    if isinstance(time_window, dict) and time_window.get("values"):
        return True
    filter_like_keys = {
        "account_type",
        "aci",
        "card_scheme",
        "credit",
        "date",
        "day_of_year",
        "display_item",
        "feature",
        "fiscal_year",
        "merchant",
        "month",
        "month_range",
        "person",
        "product",
        "role",
        "status",
        "year",
        "ym",
    }
    return any(key in params and params.get(key) not in {None, "", []} for key in filter_like_keys)


def _asks_grouped_count(question: str) -> bool:
    return _asks_count_metric(question) and any(token in question for token in (" by ", "group", "per ", "each", "按", "各", "每"))


def _asks_count_metric(question: str) -> bool:
    return bool(
        re_search(
            r"\b(row count|record count|transaction count|number of rows|number of records|number of transactions|how many rows|how many records|how many transactions)\b",
            question,
        )
    ) or any(
        token in question for token in ("数量", "记录数", "条数", "笔数", "次数", "个数", "行数")
    )


def _count_metric_request_satisfied(logic: Any, question: str) -> bool:
    if _metric_aggregation(logic) in {"count", "distinct_count", "nunique"}:
        return True
    if logic.operation in {"row_count", "top_count", "distinct_count"}:
        return True
    if _counts_entities_after_metric_comparison(logic.operation):
        return True
    return _business_quantity_metric_satisfies_count_question(logic, question)


def _counts_entities_after_metric_comparison(operation: str) -> bool:
    return operation in {
        "vds_period_growth_count_share",
    }


def _business_quantity_metric_satisfies_count_question(logic: Any, question: str) -> bool:
    operation = str(getattr(logic, "operation", "") or "")
    params = getattr(logic, "parameters", {}) or {}
    metric = str(getattr(logic, "metric", "") or params.get("metric") or "")
    metric_text = f"{operation} {metric}".lower()
    if not operation.startswith("retail_"):
        return False
    if any(token in question for token in ("记录数", "条数", "行数", "次数", "个数", "合格数")):
        return _business_top_count_operation(logic) or any(token in metric_text for token in ("count", "cnt", "num", "record"))
    if "数量" in question:
        return any(
            token in metric_text
            for token in ("quantity", "qty", "count", "cnt", "num", "sku", "box", "数量")
        ) or _business_top_count_operation(logic)
    return False


def _business_top_count_operation(logic: Any) -> bool:
    operation = str(getattr(logic, "operation", "") or "")
    if not operation.startswith("retail_"):
        return False
    return any(token in operation for token in ("_top", "_count", "_record", "_ranking"))


def _asks_mode_or_most_common(question: str) -> bool:
    return any(token in question for token in ("most common", "most frequent", "mode", "出现次数最多", "出现最多", "最常见", "最频繁", "频次最高", "频率最高", "众数"))


def _metric_aggregation(logic: Any) -> str:
    definition = getattr(logic, "metric_definition", {}) or {}
    params = getattr(logic, "parameters", {}) or {}
    return str(definition.get("aggregation") or params.get("aggregation") or "")


def _verify_share_contract(question: str, denominator: dict[str, Any], params: dict[str, Any]) -> tuple[bool, dict[str, object] | None]:
    if not any(token in question for token in ("share", "percentage", "proportion", "占比", "比例", "百分比")):
        return True, None
    if not any(token in question for token in ("top", "前")):
        return True, None
    denominator_aggregation = str(denominator.get("aggregation") or params.get("aggregation") or "")
    if _asks_count_metric(question):
        return (
            denominator_aggregation == "count",
            {"action": "repair_denominator", "required_aggregation": "count", "scope": "filtered_total"},
        )
    if params.get("metric") and denominator_aggregation == "count":
        return (
            False,
            {
                "action": "repair_denominator",
                "required_aggregation": params.get("aggregation") or "sum",
                "field": params.get("metric"),
                "scope": "filtered_total",
            },
        )
    return True, None


def re_search(pattern: str, text: str) -> Any:
    import re

    return re.search(pattern, text, re.I)


def re_finditer(pattern: str, text: str) -> Any:
    import re

    return re.finditer(pattern, text, re.I)


def _verify_output_contract(output_contract: dict[str, Any], value: Any) -> tuple[bool, str]:
    answer_type = str(output_contract.get("answer_type") or output_contract.get("expected_result_shape") or "scalar")
    if value == "Not Applicable":
        return True, "Output contract allows Not Applicable boundary handling."
    if answer_type in {"number", "percentage"} and isinstance(value, list):
        return False, f"Output contract expected {answer_type}, but execution returned rows."
    if answer_type in {"table", "list"} and value is None:
        return False, f"Output contract expected {answer_type}, but execution returned no value."
    return True, f"Output contract checked as {answer_type}."
