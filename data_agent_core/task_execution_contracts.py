"""Task-level semantic execution contracts for data-agent verification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from data_agent_core.contracts.execution_contracts import ExecutionResult


TaskFamily = Literal[
    "topn",
    "gap",
    "trend",
    "followup_referent",
    "overview",
    "multi_file_overview",
    "data_quality",
    "unknown",
]

SEMANTIC_STATUSES = {
    "passed",
    "passed_with_insufficient_data",
    "corrected_passed",
    "partial",
    "failed",
    "needs_clarification",
    "legacy_unverified",
}


@dataclass
class ContractViolation:
    """One deterministic semantic-contract issue."""

    code: str
    severity: str
    message: str
    correction_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContractVerificationReport:
    """Deterministic verification result for a TaskExecutionContract."""

    contract_id: str
    task_family: TaskFamily
    passed: bool
    violations: list[ContractViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class TaskExecutionContract:
    """Semantic task contract derived from LogicForm and AnalysisPlan."""

    contract_id: str
    task_family: TaskFamily
    required_n: int | None = None
    metric: str | None = None
    dimension: str | None = None
    time_dimension: str | None = None
    sort_order: str | None = None
    gap_mode: str | None = None
    required_output_columns: list[str] = field(default_factory=list)
    required_answer_elements: list[str] = field(default_factory=list)
    requires_previous_artifact: bool = False
    referent_artifact_id: str | None = None
    referent_dimension: str | None = None
    referent_values: list[Any] = field(default_factory=list)
    referent_policy: str = "must_filter_to_previous_result_objects"
    referent_source: str = ""
    requires_gap_comparison: bool = False
    minimum_required_objects: int | None = None
    preferred_top_n: int | None = None
    auto_expand_topn_if_needed: bool = False
    expansion_source: str = ""
    verification_rules: dict[str, Any] = field(default_factory=dict)
    insufficiency_policy: str = "fail_closed"


def build_task_execution_contract(logic_form: Any, *, question: str = "") -> TaskExecutionContract | None:
    """Derive the first task-level contract without changing planner behavior."""

    operation = _get(logic_form, "operation", "")
    task_type = _get(logic_form, "task_type", "")
    params = _dict(_get(logic_form, "parameters", {}))
    output_format = _dict(_get(logic_form, "output_format", {}))
    source_tables = list(_get(logic_form, "source_tables", []) or [])
    family = _task_family(operation=operation, task_type=task_type, question=question, source_tables=source_tables)
    if family == "unknown":
        return None
    metric = _first_text(params.get("metric"), _get(logic_form, "metric"), output_format.get("metric"))
    dimension = _first_text(params.get("dimension"), params.get("group_by"), _get(logic_form, "group_by"), output_format.get("entity_field"))
    if family == "trend":
        dimension = _first_text(params.get("time_column"), params.get("time_dimension"), dimension)
    time_dimension = dimension if family == "trend" else None
    question_required_n = _required_n_from_question(question)
    required_n = question_required_n or _positive_int(params.get("limit") or params.get("top_n") or params.get("k"))
    sort_order = _first_text(params.get("sort_order")) or ("asc" if _asks_lowest(question) else "desc")
    gap_mode = "rank_pair" if family == "gap" and _asks_rank_pair(question) else "adjacent_and_to_leader" if family == "gap" else None
    required_columns = _required_columns(
        family=family,
        operation=operation,
        metric=metric,
        dimension=dimension,
        output_format=output_format,
        params=params,
    )
    file_scope_family = family in {"overview", "multi_file_overview", "data_quality"}
    requires_previous = bool(
        not file_scope_family
        and (params.get("requires_previous_artifact") or params.get("referent_artifact_id") or _looks_like_followup(question))
    )
    referent_dimension = None if file_scope_family else _first_text(params.get("referent_dimension"))
    referent_values = [] if file_scope_family else list(params.get("referent_values") or [])
    auto_expand_topn_if_needed = bool(params.get("auto_expand_topn_if_needed"))
    minimum_required_objects = _positive_int(params.get("minimum_required_objects"))
    preferred_top_n = _positive_int(params.get("preferred_top_n"))
    if family == "gap" and auto_expand_topn_if_needed:
        minimum_required_objects = minimum_required_objects or 2
        preferred_top_n = preferred_top_n or 3
        required_n = max(required_n or 0, preferred_top_n)
    referent_filter_applied = False
    if referent_dimension and referent_values:
        filter_value = _dict(_get(logic_form, "filters", {})).get(referent_dimension)
        referent_filter_applied = _values_cover(filter_value, referent_values)
    contract_seed = {
        "operation": operation,
        "task_type": task_type,
        "family": family,
        "metric": metric,
        "dimension": dimension,
        "required_n": required_n,
        "sort_order": sort_order,
        "gap_mode": gap_mode,
        "source_tables": source_tables,
    }
    contract_id = "contract_" + hashlib.sha1(repr(contract_seed).encode("utf-8")).hexdigest()[:12]
    return TaskExecutionContract(
        contract_id=contract_id,
        task_family=family,
        required_n=required_n,
        metric=metric,
        dimension=dimension,
        time_dimension=time_dimension,
        sort_order=sort_order if family == "topn" else None,
        gap_mode=gap_mode,
        required_output_columns=required_columns,
        required_answer_elements=_required_answer_elements(family),
        requires_previous_artifact=requires_previous,
        referent_artifact_id=None if file_scope_family else _first_text(params.get("referent_artifact_id")),
        referent_dimension=referent_dimension,
        referent_values=referent_values,
        referent_policy=str(params.get("referent_policy") or "must_filter_to_previous_result_objects"),
        referent_source=str(params.get("referent_source") or ""),
        requires_gap_comparison=bool(params.get("requires_gap_comparison") or family == "gap"),
        minimum_required_objects=minimum_required_objects,
        preferred_top_n=preferred_top_n,
        auto_expand_topn_if_needed=auto_expand_topn_if_needed,
        expansion_source=str(params.get("expansion_source") or ""),
        verification_rules={
            "requires_execution_success": True,
            "requires_non_empty_value": family not in {"overview", "multi_file_overview", "data_quality"},
            "required_output_columns": required_columns,
            "referent_filter_applied": referent_filter_applied,
            "candidate_set": _dict(_get(logic_form, "candidate_set", {})),
            "explicit_required_n": question_required_n is not None,
            "requires_gap_comparison": bool(params.get("requires_gap_comparison") or family == "gap"),
            "minimum_required_objects": minimum_required_objects,
            "preferred_top_n": preferred_top_n,
            "auto_expand_topn_if_needed": auto_expand_topn_if_needed,
            "expansion_source": str(params.get("expansion_source") or ""),
            **_family_verification_rules(family),
        },
        insufficiency_policy="needs_clarification" if requires_previous else "fail_closed",
    )


def verify_task_execution_contract(contract: TaskExecutionContract, execution_result: ExecutionResult) -> ContractVerificationReport:
    """Check deterministic semantics that do not require an LLM judge."""

    violations: list[ContractViolation] = []
    warnings: list[str] = []
    if contract.verification_rules.get("requires_execution_success") and not execution_result.success:
        violations.append(
            ContractViolation(
                code="execution_failed",
                severity="error",
                message="Execution did not complete successfully for the contracted task.",
                correction_hint="Repair the LogicForm or executor path before trusting the answer.",
            )
        )
    if (
        contract.task_family != "trend"
        and contract.verification_rules.get("requires_non_empty_value")
        and _empty_value(execution_result.value, execution_result.rows)
    ):
        violations.append(
            ContractViolation(
                code="empty_result",
                severity="error",
                message="Execution returned no value for a task that requires a concrete result.",
                correction_hint="Check metric, dimension, filters, and table selection.",
            )
        )
    available_columns = _available_result_columns(execution_result)
    if contract.task_family != "trend":
        missing_columns = [column for column in contract.required_output_columns if column and not _column_present(column, available_columns)]
        if missing_columns and _tabular_result_present(execution_result):
            violations.append(
                ContractViolation(
                    code="required_output_column_missing",
                    severity="error",
                    message="The result is missing contract-required output columns.",
                    correction_hint="Regenerate the execution plan with the requested metric and dimension columns.",
                    metadata={"missing_columns": missing_columns, "available_columns": sorted(available_columns)},
                )
            )
    row_count = _row_count(execution_result)
    if (
        contract.task_family == "topn"
        and contract.required_n
        and contract.verification_rules.get("explicit_required_n")
        and row_count is not None
        and row_count < contract.required_n
    ):
        distinct_count = _distinct_count(execution_result, contract.dimension) or row_count
        answer_text = _direct_answer_text(execution_result)
        if not answer_text.strip():
            warnings.append(f"topn_insufficient_data:{distinct_count}<{contract.required_n}")
        elif _has_explicit_topn_insufficient_explanation(
            answer_text,
            distinct_count=distinct_count,
            required_n=contract.required_n,
            dimension=contract.dimension or "对象",
        ):
            warnings.append(f"topn_insufficient_data:{distinct_count}<{contract.required_n}")
        else:
            violations.append(
                _violation(
                    "TOPN_INSUFFICIENT_EXPLANATION_MISSING",
                    "TopN result has fewer rows than requested but lacks the required explicit insufficient-data explanation.",
                    {
                        "required_n": contract.required_n,
                        "row_count": row_count,
                        "distinct_count": distinct_count,
                    },
                )
            )
    if contract.task_family == "topn":
        violations.extend(_verify_topn_contract(contract, execution_result))
    if contract.task_family == "gap":
        violations.extend(_verify_gap_contract(contract, execution_result))
    if contract.task_family == "trend":
        violations.extend(_verify_trend_contract(contract, execution_result))
    if contract.requires_previous_artifact and not contract.referent_artifact_id:
        violations.append(
            ContractViolation(
                code="REFERENT_ARTIFACT_MISSING",
                severity="needs_clarification",
                message="The task depends on a previous artifact, but no referent artifact or values were bound.",
                correction_hint="Ask for clarification or bind the previous result before executing.",
            )
        )
    if contract.requires_previous_artifact and not contract.referent_values:
        violations.append(
            ContractViolation(
                code="REFERENT_VALUES_MISSING",
                severity="needs_clarification",
                message="The task depends on previous result objects, but the referent value set is empty.",
                correction_hint="Ask for clarification or rebuild from the previous result artifact.",
            )
        )
    requires_referent_filter = contract.referent_policy == "must_filter_to_previous_result_objects" and not contract.auto_expand_topn_if_needed
    if contract.requires_previous_artifact and contract.referent_values and requires_referent_filter and not contract.verification_rules.get("referent_filter_applied"):
        violations.append(
            ContractViolation(
                code="REFERENT_FILTER_NOT_APPLIED",
                severity="error",
                message="The execution plan did not filter to the previous result objects.",
                correction_hint="Inject the referent values as a filter and rerun execution.",
                metadata={"referent_dimension": contract.referent_dimension, "referent_values": contract.referent_values},
            )
        )
    if contract.requires_previous_artifact and contract.referent_values and requires_referent_filter:
        violations.extend(_verify_referent_result_scope(contract, execution_result))
    if contract.task_family in {"overview", "multi_file_overview"}:
        violations.extend(_verify_overview_contract(contract, execution_result))
    if contract.task_family == "data_quality":
        violations.extend(_verify_data_quality_contract(execution_result))
    return ContractVerificationReport(
        contract_id=contract.contract_id,
        task_family=contract.task_family,
        passed=not violations,
        violations=violations,
        warnings=warnings,
    )


def semantic_status_from_report(
    *,
    contract: TaskExecutionContract | None,
    report: ContractVerificationReport | None,
    corrected: bool = False,
) -> str:
    """Map deterministic contract evidence to the public semantic status."""

    if contract is None or report is None:
        return "legacy_unverified"
    if report.passed:
        if any(str(warning).startswith("topn_insufficient_data") for warning in report.warnings):
            return "passed_with_insufficient_data"
        return "corrected_passed" if corrected else "passed"
    if any(item.severity == "needs_clarification" for item in report.violations):
        return "needs_clarification"
    return "failed"


def _task_family(*, operation: str, task_type: str, question: str, source_tables: list[str]) -> TaskFamily:
    operation = str(operation or "")
    task_type = str(task_type or "")
    compact_question = "".join(str(question or "").split()).lower()
    overview_question = any(
        token in compact_question
        for token in ("概览", "overview", "数据结构", "表结构", "字段", "能支持哪些分析", "支持哪些分析", "能分析什么", "可分析方向")
    )
    quality_question = any(token in compact_question for token in ("数据质量", "缺失", "重复", "异常值", "清洗", "质量检查", "quality", "missing", "duplicate", "outlier", "clean"))
    if operation in {"dataset_overview", "multi_table_dataset_overview"} or task_type == "overview":
        return "multi_file_overview" if len(source_tables) > 1 or operation == "multi_table_dataset_overview" else "overview"
    if overview_question:
        return "multi_file_overview" if len(source_tables) > 1 else "overview"
    if operation in {"data_quality_report", "cleaning_policy", "quality_summary", "anomaly_rules", "outlier_count", "numeric_quality", "temporal_quality"}:
        return "data_quality"
    if quality_question:
        return "data_quality"
    if operation in {"ranking", "top_count", "top_k_share", "growth_ranking", "vds_current_filtered_metric_top"} or task_type == "ranking":
        if any(token in compact_question for token in ("差距", "gap", "compare", "比较")):
            return "gap"
        return "topn"
    if operation in {"aggregation", "trend", "time_series"} and any(token in compact_question for token in ("趋势", "trend", "按月", "月度", "变化")):
        return "trend"
    if _looks_like_followup(question):
        return "followup_referent"
    return "unknown"


def _required_columns(
    *,
    family: TaskFamily,
    operation: str,
    metric: str | None,
    dimension: str | None,
    output_format: dict[str, Any],
    params: dict[str, Any],
) -> list[str]:
    columns: list[str] = []
    required_metric = metric
    if str(operation or "") == "growth_ranking" and metric:
        growth_mode = str(params.get("growth_mode") or "rate")
        required_metric = f"{metric}_growth_rate" if growth_mode == "rate" else f"{metric}_growth_delta"
    for value in (dimension, required_metric, output_format.get("entity_field"), output_format.get("metric")):
        text = str(value or "").strip()
        if text and text not in columns and family in {"topn", "gap", "trend"}:
            columns.append(text)
    return columns


def _required_answer_elements(family: TaskFamily) -> list[str]:
    if family == "topn":
        return ["ranking_order", "metric_value"]
    if family == "gap":
        return ["comparison_baseline", "gap_value"]
    if family == "trend":
        return ["time_grain", "metric_series"]
    if family in {"overview", "multi_file_overview"}:
        return ["schema_summary", "analysis_directions"]
    if family == "data_quality":
        return ["quality_issue_summary", "impact_boundary"]
    if family == "followup_referent":
        return ["referent_binding"]
    return []


def _family_verification_rules(family: TaskFamily) -> dict[str, Any]:
    if family == "topn":
        return {
            "topn_required_rows": True,
            "topn_sort_order": True,
            "topn_required_columns": True,
            "topn_insufficient_explanation": True,
        }
    if family == "gap":
        return {
            "gap_absolute_required": True,
            "gap_to_leader_required": True,
            "direct_gap_summary": True,
        }
    if family == "trend":
        return {
            "trend_time_series_required": True,
            "trend_description_matches_values": True,
        }
    if family in {"overview", "multi_file_overview"}:
        return {
            "must_list_all_tables": True,
            "must_list_all_fields": True,
            "must_include_field_types": True,
            "must_include_metric_candidates": True,
            "must_include_dimension_candidates": True,
            "must_include_time_columns": True,
            "must_include_join_keys": family == "multi_file_overview",
            "must_include_analysis_directions": True,
            "must_include_quality_summary": True,
        }
    if family == "data_quality":
        return {
            "must_include_missing_by_column": True,
            "must_include_duplicate_rules": True,
            "must_include_outlier_rules": True,
            "must_include_type_parse_failures": True,
            "must_include_affected_rows": True,
            "must_include_field_level_table": True,
        }
    return {}


def _verify_topn_contract(contract: TaskExecutionContract, result: ExecutionResult) -> list[ContractViolation]:
    rows = _result_rows(result)
    violations: list[ContractViolation] = []
    if not rows:
        return violations
    metric = contract.metric or _first_numeric_column(rows, exclude={str(contract.dimension or "")})
    if metric:
        numeric_values = [value for value in (_as_float(_row_value(row, metric)) for row in rows) if value is not None]
        if len(numeric_values) >= 2:
            expected = sorted(numeric_values, reverse=str(contract.sort_order or "desc") != "asc")
            if numeric_values != expected:
                violations.append(
                    _violation(
                        "TOPN_SORT_ORDER_INVALID",
                        "TopN rows are not sorted according to the requested sort order.",
                        {"sort_order": contract.sort_order or "desc", "values": numeric_values},
                    )
                )
    return violations


def _verify_gap_contract(contract: TaskExecutionContract, result: ExecutionResult) -> list[ContractViolation]:
    rows = _result_rows(result)
    answer_text = _direct_answer_text(result)
    gap_rows = _gap_rows(rows, contract)
    violations: list[ContractViolation] = []
    minimum_required = contract.minimum_required_objects or int(contract.verification_rules.get("minimum_required_objects") or 0)
    if contract.auto_expand_topn_if_needed and minimum_required and len(gap_rows) < minimum_required:
        return []
    has_adjacent = any(_as_float(row.get("gap_from_previous")) is not None or _as_float(row.get("adjacent_gap")) is not None for row in gap_rows)
    has_to_leader = any(_as_float(row.get("gap_to_leader")) is not None for row in gap_rows)
    if not has_adjacent:
        violations.append(_violation("GAP_ADJACENT_MISSING", "Gap contract requires gap_from_previous or adjacent_gap.", {}))
    if not has_to_leader:
        violations.append(_violation("GAP_TO_LEADER_MISSING", "Gap contract requires gap_to_leader.", {}))
    if answer_text.strip() and not _answer_mentions_gap(answer_text):
        violations.append(_violation("GAP_DIRECT_SUMMARY_MISSING", "Direct answer must include a gap summary.", {}))
    return violations


def _verify_trend_contract(contract: TaskExecutionContract, result: ExecutionResult) -> list[ContractViolation]:
    rows = _result_rows(result)
    answer_text = _direct_answer_text(result)
    if not rows:
        if contract.referent_values:
            return [
                _violation(
                    "REFERENT_FILTER_EMPTY_RESULT",
                    "Trend referent filter produced no rows for the previous result objects.",
                    {
                        "referent_dimension": contract.referent_dimension,
                        "referent_values": contract.referent_values,
                    },
                )
            ]
        return [_violation("TREND_EMPTY_RESULT", "Trend contract requires at least one row for time-series analysis.", {})]

    time_dimension = _first_text(contract.time_dimension, contract.dimension)
    available_columns = _available_result_columns(result)
    if time_dimension and not _column_present(time_dimension, available_columns):
        return [_violation("TREND_TIME_COLUMN_MISSING", "Trend contract requires a time dimension column.", {"time_dimension": time_dimension})]

    metric = contract.metric or _first_numeric_column(rows, exclude={str(time_dimension or contract.dimension or "")})
    if not metric:
        return [_violation("TREND_METRIC_COLUMN_MISSING", "Trend contract requires a numeric metric column.", {})]
    if contract.metric and not _column_present(metric, available_columns):
        return [_violation("TREND_METRIC_COLUMN_MISSING", "Trend contract requires a numeric metric column.", {"metric": contract.metric})]
    if not _trend_value_column_present(result, rows, metric):
        return [_violation("TREND_METRIC_COLUMN_MISSING", "Trend contract requires a numeric metric column.", {"metric": metric})]

    if not _trend_has_time_series_artifact(result, rows):
        return [_violation("TREND_TIME_SERIES_MISSING", "Trend contract requires a complete time series artifact.", {})]

    values = [value for value in (_as_float(row.get(metric)) for row in rows) if value is not None]
    if contract.referent_values and contract.referent_dimension and str(contract.referent_dimension) in rows[0]:
        return []
    if len(values) <= 1:
        if "无法判断趋势" in answer_text or "不能判断趋势" in answer_text:
            return []
        return [_violation("TREND_SINGLE_PERIOD_EXPLANATION_MISSING", "Single-period trend output must state that trend cannot be determined.", {})]
    shape = _trend_shape(values)
    violations: list[ContractViolation] = []
    if shape in {"mixed", "up_then_down", "down_then_up"} and _claims_monotonic(answer_text):
        violations.append(
            _violation(
                "TREND_DESCRIPTION_CONTRADICTS_VALUES",
                "Non-monotonic series must not be described as overall rising or overall falling.",
                {"values": values, "shape": shape},
            )
        )
    if answer_text.strip() and shape == "up_then_down" and not _answer_mentions_up_then_down(answer_text):
        violations.append(
            _violation(
                "TREND_DESCRIPTION_MISSING_UP_THEN_DOWN",
                "Series rises then falls; the direct explanation must say 先升后降 or 波动/峰值后回落.",
                {"values": values},
            )
        )
    return violations


def _trend_value_column_present(result: ExecutionResult, rows: list[dict[str, Any]], metric: str) -> bool:
    for row in rows:
        if _as_float(_row_value(row, metric)) is not None:
            return True
    if isinstance(result.value, dict):
        candidate_table = result.value.get("candidate_table")
        if isinstance(candidate_table, list):
            for row in candidate_table:
                if isinstance(row, dict) and _as_float(_row_value(row, metric)) is not None:
                    return True
    return False


def _trend_has_time_series_artifact(result: ExecutionResult, rows: list[dict[str, Any]]) -> bool:
    if isinstance(result.value, list):
        return len(result.value) > 0
    if not isinstance(result.value, dict):
        return False
    time_series = result.value.get("time_series")
    if isinstance(time_series, list):
        return len(time_series) > 0
    if not rows:
        return False
    candidate_table = result.value.get("candidate_table")
    return isinstance(candidate_table, list) and len(candidate_table) > 0


def _verify_overview_contract(contract: TaskExecutionContract, result: ExecutionResult) -> list[ContractViolation]:
    payload = _mapping_payload(result.value)
    report = _mapping_payload(payload.get("overview_report")) or _mapping_payload(payload.get("value", {})).get("overview_report") or payload
    answer_text = _answer_text(payload, result)
    tables = _overview_tables(report)
    violations: list[ContractViolation] = []
    if contract.verification_rules.get("must_list_all_tables"):
        omitted = [table["name"] for table in tables if table["name"] and table["name"] not in answer_text]
        if omitted:
            violations.append(_violation("OVERVIEW_TABLE_OMITTED", "Overview answer omitted one or more uploaded tables.", {"omitted_tables": omitted}))
    if contract.verification_rules.get("must_list_all_fields"):
        omitted_fields: list[str] = []
        for table in tables:
            for field in table["fields"]:
                field_name = str(field.get("field") or field.get("name") or "")
                if field_name and field_name not in answer_text:
                    omitted_fields.append(f"{table['name']}.{field_name}")
        if omitted_fields:
            violations.append(_violation("OVERVIEW_FIELD_OMITTED", "Overview answer omitted one or more uploaded fields.", {"omitted_fields": omitted_fields}))
    if contract.verification_rules.get("must_include_field_types"):
        missing_type: list[str] = []
        for table in tables:
            for field in table["fields"]:
                field_name = str(field.get("field") or field.get("name") or "")
                field_type = str(field.get("type") or field.get("dtype") or "")
                if field_name and (not field_type or field_type == "unknown" or field_type not in answer_text):
                    missing_type.append(f"{table['name']}.{field_name}")
        if missing_type:
            violations.append(_violation("OVERVIEW_FIELD_TYPE_MISSING", "Overview answer did not include field types for all fields.", {"fields": missing_type}))
    if contract.verification_rules.get("must_include_join_keys"):
        join_keys = report.get("candidate_join_keys") if isinstance(report, dict) else []
        join_text = str(join_keys) + " " + answer_text
        if not join_keys or "->" not in join_text:
            violations.append(_violation("OVERVIEW_JOIN_KEY_MISSING", "Multi-file overview did not include candidate join keys.", {}))
    if contract.verification_rules.get("must_include_analysis_directions"):
        field_names = [str(field.get("field") or field.get("name") or "") for table in tables for field in table["fields"]]
        if "分析方向" not in answer_text or not any(field and field in answer_text for field in field_names):
            violations.append(_violation("OVERVIEW_ANALYSIS_DIRECTION_TOO_GENERIC", "Analysis directions must reference concrete field names.", {}))
    if contract.verification_rules.get("must_include_quality_summary") and "质量" not in answer_text:
        violations.append(_violation("QUALITY_FIELD_LEVEL_MISSING", "Overview answer must include a quality summary.", {}))
    return violations


def _verify_data_quality_contract(result: ExecutionResult) -> list[ContractViolation]:
    payload = _mapping_payload(result.value)
    quality = _mapping_payload(payload.get("quality_report")) or payload
    field_rows = quality.get("field_level_table") if isinstance(quality.get("field_level_table"), list) else []
    answer_text = _answer_text(payload, result)
    violations: list[ContractViolation] = []
    if not field_rows:
        violations.append(_violation("QUALITY_FIELD_LEVEL_MISSING", "Data quality output must include a field-level table.", {}))
    else:
        missing_columns = []
        for row in field_rows:
            item = _mapping_payload(row)
            for key in ("字段", "缺失数", "缺失率", "类型异常数", "异常值数", "检测规则"):
                if key not in item:
                    missing_columns.append(key)
        if missing_columns:
            violations.append(_violation("QUALITY_FIELD_LEVEL_MISSING", "Field-level quality table is missing required columns.", {"missing_columns": sorted(set(missing_columns))}))
    if "缺失" not in answer_text and not any("缺失" in str(row) for row in field_rows):
        violations.append(_violation("QUALITY_MISSING_RULE_MISSING", "Quality output must include missing-value rules and counts.", {}))
    if not quality.get("duplicate_rules") and "full_row_duplicate_count" not in answer_text:
        violations.append(_violation("QUALITY_DUPLICATE_RULE_MISSING", "Quality output must include duplicate rules.", {}))
    if not quality.get("outlier_rules") and "IQR" not in answer_text and "异常" not in answer_text:
        violations.append(_violation("QUALITY_OUTLIER_RULE_MISSING", "Quality output must include outlier rules.", {}))
    if not quality.get("type_parse_failure_rules") and "type parse" not in answer_text and "类型异常" not in answer_text:
        violations.append(_violation("QUALITY_OUTLIER_RULE_MISSING", "Quality output must include type parse failure rules.", {}))
    if field_rows and not all("row_count" in _mapping_payload(row) or "affected_rows" in _mapping_payload(row) for row in field_rows):
        violations.append(_violation("QUALITY_FIELD_LEVEL_MISSING", "Quality output must include row counts or affected rows.", {}))
    return violations


def _overview_tables(report: Any) -> list[dict[str, Any]]:
    payload = _mapping_payload(report)
    summaries = payload.get("tables_summary")
    if isinstance(summaries, list) and summaries:
        return [
            {
                "name": str(_mapping_payload(table).get("table") or ""),
                "fields": list(_mapping_payload(table).get("field_meanings") or []),
            }
            for table in summaries
        ]
    return [{"name": str(payload.get("table") or ""), "fields": list(payload.get("field_meanings") or [])}]


def _mapping_payload(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _answer_text(payload: dict[str, Any], result: ExecutionResult) -> str:
    parts = [str(payload.get("answer") or ""), str(result.summary or "")]
    if not parts[0] and isinstance(result.value, dict):
        parts.append(str(result.value))
    return "\n".join(parts)


def _direct_answer_text(result: ExecutionResult) -> str:
    if isinstance(result.value, dict):
        return str(result.value.get("answer") or "")
    return ""


def _violation(code: str, message: str, metadata: dict[str, Any]) -> ContractViolation:
    return ContractViolation(code=code, severity="error", message=message, correction_hint="Regenerate the response from the structured contract evidence.", metadata=metadata)


def _available_result_columns(result: ExecutionResult) -> set[str]:
    columns = {str(column) for column in result.columns or [] if str(column)}
    rows = result.rows or (result.value if isinstance(result.value, list) else [])
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                columns.update(str(key) for key in row if str(key))
    if isinstance(result.value, dict):
        columns.update(str(key) for key in result.value if str(key))
        candidate_table = result.value.get("candidate_table")
        if isinstance(candidate_table, list):
            for row in candidate_table:
                if isinstance(row, dict):
                    columns.update(str(key) for key in row if str(key))
        result_rows = result.value.get("rows")
        if isinstance(result_rows, list):
            for row in result_rows:
                if isinstance(row, dict):
                    columns.update(str(key) for key in row if str(key))
    return columns


DISPLAY_COLUMN_ALIASES = {
    "sign_amt": ("分销金额", "签收金额", "销售金额", "金额"),
    "sign_box_cnt": ("签收箱数", "箱数"),
    "cust_name": ("客户", "终端客户", "客户名称"),
    "ctg_name": ("品类", "品类名称"),
    "sku_name": ("SKU", "sku", "产品", "产品名称", "商品", "商品名称"),
    "emp_name": ("业代", "业务员", "人员"),
    "p_emp_name": ("主任",),
    "route_scope": ("线路范围",),
}


def _normalize_display_column_name(value: Any) -> str:
    return str(value).strip().lower()


def _column_present(column: str, available_columns: set[str]) -> bool:
    normalized_available = {_normalize_display_column_name(name) for name in available_columns}
    if _normalize_display_column_name(column) in normalized_available:
        return True
    aliases = DISPLAY_COLUMN_ALIASES.get(str(column), ())
    return any(_normalize_display_column_name(alias) in normalized_available for alias in aliases)


def _row_value(row: dict[str, Any], column: str) -> Any:
    normalized_row = {_normalize_display_column_name(key): key for key in row if str(key).strip()}
    if column in row:
        return row.get(column)
    direct_key = normalized_row.get(_normalize_display_column_name(column))
    if direct_key is not None:
        return row.get(direct_key)
    for alias in DISPLAY_COLUMN_ALIASES.get(str(column), ()):
        alias_key = normalized_row.get(_normalize_display_column_name(alias))
        if alias_key is not None:
            return row.get(alias_key)
    return None


def _verify_referent_result_scope(contract: TaskExecutionContract, result: ExecutionResult) -> list[ContractViolation]:
    dimension = str(contract.referent_dimension or "")
    if not dimension:
        return []
    rows = result.rows or (result.value if isinstance(result.value, list) else [])
    if not isinstance(rows, list) or not rows:
        return []
    if not all(isinstance(row, dict) for row in rows):
        return []
    if dimension not in rows[0]:
        if contract.task_family == "trend" and len(contract.referent_values) > 1:
            return [
                ContractViolation(
                    code="REFERENT_RESULT_INCOMPLETE",
                    severity="error",
                    message="Trend output for multiple previous objects must retain the object dimension.",
                    correction_hint="Group by both time and referent object, or return separate object series.",
                    metadata={"referent_dimension": dimension, "referent_values": contract.referent_values},
                )
            ]
        return []
    expected = {str(value) for value in contract.referent_values}
    observed = {str(row.get(dimension)) for row in rows if isinstance(row, dict) and row.get(dimension) not in (None, "")}
    if observed and not observed.issubset(expected):
        return [
            ContractViolation(
                code="REFERENT_FALLBACK_TO_GLOBAL",
                severity="error",
                message="Result contains objects outside the previous result referent set.",
                correction_hint="Apply the referent filter instead of falling back to global analysis.",
                metadata={"observed_values": sorted(observed), "referent_values": sorted(expected)},
            )
        ]
    if contract.task_family == "trend" and len(expected) > 1 and observed != expected:
        return [
            ContractViolation(
                code="REFERENT_RESULT_INCOMPLETE",
                severity="error",
                message="Trend result does not include every previous result object.",
                correction_hint="Return trend rows for each referent value.",
                metadata={"observed_values": sorted(observed), "referent_values": sorted(expected)},
            )
        ]
    return []


def _values_cover(filter_value: Any, referent_values: list[Any]) -> bool:
    if filter_value in (None, "", [], {}):
        return False
    expected = {str(value) for value in referent_values}
    if isinstance(filter_value, (list, tuple, set)):
        return expected.issubset({str(value) for value in filter_value})
    return expected == {str(filter_value)}


def _tabular_result_present(result: ExecutionResult) -> bool:
    return bool(result.rows) or isinstance(result.value, (list, dict))


def _row_count(result: ExecutionResult) -> int | None:
    if result.rows:
        return len(result.rows)
    if isinstance(result.value, list):
        return len(result.value)
    if isinstance(result.value, dict) and isinstance(result.value.get("candidate_table"), list):
        return len(result.value["candidate_table"])
    return None


def _result_rows(result: ExecutionResult) -> list[dict[str, Any]]:
    if result.rows:
        return [row for row in result.rows if isinstance(row, dict)]
    if isinstance(result.value, list):
        return [row for row in result.value if isinstance(row, dict)]
    if isinstance(result.value, dict):
        candidate_table = result.value.get("candidate_table")
        if isinstance(candidate_table, list):
            rows = [row for row in candidate_table if isinstance(row, dict)]
            if rows:
                return rows
        rows = result.value.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _distinct_count(result: ExecutionResult, dimension: str | None) -> int | None:
    if isinstance(result.value, dict):
        for key in ("distinct_count", "distinctCount"):
            count = _positive_int(result.value.get(key))
            if count is not None:
                return count
    rows = _result_rows(result)
    if not rows:
        return None
    if not dimension:
        return len(rows)
    values = {_row_value(row, dimension) for row in rows if _row_value(row, dimension) not in {None, ""}}
    return len(values)


def _has_explicit_topn_insufficient_explanation(answer_text: str, *, distinct_count: int, required_n: int, dimension: str) -> bool:
    compact = "".join(str(answer_text or "").split())
    normalized_dimension = str(dimension or "对象")
    return (
        f"数据集中只有{distinct_count}个不同{normalized_dimension}" in compact
        and f"无法返回Top{required_n}" in compact
        and f"只能展示Top{distinct_count}" in compact
    )


def _first_numeric_column(rows: list[dict[str, Any]], *, exclude: set[str]) -> str | None:
    if not rows:
        return None
    for key in rows[0]:
        if str(key) in exclude:
            continue
        if any(_as_float(row.get(key)) is not None for row in rows):
            return str(key)
    return None


def _gap_rows(rows: list[dict[str, Any]], contract: TaskExecutionContract) -> list[dict[str, Any]]:
    if not rows:
        return []
    if any("gap_to_leader" in row or "gap_from_previous" in row or "adjacent_gap" in row for row in rows):
        return rows
    metric = contract.metric or _first_numeric_column(rows, exclude={str(contract.dimension or "")})
    if not metric:
        return rows
    leader = _as_float(rows[0].get(metric))
    previous = leader
    gap_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        value = _as_float(row.get(metric))
        gap_row = dict(row)
        if leader is not None and value is not None:
            gap_row["gap_to_leader"] = leader - value
        if index > 0 and previous is not None and value is not None:
            gap_row["gap_from_previous"] = previous - value
            gap_row["adjacent_gap"] = previous - value
        gap_rows.append(gap_row)
        previous = value
    return gap_rows


def _answer_mentions_gap(answer_text: str) -> bool:
    lowered = str(answer_text or "").lower()
    return any(token in answer_text for token in ("差距", "相差", "差额")) or any(token in lowered for token in ("gap", "difference"))


def _trend_shape(values: list[float]) -> str:
    deltas = [values[index + 1] - values[index] for index in range(len(values) - 1)]
    positives = [delta for delta in deltas if delta > 0]
    negatives = [delta for delta in deltas if delta < 0]
    if positives and not negatives:
        return "up"
    if negatives and not positives:
        return "down"
    if len(deltas) >= 2 and deltas[0] > 0 and any(delta < 0 for delta in deltas[1:]):
        return "up_then_down"
    if len(deltas) >= 2 and deltas[0] < 0 and any(delta > 0 for delta in deltas[1:]):
        return "down_then_up"
    return "mixed"


def _claims_monotonic(answer_text: str) -> bool:
    compact = "".join(str(answer_text or "").split())
    lowered = str(answer_text or "").lower()
    return any(token in compact for token in ("整体上升", "总体上升", "持续上升", "整体下降", "总体下降", "持续下降")) or any(
        token in lowered for token in ("overall rising", "overall increasing", "overall falling", "overall decreasing", "monotonic")
    )


def _answer_mentions_up_then_down(answer_text: str) -> bool:
    compact = "".join(str(answer_text or "").split())
    lowered = str(answer_text or "").lower()
    return any(token in compact for token in ("先升后降", "波动", "峰值后回落", "达到峰值后回落", "先上升后下降")) or any(
        token in lowered for token in ("up then down", "rose then fell", "fluctuat", "peaked then fell", "peak then pullback")
    )


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_n_from_question(question: str) -> int | None:
    import re

    text = str(question or "")
    compact = "".join(text.split()).lower()
    match = re.search(r"(?:top|前|排名前|最高的?|最低的?|最大的?|最小的?|最多的?|最少的?)\s*(\d+|[一二两三四五六七八九十]+)", text, re.I)
    if not match:
        if any(token in compact for token in ("最高", "最低", "最大", "最小", "最多", "最少")) or re.search(
            r"\b(top|highest|lowest|largest|smallest|most|least)\b",
            text,
            re.I,
        ):
            return 1
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return _small_chinese_number(raw)


def _asks_lowest(question: str) -> bool:
    compact = "".join(str(question or "").split())
    lowered = str(question or "").lower()
    return any(token in compact for token in ("最低", "最小", "最少", "从低到高")) or any(
        token in lowered for token in ("lowest", "smallest", "least", "bottom", "ascending")
    )


def _asks_rank_pair(question: str) -> bool:
    import re

    compact = "".join(str(question or "").split())
    return any(token in compact for token in ("第一名和第二名", "第1名和第2名", "第一和第二")) or bool(
        re.search(r"(?:first|1st).+(?:second|2nd)", str(question or ""), re.I)
    )


def _small_chinese_number(value: str) -> int | None:
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in digits:
        return digits[value]
    if value.startswith("十") and len(value) == 2:
        return 10 + digits.get(value[1], 0)
    if value.endswith("十") and len(value) == 2:
        return digits.get(value[0], 0) * 10
    if "十" in value and len(value) == 3:
        return digits.get(value[0], 0) * 10 + digits.get(value[2], 0)
    return None


def _empty_value(value: Any, rows: list[dict[str, Any]]) -> bool:
    if rows:
        return False
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and not value:
        return True
    return False


def _looks_like_followup(question: str) -> bool:
    import re

    compact = "".join(str(question or "").split()).lower()
    if not compact:
        return False
    file_scope_tokens = (
        "这些文件",
        "这些上传文件",
        "这批数据",
        "这批客户订单收入文件",
        "上传的数据",
        "上传文件",
        "当前数据",
        "数据结构",
        "数据概览",
        "概览",
        "能支持哪些分析",
        "支持哪些分析",
        "数据质量",
        "缺失",
        "重复",
        "异常值",
    )
    previous_result_tokens = (
        "这些top",
        "这些top对象",
        "这些top城市",
        "top对象",
        "top城市",
        "上述top",
        "上述top对象",
        "上述top城市",
        "上面top",
        "刚才top",
        "这些对象",
        "上述对象",
        "这些城市",
        "上述城市",
        "这几个对象",
        "这几个城市",
        "前几个",
        "第一名",
        "第二名",
        "第1名",
        "第2名",
        "它们",
        "previous",
        "same",
    )
    if any(token in compact for token in file_scope_tokens):
        return False
    if any(token in compact for token in previous_result_tokens):
        return True
    return bool(
        re.search(r"第[一二两三四五六七八九十\d]+名", compact)
        or re.search(r"\btop\s*\d+", compact)
        or any(token in compact for token in ("刚才的结果", "上面的结果", "上一轮结果", "previousresult"))
    )


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
