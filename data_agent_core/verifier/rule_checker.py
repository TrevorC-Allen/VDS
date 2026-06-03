"""Rule checker for verified final responses."""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import ComparisonResult, VerificationResult
from data_agent_core.core.analysis_planner import complete_generalization_contract
from data_agent_core.core.capability_registry import capability_for_operation
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.task_execution_contracts import (
    TaskExecutionContract,
    build_task_execution_contract,
    semantic_status_from_report,
    verify_task_execution_contract,
)


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
    task_contract = _task_contract_from_plan(plan, user_question) if plan is not None else None
    contract_report = None
    oracle_result = build_oracle_result(task_contract, primary)
    semantic_status = "legacy_unverified"
    if task_contract is not None:
        contract_report = verify_task_execution_contract(task_contract, primary)
        semantic_status = semantic_status_from_report(contract=task_contract, report=contract_report)
        semantic_notes.append(f"Task contract {task_contract.contract_id} checked as {task_contract.task_family}.")
        if not contract_report.passed:
            semantic_passed = False
            issues.append("Task semantic execution contract failed.")
            semantic_notes.extend(item.message for item in contract_report.violations)
            correction_action = correction_action or _referent_correction_action(task_contract, contract_report)
    if plan is not None and user_question is not None:
        complete_generalization_contract(plan.logic_form)
        generalization_passed, generalization_notes, generalization_action = _verify_semantic_contract(plan, user_question, primary)
        semantic_notes.extend(generalization_notes)
        if generalization_action is not None:
            correction_action = generalization_action
        if not generalization_passed:
            semantic_passed = False
            issues.append("Semantic metric definition does not match the user question.")
    if contract_report is not None and not contract_report.passed and _needs_clarification(contract_report):
        semantic_status = "needs_clarification"
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
        task_contract=_json_ready(task_contract) if task_contract is not None else None,
        contract_report=_json_ready(contract_report) if contract_report is not None else None,
        oracle_result=_json_ready(oracle_result),
        semantic_status=semantic_status,
    )


def _task_contract_from_plan(plan: AnalysisPlan | None, user_question: UserQuestion | None) -> TaskExecutionContract | None:
    if plan is None:
        return None
    contract = getattr(plan, "task_contract", None)
    if isinstance(contract, TaskExecutionContract):
        return contract
    if isinstance(contract, dict) and contract:
        return TaskExecutionContract(
            contract_id=str(contract.get("contract_id") or "contract_payload"),
            task_family=str(contract.get("task_family") or "unknown"),  # type: ignore[arg-type]
            required_n=contract.get("required_n"),
            metric=contract.get("metric"),
            dimension=contract.get("dimension"),
            sort_order=contract.get("sort_order"),
            gap_mode=contract.get("gap_mode"),
            required_output_columns=list(contract.get("required_output_columns") or []),
            required_answer_elements=list(contract.get("required_answer_elements") or []),
            requires_previous_artifact=bool(contract.get("requires_previous_artifact")),
            referent_artifact_id=contract.get("referent_artifact_id"),
            referent_dimension=contract.get("referent_dimension"),
            referent_values=list(contract.get("referent_values") or []),
            referent_policy=str(contract.get("referent_policy") or "must_filter_to_previous_result_objects"),
            verification_rules=dict(contract.get("verification_rules") or {}),
            insufficiency_policy=str(contract.get("insufficiency_policy") or "fail_closed"),
        )
    logic_contract = getattr(plan.logic_form, "task_contract", None)
    if isinstance(logic_contract, dict) and logic_contract:
        return _task_contract_from_plan(
            AnalysisPlan(
                plan_id=plan.plan_id,
                logic_form=plan.logic_form,
                steps=plan.steps,
                expected_result_shape=plan.expected_result_shape,
                constraints=plan.constraints,
                task_contract=logic_contract,
            ),
            user_question,
        )
    return build_task_execution_contract(plan.logic_form, question="" if user_question is None else user_question.question)


def _needs_clarification(report: Any) -> bool:
    violations = getattr(report, "violations", []) or []
    return any(getattr(item, "severity", "") == "needs_clarification" for item in violations)


def _referent_correction_action(contract: TaskExecutionContract, report: Any) -> dict[str, object] | None:
    violations = getattr(report, "violations", []) or []
    codes = {str(getattr(item, "code", "") or "") for item in violations}
    if "REFERENT_FILTER_NOT_APPLIED" not in codes:
        return None
    return {
        "action": "repair_referent_filter",
        "reason": "REFERENT_FILTER_NOT_APPLIED",
        "referent_artifact_id": contract.referent_artifact_id,
        "referent_dimension": contract.referent_dimension,
        "referent_values": list(contract.referent_values),
        "referent_policy": contract.referent_policy,
    }


def _json_ready(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


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
    if _asks_explicit_metric_formula(user_question.question) and not _logic_uses_explicit_derived_formula(logic):
        notes.append("Question includes an explicit metric formula, but the plan does not carry it as a derived metric.")
        return False, notes, {"action": "repair_metric_definition", "reason": "explicit_formula_missing"}
    if _asks_grouped_count(question) and logic.operation == "row_count":
        notes.append("Question asks for grouped counts, but the plan returns only a scalar row count.")
        return False, notes, {"action": "replace_operation", "to_operation": "aggregation", "aggregation": "count"}
    if _asks_grouped_metric_visual(question) and logic.operation in {"detail_lookup", "row_count"}:
        notes.append("Question asks for grouped metric output or a chart, but the plan returns detail rows or a scalar count.")
        return False, notes, {"action": "replace_operation", "to_operation": "aggregation", "reason": "grouped_metric_chart_required"}
    if (
        _asks_multi_entity_comparison(question)
        and logic.filters
        and _filters_include_entity_scope(logic.filters)
        and not _filter_scope_preserves_multi_entity(question, logic.filters)
    ):
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
    "product": ("product", "product_name", "sku", "item", "产品", "商品", "品名", "商品名称", "产品名称"),
    "category": (
        "category",
        "category_name",
        "ctg",
        "ctg_name",
        "prod_category",
        "product_category",
        "product_line",
        "productline",
        "product_segment",
        "sku_category",
        "sku_cat",
        "cat",
        "line",
        "segment",
        "类别",
        "类别名称",
        "品类",
        "品类名称",
        "商品品类",
        "产品品类",
        "产品线",
        "商品线",
        "品项",
        "类目",
        "类目名称",
        "分类",
    ),
    "store": ("store", "shop", "branch", "门店", "店铺"),
    "city": ("city", "城市", "市"),
    "channel": ("channel", "channel_name", "sale_channel", "sales_channel", "source_channel", "source", "origin", "来源", "渠道", "渠道名称", "销售渠道", "来源渠道", "获客渠道", "通路", "通路名称"),
    "segment": ("segment", "customer_segment", "cust_segment", "客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "细分"),
    "service_line": ("service_line", "business_line", "service", "line", "服务线", "业务线", "服务", "业务"),
    "customer": ("customer", "cust", "client", "客户", "终端"),
    "service_line": ("service_line", "business_line", "service", "line", "服务线", "业务线", "服务", "业务"),
    "month": ("month", "month_id", "month_code", "stat_month", "ym", "year_month", "biz_month", "period", "month_period", "period_month", "年月", "月份", "月度", "业务月份", "统计月份", "期间"),
    "time": ("date", "day", "week", "period", "time", "sign_time", "create_time", "日期", "时间", "周期", "业务日期", "统计日期", "签收时间", "创建时间"),
}

METRIC_CONCEPT_ALIASES = {
    "sales": ("sales", "sale", "revenue", "amount", "amt", "sales_amt", "sign_amt", "ord_amt", "dist_sign_amt", "销售额", "销售金额", "销售", "收入", "金额", "订单金额", "签收金额", "分销金额"),
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
    requested_dimensions = _target_dimension_concepts(question) or _requested_dimension_concepts(question)
    schema_backed_semantics = _uses_schema_backed_semantic_binding(logic)
    if _card_scheme_steering_uses_temporal_scope_filters(logic, requested_dimensions):
        notes.append("Card scheme steering uses month/year language as filter scope, not as a grouped output dimension.")
        return True, notes, None
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
            available = [str(item) for item in params.get("available_columns") or []]
            notes.append(f"Question requests dimension {requested_dimensions}, but plan uses dimension {dimension_fields[0]}.")
            return False, notes, {
                "action": "repair_dimension_binding",
                "requested_dimensions": requested_dimensions,
                "actual_dimension": dimension_fields[0],
                "available_columns": available,
            }
        rows = _execution_rows(primary)
        if rows and not any(field in rows[0] for field in matched_dimensions):
            if _scalar_share_operation(logic):
                notes.append("Top-K share returns a scalar percentage; requested dimension is used for grouping but not exposed as an output column.")
                return True, notes, None
            notes.append(f"Question requests dimension {matched_dimensions[0]}, but execution rows do not contain it.")
            return False, notes, {"action": "repair_result_shape", "required_column": matched_dimensions[0]}

    requested_metrics = _requested_metric_concepts(question)
    explicit_formula_components_bound = _explicit_formula_components_bound(logic, question, requested_metrics)
    derived_metric_components_bound = _derived_metric_components_bound(logic, requested_metrics) if _asks_profit_margin(question) else False
    if explicit_formula_components_bound:
        notes.append("Explicit derived metric formula binds requested base metric components; output may expose the derived metric only.")
    if derived_metric_components_bound:
        notes.append("Derived metric components bind requested base metric concepts; output may expose the derived metric only.")
    if len(requested_metrics) > 1 and not schema_backed_semantics and not explicit_formula_components_bound and not derived_metric_components_bound:
        metric_fields = _semantic_metric_fields(logic)
        candidate_metric_fields = _candidate_filter_metric_fields(logic)
        missing_metrics = [
            concept
            for concept in requested_metrics
            if not any(_column_matches_concept(field, concept, METRIC_CONCEPT_ALIASES) for field in metric_fields)
            and not any(_column_matches_concept(field, concept, METRIC_CONCEPT_ALIASES) for field in candidate_metric_fields)
        ]
        if missing_metrics:
            available = [str(item) for item in params.get("available_columns") or []]
            notes.append(f"Question requests multiple metrics {requested_metrics}, but plan only binds {metric_fields}.")
            return False, notes, {
                "action": "repair_metric_binding",
                "requested_metrics": requested_metrics,
                "missing_metrics": missing_metrics,
                "actual_metrics": metric_fields,
                "available_columns": available,
            }
        if candidate_metric_fields:
            notes.append("Candidate-set metric bound as TopN filter: " + ", ".join(candidate_metric_fields))
        rows = _execution_rows(primary)
        if rows:
            sample_keys = set(rows[0])
            missing_result_columns = [
                field
                for field in metric_fields
                if any(_column_matches_concept(field, concept, METRIC_CONCEPT_ALIASES) for concept in requested_metrics)
                and field not in sample_keys
            ]
            if missing_result_columns:
                notes.append("Multi-metric result is missing requested metric column(s): " + ", ".join(missing_result_columns))
                return False, notes, {"action": "repair_result_shape", "required_columns": missing_result_columns}
        notes.append("Multiple requested metrics are bound and exposed in the result.")

    if _asks_profit_margin(question):
        if _logic_uses_schema_backed_profit_margin(logic):
            notes.append("Schema-backed business ratio metric verified for profit margin/rate.")
            return True, notes, None
        if _profit_margin_bound_as_candidate_filter(logic, question):
            notes.append("Profit margin is bound as a derived candidate-set metric; result metric answers the scoped ranking question.")
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


def _semantic_metric_fields(logic: Any) -> list[str]:
    params = getattr(logic, "parameters", {}) or {}
    raw_fields: list[Any] = []
    metrics = params.get("metrics")
    if isinstance(metrics, (list, tuple)):
        raw_fields.extend(metrics)
    raw_fields.extend([params.get("metric"), getattr(logic, "metric", None)])
    metric_definition = getattr(logic, "metric_definition", {}) or {}
    if isinstance(metric_definition, dict):
        definition_metrics = metric_definition.get("metrics")
        if isinstance(definition_metrics, (list, tuple)):
            raw_fields.extend(definition_metrics)
        elif "," not in str(metric_definition.get("name") or ""):
            raw_fields.append(metric_definition.get("name"))
    fields: list[str] = []
    for field in raw_fields:
        text = str(field or "").strip()
        if text and text not in fields:
            fields.append(text)
    return fields


def _candidate_filter_metric_fields(logic: Any) -> list[str]:
    params = getattr(logic, "parameters", {}) or {}
    candidate_filter = params.get("candidate_filter")
    if not isinstance(candidate_filter, dict):
        return []
    metric = str(candidate_filter.get("metric") or "").strip()
    return [metric] if metric else []


def _explicit_formula_components_bound(logic: Any, question: str, requested_metrics: list[str]) -> bool:
    if len(requested_metrics) <= 1 or not _asks_explicit_metric_formula(question):
        return False
    return _derived_metric_components_bound(logic, requested_metrics)


def _derived_metric_components_bound(logic: Any, requested_metrics: list[str]) -> bool:
    if len(requested_metrics) <= 1:
        return False
    params = getattr(logic, "parameters", {}) or {}
    derived_metric = params.get("derived_metric")
    if not isinstance(derived_metric, dict) or not derived_metric:
        return False
    component_fields = [
        str(derived_metric.get("numerator") or ""),
        str(derived_metric.get("denominator") or ""),
    ]
    if not all(component_fields):
        return False
    return all(
        any(_column_matches_concept(field, concept, METRIC_CONCEPT_ALIASES) for field in component_fields)
        for concept in requested_metrics
    )


def _scalar_share_operation(logic: Any) -> bool:
    operation = str(getattr(logic, "operation", "") or "")
    output_format = getattr(logic, "output_format", {}) or {}
    answer_type = str(output_format.get("answer_type") or "")
    return operation == "top_k_share" and answer_type in {"percentage", "number"}


def _logic_uses_schema_backed_profit_margin(logic: Any) -> bool:
    operation = str(getattr(logic, "operation", "") or "")
    capability = capability_for_operation(operation)
    if capability.capability_family != "vds_period_comparison":
        return False
    params = getattr(logic, "parameters", {}) or {}
    metric = str(params.get("metric") or getattr(logic, "metric", "") or "")
    normalized = _normalize_token(metric).upper().removesuffix("ROW")
    return normalized in {"PM", "GM"} or any(token in metric for token in ("利润率", "毛利率"))


def _profit_margin_bound_as_candidate_filter(logic: Any, question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    if not re.search(r"(?:利润率|毛利率)[^，,。？?；;]{0,20}(?:排名)?前(?:\d+|[一二两三四五六七八九十]+)", compact):
        return False
    params = getattr(logic, "parameters", {}) or {}
    candidate_filter = params.get("candidate_filter")
    if not isinstance(candidate_filter, dict):
        return False
    derived_metric = candidate_filter.get("derived_metric")
    if not isinstance(derived_metric, dict):
        return False
    return bool(derived_metric.get("name") and derived_metric.get("numerator") and derived_metric.get("denominator"))


def _uses_schema_backed_semantic_binding(logic: Any) -> bool:
    capability = capability_for_operation(str(getattr(logic, "operation", "") or ""))
    return capability.capability_family in {"vds_period_comparison", "chinese_retail_business_metric"}


def _requested_dimension_concepts(question: str) -> list[str]:
    requested: list[str] = []
    for concept, aliases in DIMENSION_CONCEPT_ALIASES.items():
        if concept == "customer" and not _explicit_customer_dimension_request(question):
            continue
        if any(_alias_in_question(question, alias) for alias in aliases):
            requested.append(concept)
    if _question_requests_time_series(question) and "month" not in requested:
        requested.append("month")
    return requested


def _target_dimension_concepts(question: str) -> list[str]:
    """Return dimensions that the user asks to receive, not merely scope phrases.

    In questions like "all cities中利润率前3的服务线", city is the universe/scope
    and service_line is the answer dimension. Dimension repair must preserve
    that distinction or it can "fix" a valid plan back to the scope field.
    """

    import re

    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    result_dimension = _result_dimension_after_extreme_time_scope(question)
    if result_dimension:
        return [result_dimension]
    scoped_answer_dimension = _dimension_after_growth_entity_scope(compact, lowered)
    if scoped_answer_dimension:
        return [scoped_answer_dimension]
    growth_entity_dimension = _growth_ranking_entity_target(compact, lowered)
    ordered_patterns = (
        ("segment", ("客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "细分市场", "哪个客户群", "哪些客户群", "哪个客群", "哪些客群", "客群是什么", "客群是哪", "按客群", "客群排名", "segment")),
        ("product", ("哪个产品", "哪种产品", "哪些产品", "产品是哪个", "产品是哪", "产品有哪些", "产品是哪些", "按产品", "产品贡献", "产品排名", "which product", "by product")),
        ("customer", ("哪个客户", "哪些客户", "客户是哪个", "客户是哪", "客户是谁", "客户是什么", "客户有哪些", "客户是哪些", "按客户", "客户贡献", "客户排名", "which customer", "by customer")),
        ("service_line", ("哪个服务线", "哪些服务线", "服务线是哪个", "服务线是哪", "服务线有哪些", "按服务线", "服务线排名", "哪个业务线", "哪些业务线", "业务线是哪个", "业务线是哪", "业务线有哪些", "按业务线", "业务线排名", "which service line", "by service line", "business line")),
        ("city", ("各城市", "各个城市", "每个城市", "哪个城市", "哪些城市", "城市是哪个", "城市是哪", "城市有哪些", "城市是哪些", "这些城市", "这几个城市", "按城市", "城市贡献", "城市排名", "which city", "by city")),
        ("category", ("哪个品类", "哪些品类", "品类是哪个", "品类是哪", "品类有哪些", "品类是哪些", "按品类", "品类贡献", "品类排名", "which category", "by category")),
        ("month", ("按月份", "哪个月份", "月度趋势", "趋势", "各月", "每月", "变化趋势", "如何变化", "怎么变化", "怎样变化", "by month", "monthly", "change over time")),
    )
    targets: list[str] = []
    for concept, patterns in ordered_patterns:
        if any((pattern in compact if any("\u4e00" <= char <= "\u9fff" for char in pattern) else pattern in lowered) for pattern in patterns):
            targets.append(concept)
    quantity_targets = (
        ("city", r"哪(?:\d+|[一二两三四五六七八九十]+)?个城市"),
        ("customer", r"哪(?:\d+|[一二两三四五六七八九十]+)?个客户"),
        ("product", r"哪(?:\d+|[一二两三四五六七八九十]+)?(?:个|种)?产品"),
        ("service_line", r"哪(?:\d+|[一二两三四五六七八九十]+)?(?:个|条)?(?:服务线|业务线)"),
    )
    for concept, pattern in quantity_targets:
        if re.search(pattern, compact) and concept not in targets:
            targets.append(concept)
    if "segment" in targets and any(token in compact for token in ("客户群", "客户群体", "客户细分", "客户分区", "客户分段", "客户段", "客群", "细分市场")):
        targets = [target for target in targets if target != "customer"]
    if growth_entity_dimension:
        return targets or [growth_entity_dimension]
    if _question_requests_time_series(question):
        return ["month", "time"]
    return targets


def _growth_ranking_entity_target(compact: str, lowered: str) -> str:
    growth_tokens = (
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
    if not any(token in compact for token in growth_tokens) and not any(
        token in lowered for token in ("fastest growth", "largest growth", "highest growth", "biggest increase", "largest increase", "fastest decline")
    ):
        return ""
    scoped_answer_dimension = _dimension_after_growth_entity_scope(compact, lowered)
    if scoped_answer_dimension:
        return scoped_answer_dimension
    targets = (
        ("city", ("哪个城市", "哪些城市", "这些城市", "几个城市", "个城市", "城市中", "城市里", "which city", "city growth")),
        ("customer", ("哪个客户", "哪些客户", "这些客户", "几个客户", "个客户", "客户中", "客户里", "which customer", "customer growth")),
        ("product", ("哪个产品", "哪些产品", "哪种产品", "这些产品", "几个产品", "个产品", "产品中", "产品里", "which product", "product growth")),
        ("service_line", ("哪个服务线", "哪些服务线", "几个服务线", "个服务线", "服务线中", "业务线中", "which service line", "service line growth", "business line growth")),
    )
    for concept, patterns in targets:
        if any((pattern in compact if any("\u4e00" <= char <= "\u9fff" for char in pattern) else pattern in lowered) for pattern in patterns):
            return concept
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
    targets = (
        ("segment", ("客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "细分市场", "哪个客户群", "哪些客户群", "哪个客群", "哪些客群", "segment")),
        ("customer", ("哪个客户", "哪些客户", "客户是哪个", "客户是哪", "客户是谁", "按客户", "which customer", "by customer")),
        ("product", ("哪个产品", "哪种产品", "哪些产品", "产品是哪个", "产品是哪", "按产品", "which product", "by product")),
        ("service_line", ("哪个服务线", "哪些服务线", "哪个业务线", "哪些业务线", "按服务线", "按业务线", "which service line", "by service line", "business line")),
        ("city", ("哪个城市", "哪些城市", "按城市", "which city", "by city")),
    )
    for concept, patterns in targets:
        if any((pattern in suffix if any("\u4e00" <= char <= "\u9fff" for char in pattern) else pattern in lowered) for pattern in patterns):
            return concept
    return ""


def _result_dimension_after_extreme_time_scope(question: str) -> str:
    import re

    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    asks_extreme_time = (
        any(token in compact for token in ("哪个月份", "哪个月", "哪月份", "哪月"))
        and any(token in compact for token in ("最高", "最大", "最多", "最低", "最小", "最少"))
    ) or bool(re.search(r"(?:which|what)\s+month.+(?:highest|top|largest|most|lowest|smallest|least)", lowered))
    if not asks_extreme_time:
        return ""
    suffix_target_patterns = (
        ("city", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?城市"),
        ("customer", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?客户"),
        ("product", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?(?:产品|商品)"),
        ("service_line", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位|条)?(?:大)?的?(?:服务线|业务线)"),
    )
    for concept, pattern in suffix_target_patterns:
        if re.search(pattern, compact):
            return concept
    if "top" in lowered:
        if "city" in lowered:
            return "city"
        if "customer" in lowered:
            return "customer"
        if "product" in lowered:
            return "product"
        if "service line" in lowered or "business line" in lowered:
            return "service_line"
    return ""


def _question_requests_time_series(question: str) -> bool:
    compact = "".join(str(question or "").split())
    lowered = str(question or "").lower()
    return any(
        token in compact
        for token in ("趋势", "月度变化", "季度变化", "按月份", "按月度", "按季度", "每月", "各月", "变化趋势", "如何变化", "怎么变化", "怎样变化")
    ) or any(token in lowered for token in ("trend", "monthly", "quarterly", "by quarter", "month by month", "change over time"))


def _explicit_customer_dimension_request(question: str) -> bool:
    compact = "".join(str(question or "").split())
    lowered = str(question or "").lower()
    if any(token in compact for token in ("客户群", "客户群体", "客户细分", "客户分区", "客户分段", "客户段", "客群", "细分市场")):
        return False
    return any(
        token in compact
        for token in ("哪个客户", "哪些客户", "哪位客户", "客户是谁", "客户是哪", "客户是哪位", "客户是哪一位", "客户是什么", "按客户", "客户排名", "客户贡献", "客户维度")
    ) or bool(
        re.search(r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?客户", compact)
    ) or any(token in lowered for token in ("by customer", "which customer", "customer ranking", "customer segment"))


def _requested_metric_concepts(question: str) -> list[str]:
    requested: list[str] = []
    for concept, aliases in METRIC_CONCEPT_ALIASES.items():
        if any(_alias_in_question(question, alias) for alias in aliases):
            requested.append(concept)
    return requested


def _card_scheme_steering_uses_temporal_scope_filters(logic: Any, requested_dimensions: list[str]) -> bool:
    if str(getattr(logic, "operation", "") or "") != "card_scheme_steering":
        return False
    if not requested_dimensions or not set(requested_dimensions).issubset({"month", "time"}):
        return False
    filters = getattr(logic, "filters", {}) or {}
    temporal_keys = ("month", "month_range", "year", "day_of_year")
    return any(filters.get(key) not in (None, "", [], ()) for key in temporal_keys)


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
    import re

    for segment in re.split(r"[。.!?？\n]+", str(text or "")):
        if "=" in segment and any(operator in segment for operator in ("/", "+", "*")):
            return True
    return False


def _asks_explicit_metric_formula(question: str) -> bool:
    return _looks_like_metric_formula(question) and bool(re_search(r"sum\s*\(?|利润率|达成率|占比|率\s*=", question))


def _logic_uses_explicit_derived_formula(logic: Any) -> bool:
    params = getattr(logic, "parameters", {}) or {}
    derived_metric = params.get("derived_metric")
    if not isinstance(derived_metric, dict) or not derived_metric:
        operation = str(getattr(logic, "operation", "") or "")
        output_format = getattr(logic, "output_format", {}) or {}
        answer_type = str(output_format.get("answer_type") or "")
        if operation.startswith("retail_") and operation.endswith("_rate") and answer_type in {"percentage", "ratio", "number"}:
            return True
        return False
    return bool(derived_metric.get("name") and derived_metric.get("numerator") and derived_metric.get("denominator") and derived_metric.get("formula"))


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
        return False, notes, {
            "action": "clarify_join_key",
            "reason": "multi_table_without_join_plan",
            "source_tables": source_tables,
            "requested_dimensions": _requested_dimension_concepts(question),
        }
    dimension = params.get("dimension") or getattr(logic, "group_by", None)
    if not join_plan:
        if _asks_named_dimension(question) and _dimension_looks_like_id(dimension):
            if _id_dimension_is_acceptable_entity_binding(question, dimension, params):
                notes.append("Requested entity dimension is represented by a stable ID column because no non-ID label column is available.")
                return True, notes, None
            notes.append("Question asks for a named dimension, but the plan would return an ID field.")
            return False, notes, {
                "action": "repair_table_selection_or_join",
                "reason": "dimension_fell_back_to_id",
                "actual_dimension": dimension,
                "requested_dimensions": _requested_dimension_concepts(question),
            }
        return True, notes, None

    if not join_plan.get("trusted"):
        notes.append("Join plan is required but not trusted.")
        return False, notes, {
            "action": "clarify_join_key",
            "reason": join_plan.get("reason") or "untrusted_join_plan",
            "join_plan": join_plan,
            "source_tables": source_tables,
            "requested_dimensions": _requested_dimension_concepts(question),
        }
    if join_plan.get("many_to_many_risk"):
        notes.append("Join plan has many-to-many risk and cannot be treated as a verified result.")
        return False, notes, {
            "action": "clarify_join_key",
            "reason": "many_to_many_join_risk",
            "join_plan": join_plan,
            "source_tables": source_tables,
            "requested_dimensions": _requested_dimension_concepts(question),
        }

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

    if _asks_named_dimension(question) and _dimension_looks_like_id(dimension):
        if _id_dimension_is_acceptable_entity_binding(question, dimension, params):
            notes.append("Requested entity dimension is represented by a stable ID column because no non-ID label column is available.")
            return True, notes, None
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
        if getattr(logic, "filters", {}):
            notes.append("Grouped metric/chart request returned no rows after explicit filters; treated as an empty-result boundary.")
            return True, notes, None
        notes.append("Grouped metric/chart request returned no inspectable rows.")
        return False, notes, {"action": "repair_result_shape", "reason": "missing_rows"}
    sample_keys = set(rows[0])
    if dimension and not _result_has_requested_column(sample_keys, dimension):
        notes.append(f"Grouped metric/chart result is missing requested dimension column: {dimension}.")
        return False, notes, {"action": "repair_result_shape", "required_column": dimension}
    aggregation = str(params.get("aggregation") or "")
    if aggregation != "count" and metric and not _result_has_requested_column(sample_keys, metric):
        notes.append(f"Grouped metric/chart result is missing requested metric column: {metric}.")
        return False, notes, {"action": "repair_result_shape", "required_column": metric}
    notes.append("Grouped metric/chart result shape contains requested dimension and metric columns.")
    return True, notes, None


def _result_has_requested_column(sample_keys: set[str], requested: str) -> bool:
    if requested in sample_keys:
        return True
    aliases = _result_column_aliases(requested)
    return any(alias in sample_keys for alias in aliases)


def _result_column_aliases(column: str) -> set[str]:
    aliases = {
        "cust_name": {"客户", "终端", "门店", "客户名称", "终端客户"},
        "cust_code": {"客户编码", "终端客户编码"},
        "channel_name": {"渠道"},
        "p_channel_name": {"父渠道", "大渠道"},
        "sku_name": {"SKU", "产品", "商品"},
        "ctg_name": {"品类", "分类"},
        "capacity": {"容量", "规格"},
        "emp_name": {"业代", "人员", "员工"},
        "p_emp_name": {"主任", "主管"},
        "sign_amt": {"分销金额", "签收金额", "销售金额", "金额"},
        "sign_box_cnt": {"分销箱数", "签收箱数", "箱数", "数量"},
    }
    return aliases.get(str(column), set())


def _empty_result_shape_is_inspectable(primary: ExecutionResult, dimension: str, metric: str, aggregation: str) -> bool:
    columns = set(str(column) for column in (primary.columns or []))
    if not columns and isinstance(primary.value, dict):
        columns = set(str(column) for column in (primary.value.get("columns") or []))
    if not columns:
        return bool(dimension and (metric or aggregation in {"count", "nunique", "distinct_count"}))
    if dimension and not _result_has_requested_column(columns, dimension):
        return False
    if aggregation not in {"count", "nunique", "distinct_count"} and metric and not _result_has_requested_column(columns, metric):
        return False
    return True


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


def _id_dimension_is_acceptable_entity_binding(question: str, dimension: Any, params: dict[str, Any]) -> bool:
    """Allow stable entity IDs only when they match the requested entity and no label exists."""

    dimension_text = str(dimension or "")
    requested = _requested_dimension_concepts(question)
    if not dimension_text or not requested:
        return False
    matching_concepts = [
        concept
        for concept in requested
        if _column_matches_concept(dimension_text, concept, DIMENSION_CONCEPT_ALIASES)
    ]
    if not matching_concepts:
        return False
    available_columns = [str(column) for column in params.get("available_columns") or [] if str(column)]
    for column in available_columns:
        if column == dimension_text or _dimension_looks_like_id(column):
            continue
        if any(_column_matches_concept(column, concept, DIMENSION_CONCEPT_ALIASES) for concept in matching_concepts):
            return False
    return True


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


def _filters_include_entity_scope(filters: dict[str, Any]) -> bool:
    for key, value in filters.items():
        column = str(key or "").lower()
        if _filter_key_is_time_like(column):
            continue
        if isinstance(value, dict) and any(_filter_key_is_time_like(str(item).lower()) for item in value):
            continue
        return True
    return False


def _filter_key_is_time_like(column: str) -> bool:
    return any(token in column for token in ("date", "day", "month", "year", "week", "time", "日期", "时间", "月份", "年份", "周"))


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
    params = getattr(logic, "parameters", {}) or {}
    specs = params.get("metric_specs")
    if isinstance(specs, list) and any(
        isinstance(spec, dict) and str(spec.get("aggregation") or "") in {"count", "distinct_count", "nunique"}
        for spec in specs
    ):
        return True
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
