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
    fee_table_passed, fee_table_notes, fee_table_action = _verify_fee_candidate_table(logic, primary.value)
    notes.extend(fee_table_notes)
    if not fee_table_passed:
        return False, notes, fee_table_action
    if logic.metric_definition:
        notes.append("LogicForm includes a metric_definition for audit.")
    return True, notes, correction_action


def _verify_fee_candidate_table(logic: Any, value: Any) -> tuple[bool, list[str], dict[str, object] | None]:
    operations = {
        "card_scheme_steering",
        "cheapest_card_scheme_for_transaction",
        "best_fraud_aci_choice",
        "aci_fee_extreme",
        "fee_extreme_by_dimension",
    }
    if getattr(logic, "operation", None) not in operations:
        return True, [], None
    if not isinstance(value, dict):
        return False, ["Fee candidate selection returned a non-structured result."], {
            "action": "repair_fee_candidate_table",
            "reason": "structured_result_required",
        }
    table = value.get("candidate_table")
    if not isinstance(table, list) or not table or not all(isinstance(row, dict) for row in table):
        return False, ["Fee candidate selection did not return a complete candidate table."], {
            "action": "repair_fee_candidate_table",
            "reason": "candidate_table_required",
        }
    missing_fee_rows = [row for row in table if not _numeric_like(row.get("fee"))]
    if missing_fee_rows:
        return False, ["Fee candidate table contains rows without numeric fee values."], {
            "action": "repair_fee_candidate_table",
            "reason": "numeric_fee_required",
        }

    selected_values = _selected_fee_values(value)
    if selected_values:
        labels = _candidate_table_labels(table, value, logic)
        if not labels:
            return False, ["Fee candidate table does not expose a candidate dimension."], {
                "action": "repair_fee_candidate_table",
                "reason": "candidate_dimension_required",
            }
        missing = [item for item in selected_values if item not in labels]
        if missing:
            return False, ["Selected fee candidate is absent from the candidate table."], {
                "action": "reselect_from_candidate_table",
                "reason": "selected_candidate_absent",
            }
    notes = [f"Fee candidate table verified with {len(table)} candidates."]
    return True, notes, None


def _numeric_like(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _selected_fee_values(value: dict[str, Any]) -> list[str]:
    selected = value.get("selected")
    if _empty_selection(selected):
        selected = value.get("answer")
    if _empty_selection(selected):
        selected = value.get("aci") or value.get("card_scheme")
    if isinstance(selected, (list, tuple, set)):
        return [str(item) for item in selected if item not in {None, ""}]
    return [] if _empty_selection(selected) else [str(selected)]


def _empty_selection(value: Any) -> bool:
    return value is None or value == ""


def _candidate_table_labels(table: list[dict[str, Any]], value: dict[str, Any], logic: Any) -> set[str]:
    dimension = str(value.get("dimension") or getattr(logic, "group_by", None) or "")
    fields = [
        field
        for field in (
            dimension,
            "aci",
            "card_scheme",
            "merchant_category_code",
            "mcc",
            "candidate",
            "answer",
        )
        if field
    ]
    labels: set[str] = set()
    for row in table:
        for field in fields:
            if field in row and row[field] not in {None, ""}:
                labels.add(str(row[field]))
    return labels


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
    if _asks_grouped_metric_visual(question) and logic.operation in {"detail_lookup", "row_count"}:
        notes.append("Question asks for grouped metric output or a chart, but the plan returns detail rows or a scalar count.")
        return False, notes, {"action": "replace_operation", "to_operation": "aggregation", "reason": "grouped_metric_chart_required"}
    if _asks_multi_entity_comparison(question) and logic.filters and not _filter_scope_preserves_multi_entity(question, logic.filters):
        notes.append("Question compares multiple named entities, but the plan collapsed scope into an implicit single-entity filter.")
        return False, notes, {"action": "repair_filters", "reason": "multi_entity_scope_collapsed"}
    semantic_binding_passed, semantic_binding_notes, semantic_binding_action = _verify_requested_metric_dimension_binding(logic, question, primary)
    notes.extend(semantic_binding_notes)
    if not semantic_binding_passed:
        return False, notes, semantic_binding_action
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
    join_passed, join_notes, join_action = _verify_join_contract(logic, question, primary)
    notes.extend(join_notes)
    if not join_passed:
        return False, notes, join_action
    shape_passed, shape_notes, shape_action = _verify_requested_shape_contract(logic, question, primary)
    notes.extend(shape_notes)
    if not shape_passed:
        return False, notes, shape_action
    output_passed, output_note = _verify_output_contract(logic.output_contract, primary.value)
    notes.append(output_note)
    if not output_passed:
        return False, notes, {"action": "repair_output_contract", "expected": logic.output_contract}
    return True, notes, None


DIMENSION_CONCEPT_ALIASES = {
    "product": ("product", "sku", "item", "产品", "商品", "品名"),
    "category": ("category", "ctg", "类别", "品类", "类目"),
    "store": ("store", "shop", "branch", "门店", "店铺"),
    "city": ("city", "城市", "市"),
    "channel": ("channel", "渠道", "通路"),
    "customer": ("customer", "cust", "client", "客户", "终端"),
    "month": ("month", "stat_month", "ym", "年月", "月份"),
    "time": ("date", "day", "week", "period", "日期", "时间", "周期"),
}

METRIC_CONCEPT_ALIASES = {
    "sales": ("sales", "sale", "revenue", "amount", "销售额", "销售金额", "销售", "收入", "金额", "订单金额"),
    "profit": ("profit", "gross_profit", "grossprofit", "利润", "毛利"),
}


def _verify_requested_metric_dimension_binding(
    logic: Any,
    question: str,
    primary: ExecutionResult,
) -> tuple[bool, list[str], dict[str, object] | None]:
    params = getattr(logic, "parameters", {}) or {}
    notes: list[str] = []
    dimension_fields = _semantic_dimension_fields(logic)
    requested_dimensions = _requested_dimension_concepts(question)
    schema_backed_semantics = _uses_schema_backed_semantic_binding(logic)
    if requested_dimensions and schema_backed_semantics:
        notes.append("Schema-backed business operation handles dimension semantic binding internally.")
    elif requested_dimensions and not dimension_fields:
        params = getattr(logic, "parameters", {}) or {}
        if not params.get("strict_missing_dimension_guard"):
            notes.append(
                f"Question mentions dimension {requested_dimensions}, but strict missing-dimension guard is disabled for this complex plan."
            )
            return True, notes, None
        available = [str(item) for item in params.get("available_columns") or []]
        notes.append(f"Question requests dimension {requested_dimensions}, but the plan did not bind a dimension field.")
        return False, notes, {
            "action": "repair_dimension_binding",
            "requested_dimensions": requested_dimensions,
            "actual_dimension": "",
            "missing_dimension": True,
            "available_columns": available,
        }
    elif requested_dimensions and dimension_fields:
        matched_dimensions = [
            field
            for field in dimension_fields
            if any(_column_matches_concept(field, concept, DIMENSION_CONCEPT_ALIASES) for concept in requested_dimensions)
        ]
        if not matched_dimensions:
            notes.append(f"Question requests dimension {requested_dimensions}, but plan uses dimension {dimension_fields[0]}.")
            return False, notes, {
                "action": "repair_dimension_binding",
                "requested_dimensions": requested_dimensions,
                "actual_dimension": dimension_fields[0],
            }
        rows = _execution_rows(primary)
        if rows and not any(field in rows[0] for field in matched_dimensions):
            notes.append(f"Question requests dimension {matched_dimensions[0]}, but execution rows do not contain it.")
            return False, notes, {"action": "repair_result_shape", "required_column": matched_dimensions[0]}

    if _asks_profit_margin(question):
        if _logic_uses_schema_backed_profit_margin(logic):
            notes.append("Schema-backed business ratio metric verified for profit margin/rate.")
            return True, notes, None
        derived_metric = params.get("derived_metric")
        if not isinstance(derived_metric, dict) or not derived_metric:
            raw_metric = str(params.get("metric") or getattr(logic, "metric", None) or "")
            notes.append(f"Question asks for profit margin/rate, but plan uses raw metric {raw_metric or 'none'}.")
            return False, notes, {
                "action": "repair_metric_definition",
                "required_metric": "profit_margin_ratio",
                "reason": "profit_margin_requires_profit_divided_by_sales",
            }
        metric_name = str(derived_metric.get("name") or "")
        numerator = str(derived_metric.get("numerator") or "")
        denominator = str(derived_metric.get("denominator") or "")
        if not metric_name or not numerator or not denominator:
            notes.append("Derived profit margin metric is missing name, numerator, or denominator.")
            return False, notes, {"action": "repair_metric_definition", "required_metric": "profit_margin_ratio"}
        rows = _execution_rows(primary)
        if rows and metric_name not in rows[0]:
            notes.append(f"Derived metric result does not expose requested metric column: {metric_name}.")
            return False, notes, {"action": "repair_result_shape", "required_column": metric_name}
        notes.append(f"Profit margin metric verified as {numerator}/{denominator}.")
    return True, notes, None


def _semantic_dimension_fields(logic: Any) -> list[str]:
    params = getattr(logic, "parameters", {}) or {}
    operation = str(getattr(logic, "operation", "") or "")
    ordered_keys = ["dimension"]
    if operation == "vds_group_top_entities":
        ordered_keys.extend(["entity", "group_by"])
    else:
        ordered_keys.extend(["entity", "entity_field", "primary_entity_field", "group_by"])
    raw_fields = [params.get(key) for key in ordered_keys]
    raw_fields.append(getattr(logic, "group_by", None))
    entity_grain = getattr(logic, "entity_grain", {}) or {}
    if isinstance(entity_grain, dict):
        raw_fields.extend(
            [
                entity_grain.get("dimension"),
                entity_grain.get("field"),
                entity_grain.get("entity_field"),
                entity_grain.get("group_by"),
            ]
        )
    fields: list[str] = []
    for field in raw_fields:
        text = str(field or "")
        if text in {"__table__", "__row__", "__record__"}:
            continue
        if text and text not in fields:
            fields.append(text)
    return fields


def _logic_uses_schema_backed_profit_margin(logic: Any) -> bool:
    operation = str(getattr(logic, "operation", "") or "")
    capability = capability_for_operation(operation)
    if capability.capability_family != "vds_period_comparison":
        return False
    params = getattr(logic, "parameters", {}) or {}
    metric = str(params.get("metric") or getattr(logic, "metric", "") or "")
    normalized = _normalize_token(metric).upper().removesuffix("ROW")
    return normalized in {"PM", "GM"} or any(token in metric for token in ("利润率", "毛利率"))


def _uses_schema_backed_semantic_binding(logic: Any) -> bool:
    capability = capability_for_operation(str(getattr(logic, "operation", "") or ""))
    return capability.capability_family in {"vds_period_comparison", "chinese_retail_business_metric"}


def _requested_dimension_concepts(question: str) -> list[str]:
    requested: list[str] = []
    for concept, aliases in DIMENSION_CONCEPT_ALIASES.items():
        if any(_alias_in_question(question, alias) for alias in aliases):
            requested.append(concept)
    return requested


def _asks_profit_margin(question: str) -> bool:
    lowered = question.lower()
    return any(token in lowered for token in ("profit margin", "gross margin", "profit rate", "margin rate", "margin")) or any(
        token in question for token in ("利润率", "毛利率")
    )


def _column_matches_concept(column: str, concept: str, aliases_by_concept: dict[str, tuple[str, ...]]) -> bool:
    normalized_column = _normalize_token(column)
    return any(_normalize_token(alias) and _normalize_token(alias) in normalized_column for alias in aliases_by_concept.get(concept, ()))


def _alias_in_question(question: str, alias: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        return alias in question
    return bool(re_search(rf"\b{alias}\b", question))


def _normalize_token(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value).lower())


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


def _verify_join_contract(
    logic: Any,
    question: str,
    primary: ExecutionResult,
) -> tuple[bool, list[str], dict[str, object] | None]:
    params = getattr(logic, "parameters", {}) or {}
    join_plan = getattr(logic, "join_plan", None) or params.get("join_plan") or {}
    same_schema_union = params.get("same_schema_union") or {}
    source_tables = list(getattr(logic, "source_tables", None) or params.get("source_tables") or [])
    notes: list[str] = []

    if len(source_tables) > 1 and not join_plan:
        if isinstance(same_schema_union, dict) and same_schema_union:
            summary = primary.debug.get("same_schema_union_summary") if isinstance(primary.debug, dict) else None
            if not isinstance(summary, dict):
                notes.append("Same-schema multi-file plan did not report union execution scope.")
                return False, notes, {"action": "repair_executor_union_trace", "reason": "missing_same_schema_union_summary"}
            expected = {str(item) for item in source_tables}
            included = {str(item) for item in summary.get("source_tables") or []}
            if not expected.issubset(included):
                notes.append("Same-schema union did not include every planned source table.")
                return False, notes, {"action": "repair_source_scope", "reason": "same_schema_union_missing_source"}
            notes.append(f"Same-schema union verified across {len(included)} source tables.")
            return True, notes, None
        if _uses_schema_backed_internal_source_alignment(logic):
            notes.append("Schema-backed business operation handles source alignment internally.")
            return True, notes, None
        notes.append("Plan references multiple source tables but does not define a join plan.")
        return False, notes, {"action": "clarify_join_key", "reason": "multi_table_without_join_plan"}
    if not join_plan:
        if _asks_named_dimension(question) and _dimension_looks_like_id(params.get("dimension") or getattr(logic, "group_by", None)):
            notes.append("Question asks for a named dimension, but the plan would return an ID field.")
            return False, notes, {"action": "repair_table_selection_or_join", "reason": "dimension_fell_back_to_id"}
        return True, notes, None

    if not join_plan.get("trusted"):
        notes.append("Join plan is required but not trusted.")
        return False, notes, {"action": "clarify_join_key", "reason": join_plan.get("reason") or "untrusted_join_plan"}
    if join_plan.get("many_to_many_risk"):
        notes.append("Join plan has many-to-many risk and cannot be treated as a verified result.")
        return False, notes, {"action": "clarify_join_key", "reason": "many_to_many_join_risk"}

    summary = primary.debug.get("join_execution_summary") if isinstance(primary.debug, dict) else None
    if isinstance(summary, dict):
        steps = summary.get("steps")
        if isinstance(steps, list) and steps:
            notes.append(f"Join materialized with {len(steps)} trusted step(s).")
        else:
            notes.append(
                "Join materialized: "
                f"{summary.get('left_table')}.{summary.get('left_key')} -> "
                f"{summary.get('right_table')}.{summary.get('right_key')} "
                f"({summary.get('relationship')})."
            )
        if summary.get("unmatched_left_key_count"):
            notes.append(f"Join produced unmatched primary keys: {summary.get('unmatched_left_key_count')}.")
    elif primary.success:
        notes.append("Trusted join plan exists, but execution did not report join materialization.")
        return False, notes, {"action": "repair_executor_join_trace", "reason": "missing_join_execution_summary"}

    if _asks_named_dimension(question) and _dimension_looks_like_id(params.get("dimension") or getattr(logic, "group_by", None)):
        notes.append("Question asks for a named dimension, but the plan would return an ID field.")
        return False, notes, {"action": "repair_table_selection_or_join", "reason": "dimension_fell_back_to_id"}
    return True, notes, None


def _verify_requested_shape_contract(
    logic: Any,
    question: str,
    primary: ExecutionResult,
) -> tuple[bool, list[str], dict[str, object] | None]:
    if not _asks_grouped_metric_visual(question):
        return True, [], None
    params = getattr(logic, "parameters", {}) or {}
    dimension = str(params.get("dimension") or params.get("group_by") or getattr(logic, "group_by", None) or "")
    metric = str(params.get("metric") or getattr(logic, "metric", None) or "")
    rows = _execution_rows(primary)
    notes: list[str] = []
    if not rows:
        notes.append("Grouped metric/chart request returned no inspectable rows.")
        return False, notes, {"action": "repair_result_shape", "reason": "missing_rows"}
    sample_keys = set(rows[0])
    if dimension and dimension not in sample_keys:
        notes.append(f"Grouped metric/chart result is missing requested dimension column: {dimension}.")
        return False, notes, {"action": "repair_result_shape", "required_column": dimension}
    aggregation = str(params.get("aggregation") or "")
    if aggregation != "count" and metric and metric not in sample_keys:
        notes.append(f"Grouped metric/chart result is missing requested metric column: {metric}.")
        return False, notes, {"action": "repair_result_shape", "required_column": metric}
    notes.append("Grouped metric/chart result shape contains requested dimension and metric columns.")
    return True, notes, None


def _execution_rows(primary: ExecutionResult) -> list[dict[str, Any]]:
    if primary.rows:
        return [row for row in primary.rows if isinstance(row, dict)]
    value = primary.value
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        candidate_table = value.get("candidate_table")
        if isinstance(candidate_table, list):
            rows = [row for row in candidate_table if isinstance(row, dict)]
            if rows:
                return rows
        result_rows = value.get("rows")
        if isinstance(result_rows, list):
            rows = [row for row in result_rows if isinstance(row, dict)]
            if rows:
                return rows
        return [value]
    return []


def _uses_schema_backed_internal_source_alignment(logic: Any) -> bool:
    operation = str(getattr(logic, "operation", "") or "")
    if not operation.startswith("retail_"):
        return False
    capability = capability_for_operation(operation)
    return capability.capability_family == "chinese_retail_business_metric"


def _asks_named_dimension(question: str) -> bool:
    return any(
        token in question
        for token in (
            "city",
            "country",
            "customer name",
            "product name",
            "merchant name",
            "category",
            "channel",
            "month",
            "城市",
            "国家",
            "客户名",
            "客户名称",
            "产品名",
            "产品名称",
            "产品",
            "品类",
            "类别",
            "渠道",
            "月份",
            "商户名",
            "商户名称",
        )
    )


def _dimension_looks_like_id(value: Any) -> bool:
    text = str(value or "").lower()
    return bool(text) and ("id" in text or text.endswith("编号") or text.endswith("代码"))


def _asks_grouped_count(question: str) -> bool:
    return _asks_count_metric(question) and any(token in question for token in (" by ", "group", "per ", "each", "按", "各", "每"))


def _asks_grouped_metric_visual(question: str) -> bool:
    grouped = any(token in question for token in (" by ", "group", "per ", "each", "按", "各", "每"))
    visual_or_display = any(
        token in question
        for token in (
            "show",
            "display",
            "visualize",
            "chart",
            "bar chart",
            "line chart",
            "展示",
            "显示",
            "生成",
            "画",
            "图",
            "图表",
            "柱状图",
            "柱形图",
            "条形图",
            "折线图",
            "饼图",
            "可视化",
        )
    )
    return grouped and visual_or_display


def _asks_multi_entity_comparison(question: str) -> bool:
    return (
        any(token in question for token in ("哪个", "哪家", "which", "highest", "lowest", "最高", "最低", "最多", "最少", "比较", "对比"))
        and any(token in question for token in ("和", "与", "及", "、", " and ", " vs ", " versus "))
    )


def _filter_scope_preserves_multi_entity(question: str, filters: dict[str, Any]) -> bool:
    question_token = _normalize_token(question)
    matched_values: set[str] = set()
    for raw_value in filters.values():
        for value in _flatten_filter_values(raw_value):
            token = _normalize_token(value)
            if token and token in question_token:
                matched_values.add(token)
    return len(matched_values) >= 2


def _flatten_filter_values(value: Any) -> list[str]:
    if value is None or (isinstance(value, str) and value == ""):
        return []
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_flatten_filter_values(item))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_flatten_filter_values(item))
        return values
    text = str(value)
    if any(separator in text for separator in (",", "，", "、", " 和 ", " 与 ", " and ")):
        import re

        return [part for part in re.split(r"\s*(?:,|，|、|和|与|\band\b)\s*", text, flags=re.I) if part]
    return [text]


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
    if _row_count_per_unique_entity(logic):
        return True
    if _counts_entities_after_metric_comparison(logic.operation):
        return True
    return _business_quantity_metric_satisfies_count_question(logic, question)


def _row_count_per_unique_entity(logic: Any) -> bool:
    if str(getattr(logic, "operation", "") or "") != "metric_per_distinct_entity":
        return False
    params = getattr(logic, "parameters", {}) or {}
    numerator = getattr(logic, "numerator", {}) or {}
    metric = str(getattr(logic, "metric", "") or params.get("metric") or numerator.get("field") or "")
    aggregation = str(params.get("aggregation") or numerator.get("aggregation") or "")
    if metric not in {"__row_count__", "row_count", "transaction_count", "record_count"} and aggregation != "count":
        return False
    denominator = getattr(logic, "denominator", {}) or {}
    entity_grain = getattr(logic, "entity_grain", {}) or {}
    return _has_unique_entity_denominator(denominator, entity_grain) or bool(
        params.get("entity_field") or entity_grain.get("field")
    )


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
