"""Final response builder for stable analyze responses."""

from __future__ import annotations

import math
from dataclasses import asdict, fields, is_dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec, DataQualityReport, FinalResponse, InsightResult, ReasoningTraceStep
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import CAPABILITY_GAP, OUTPUT_CONTRACT_VALIDATION_FAILED
from data_agent_core.output.execution_artifacts import build_execution_artifacts
from data_agent_core.output.output_contract import canonicalize_final_answer
from data_agent_core.output.text_answer_framework import apply_text_answer_framework
from data_agent_core.result_artifacts import build_task_artifacts


def build_response(
    *,
    run_id: str,
    user_question: UserQuestion,
    plan: AnalysisPlan,
    execution_result: ExecutionResult,
    verification: VerificationResult,
    debug: dict[str, Any] | None = None,
    quality_report: DataQualityReport | dict[str, Any] | None = None,
    reasoning_trace_view: list[ReasoningTraceStep] | list[dict[str, Any]] | None = None,
) -> FinalResponse:
    """Build a FinalResponse with stable fields and formatted answer."""

    canonical_answer = canonicalize_final_answer(execution_result.value, plan.logic_form.output_format)
    answer = canonical_answer.answer
    semantic_failure_answer = _semantic_failure_answer(user_question, plan, verification)
    if semantic_failure_answer is not None:
        answer = semantic_failure_answer
    display_result = {"columns": execution_result.columns, "rows": execution_result.rows, "value": execution_result.value}
    ranking_display_answer = _vds_current_metric_top_answer(plan, execution_result)
    if semantic_failure_answer is None and ranking_display_answer is not None:
        answer = ranking_display_answer
    overview_display = _overview_display_payload(user_question.question, plan, execution_result)
    if semantic_failure_answer is None and overview_display is not None:
        answer = overview_display["answer"]
        display_result = {
            "columns": overview_display["columns"],
            "rows": overview_display["rows"],
            "value": overview_display["value"],
        }
    display_result = _attach_display_rows(
        display_result,
        output_format=plan.logic_form.output_format,
    )
    display_result = _attach_derived_metric_metadata_to_display_rows(display_result, plan)
    if semantic_failure_answer is None:
        answer = _referent_answer_prefix(verification) + answer
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
    if ranking_display_answer is not None:
        debug_payload["user_experience_shaping"] = {
            "applied": True,
            "reason": "vds_current_metric_top_answer_summary",
            "operation": plan.logic_form.operation,
        }
    if overview_display is not None:
        debug_payload["user_experience_shaping"] = {
            "applied": True,
            "reason": "overview_question_prevents_raw_detail_answer",
            "source_row_count": overview_display["source_row_count"],
            "source_column_count": overview_display["source_column_count"],
            "metric_column": overview_display["metric_column"],
            "dimension_column": overview_display["dimension_column"],
        }
    debug_payload["output_contract_validation"] = canonical_answer.validation.to_dict()
    debug_payload["canonical_answer"] = {
        "normalized_from": canonical_answer.normalized_from,
        "answer_type": canonical_answer.validation.answer_type,
    }
    referent_prefix = _referent_answer_prefix(verification)
    if referent_prefix:
        debug_payload["referent_answer_prefix"] = referent_prefix
    semantic_status = str(getattr(verification, "semantic_status", None) or "legacy_unverified")
    contract_report = getattr(verification, "contract_report", None) if isinstance(getattr(verification, "contract_report", None), dict) else None
    task_contract = getattr(verification, "task_contract", None) if isinstance(getattr(verification, "task_contract", None), dict) else None
    oracle_result = getattr(verification, "oracle_result", None) if isinstance(getattr(verification, "oracle_result", None), dict) else None
    contract_satisfied = contract_report.get("passed") if isinstance(contract_report, dict) else None
    violations = list(contract_report.get("violations") or []) if isinstance(contract_report, dict) else []
    contract_family = ""
    if isinstance(task_contract, dict):
        contract_family = str(task_contract.get("task_family") or "")
    if not contract_family and isinstance(contract_report, dict):
        contract_family = str(contract_report.get("task_family") or "")
    trend_empty_answer = _trend_empty_answer(task_contract, plan, execution_result)
    if semantic_failure_answer is None and trend_empty_answer:
        answer = trend_empty_answer
    insufficient_answer = _topn_insufficient_answer(task_contract, execution_result, semantic_status)
    if insufficient_answer:
        answer = insufficient_answer
    debug_payload["semantic_status"] = semantic_status
    debug_payload["task_contract"] = task_contract
    debug_payload["contract_report"] = contract_report
    debug_payload["oracle_result"] = oracle_result
    result_artifacts = build_task_artifacts(
        task_contract=task_contract or {},
        rows=_artifact_rows(execution_result),
        answer=str(answer or ""),
    )
    if result_artifacts:
        debug_payload["result_artifacts"] = result_artifacts
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
    response_quality_report = quality_report
    if response_quality_report is None and plan.logic_form.operation == "data_quality_report" and isinstance(execution_result.value, dict):
        response_quality_report = execution_result.value
    if response_quality_report is None and isinstance(execution_result.debug, dict) and isinstance(execution_result.debug.get("quality_report"), dict):
        response_quality_report = execution_result.debug.get("quality_report")
    response = FinalResponse(
        response_version="v1",
        success=success,
        run_id=run_id,
        dataset_id=user_question.dataset_id,
        question=user_question.question,
        answer_type=str(plan.logic_form.output_format.get("answer_type", "text")),
        execution_mode=user_question.execution_mode,
        answer=answer,
        logic_form=_to_dict(plan.logic_form),
        result=display_result,
        verification=_to_dict(verification),
        insight=InsightResult(summary=answer if success else ""),
        chart=ChartSpec(),
        quality_report=response_quality_report,
        reasoning_trace_view=reasoning_trace_view or [],
        execution_artifacts=build_execution_artifacts(
            plan=plan,
            execution_result=execution_result,
            verification_passed=success,
        ),
        artifacts_manifest={"result_artifacts": result_artifacts} if result_artifacts else {},
        semantic_status=semantic_status,
        contract_satisfied=contract_satisfied,
        contract_family=contract_family or None,
        violations=violations,
        oracle_result=oracle_result,
        warnings=warnings,
        errors=errors,
        debug=debug_payload,
    )
    return _apply_structured_answer_framework(response)


def format_answer(value: Any, output_format: dict[str, Any]) -> str:
    """Format a raw execution value according to benchmark/API guidelines."""

    return canonicalize_final_answer(value, output_format).answer


def _artifact_rows(execution_result: ExecutionResult) -> list[dict[str, Any]]:
    if execution_result.rows:
        return [row for row in execution_result.rows if isinstance(row, dict)]
    if isinstance(execution_result.value, list):
        return [row for row in execution_result.value if isinstance(row, dict)]
    if isinstance(execution_result.value, dict):
        candidate_table = execution_result.value.get("candidate_table")
        if isinstance(candidate_table, list):
            return [row for row in candidate_table if isinstance(row, dict)]
        rows = execution_result.value.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _attach_derived_metric_metadata_to_display_rows(display_result: dict[str, Any], plan: AnalysisPlan) -> dict[str, Any]:
    metadata = _derived_metric_metadata_from_plan(plan)
    if not metadata:
        return display_result
    metric_name = str(metadata.get("derived_metric_name") or "").strip()
    if metric_name and not metric_name.isascii():
        return display_result
    rows = display_result.get("rows")
    if isinstance(rows, list):
        display_result = dict(display_result)
        display_result["rows"] = [
            {**row, **metadata} if isinstance(row, dict) else row
            for row in rows
        ]
    return display_result


def _derived_metric_metadata_from_plan(plan: AnalysisPlan) -> dict[str, str]:
    params = dict(getattr(plan.logic_form, "parameters", {}) or {})
    task_contract = getattr(plan, "task_contract", None)
    if isinstance(task_contract, dict):
        params = {**params, **{key: task_contract.get(key) for key in ("derived_metric_name", "metric_formula", "numerator_column", "denominator_column") if task_contract.get(key)}}
    derived = params.get("derived_metric") if isinstance(params.get("derived_metric"), dict) else {}
    name = str(params.get("derived_metric_name") or derived.get("name") or "").strip()
    numerator = str(params.get("numerator_column") or derived.get("numerator") or "").strip()
    denominator = str(params.get("denominator_column") or derived.get("denominator") or "").strip()
    formula = str(params.get("metric_formula") or derived.get("formula") or "").strip()
    if not formula and numerator and denominator:
        formula = f"sum({numerator})/sum({denominator})"
    return {
        key: value
        for key, value in {
            "derived_metric_name": name,
            "metric_formula": formula,
            "numerator_column": numerator,
            "denominator_column": denominator,
        }.items()
        if value
    }


def _topn_insufficient_answer(task_contract: dict[str, Any] | None, execution_result: ExecutionResult, semantic_status: str) -> str:
    if semantic_status not in {"passed_with_insufficient_data", "partial"} or not isinstance(task_contract, dict):
        return ""
    if str(task_contract.get("task_family") or "") != "topn":
        return ""
    required_n = _int_or_none(task_contract.get("required_n"))
    dimension = str(task_contract.get("dimension") or "对象")
    rows = _artifact_rows(execution_result)
    if not required_n:
        return ""
    if not rows:
        metric = str(task_contract.get("metric") or "指标")
        dimension_label = _display_dimension_label(dimension)
        dimension_text = _dimension_label_with_field(dimension_label, dimension)
        metric_label = _display_metric_label(metric)
        return f"当前结果没有返回可用于 Top {required_n} 的{dimension_text}排名；按当前筛选条件没有匹配的{metric_label}记录，因此无法列出前 {required_n} 个{dimension_text}。"
    distinct_count = _int_or_none(execution_result.value.get("distinct_count")) if isinstance(execution_result.value, dict) else None
    if distinct_count is None:
        distinct_count = len({row.get(dimension) for row in rows if row.get(dimension) not in {None, ""}}) if dimension else len(rows)
    if distinct_count >= required_n:
        return ""
    metric = str(task_contract.get("metric") or _first_numeric_column(rows, exclude={dimension}) or "指标")
    dimension_label = _display_dimension_label(dimension)
    dimension_text = _dimension_label_with_field(dimension_label, dimension)
    metric_label = _display_metric_label(metric)
    items = []
    for row in rows[:distinct_count]:
        label = row.get(dimension)
        value = row.get(metric)
        if label in {None, ""} or value in {None, ""}:
            continue
        items.append(f"{label} {_format_display_number(value)}")
    suffix = "：" + "、".join(items) if items else ""
    return f"按{dimension_text}统计{metric_label}，当前只有 {distinct_count} 个{dimension_text}，无法返回 Top {required_n}，因此返回 Top {distinct_count}{suffix}。"


def _trend_empty_answer(task_contract: dict[str, Any] | None, plan: AnalysisPlan, execution_result: ExecutionResult) -> str:
    if not isinstance(task_contract, dict) or str(task_contract.get("task_family") or "") != "trend":
        return ""
    if _artifact_rows(execution_result):
        return ""
    metric = str(task_contract.get("metric") or plan.logic_form.parameters.get("metric") or plan.logic_form.metric or "指标")
    time_dimension = str(task_contract.get("time_dimension") or task_contract.get("dimension") or plan.logic_form.parameters.get("dimension") or "时间")
    filters = plan.logic_form.filters or {}
    scope_parts = []
    for key, value in filters.items():
        if value in (None, "", [], {}):
            continue
        scope_parts.append(f"{key}={value}")
    scope = "，筛选范围：" + "；".join(scope_parts) if scope_parts else ""
    return f"当前没有匹配的{time_dimension}趋势结果，无法判断{metric}趋势变化{scope}。"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_numeric_column(rows: list[dict[str, Any]], *, exclude: set[str] | None = None) -> str | None:
    excluded = {item for item in (exclude or set()) if item}
    for row in rows:
        for key, value in row.items():
            if key in excluded:
                continue
            if _to_float(value) is not None:
                return str(key)
    return None


def _display_dimension_label(value: str) -> str:
    lowered = str(value or "").lower()
    if "city" in lowered or "城市" in lowered:
        return "城市"
    if "customer" in lowered or "客户" in lowered:
        return "客户"
    return str(value or "对象")


def _dimension_label_with_field(label: str, field: str) -> str:
    raw_field = str(field or "").strip()
    if not raw_field or raw_field == label:
        return label
    if raw_field.lower().endswith("_id") or "id" in raw_field.lower():
        return f"{label}（{raw_field}）"
    return label


def _display_metric_label(value: str) -> str:
    lowered = str(value or "").lower()
    if "order_amount" in lowered:
        return "订单金额"
    if "amount" in lowered or "金额" in lowered:
        return "金额"
    return str(value or "指标")


def _semantic_failure_answer(user_question: UserQuestion, plan: AnalysisPlan, verification: VerificationResult) -> str | None:
    if verification.passed:
        return None
    contract_report = verification.contract_report if isinstance(verification.contract_report, dict) else {}
    violation_codes = {str(item.get("code") or "") for item in contract_report.get("violations") or [] if isinstance(item, dict)}
    if "REFERENT_ARTIFACT_MISSING" in violation_codes:
        return "这个追问依赖上一轮结果对象，但当前对话里没有可引用的 Top/ranking 结果 artifact。请先说明要分析哪些对象，或先跑一轮 Top 排名。"
    if "REFERENT_VALUES_MISSING" in violation_codes:
        return "这个追问依赖上一轮结果对象，但上一轮 artifact 中没有可用对象集合。请明确要分析的对象范围。"
    action = verification.correction_action if isinstance(verification.correction_action, dict) else {}
    action_name = str(action.get("action") or "")
    if action_name not in {"clarify_join_key", "repair_table_selection_or_join", "repair_dimension_binding", "repair_metric_definition"}:
        return None
    logic = plan.logic_form
    params = logic.parameters or {}
    join_plan = logic.join_plan or params.get("join_plan") or {}
    if action_name in {"clarify_join_key", "repair_table_selection_or_join"}:
        target_dimension = (
            params.get("dimension")
            or params.get("group_by")
            or logic.group_by
            or "、".join(str(item) for item in action.get("requested_dimensions") or [])
        )
        dimension_label = _semantic_dimension_label(str(target_dimension or "目标维度"))
        metric_label = str(params.get("metric") or logic.metric or "目标指标")
        reason = str(action.get("reason") or "")
        if isinstance(join_plan, dict) and join_plan:
            left_table = str(join_plan.get("left_table") or params.get("table") or "左表")
            right_table = str(join_plan.get("right_table") or "右表")
            left_key = str(join_plan.get("left_key") or "待确认字段")
            right_key = str(join_plan.get("right_key") or "待确认字段")
            reason = str(join_plan.get("reason") or reason)
            overlap = join_plan.get("overlap_rate")
            risk = "，且存在多对多风险" if join_plan.get("many_to_many_risk") else ""
            overlap_text = f"，当前键值重叠率约 {float(overlap):.0%}" if isinstance(overlap, (int, float)) else ""
            reason_text = f"；原因是 {reason}" if reason else ""
            guard_text = "我已拦截这次低可信自动关联，避免把跨表数据误算成已验证结果。"
            return (
                f"这个问题需要先确认跨表关联，不能直接把单表结果当成{dimension_label}口径。"
                f"{guard_text}"
                f"建议检查关联键：{left_table}.{left_key} -> {right_table}.{right_key}{overlap_text}{risk}{reason_text}。"
                f"确认后我才能按{dimension_label}汇总或排名{metric_label}。"
            )
        source_tables = list(logic.source_tables or params.get("source_tables") or action.get("source_tables") or [])
        source_text = "、".join(str(item) for item in source_tables if str(item)) or "相关表"
        actual_dimension = str(action.get("actual_dimension") or params.get("dimension") or logic.group_by or "")
        actual_text = f"当前计划绑定到 {actual_dimension}，" if actual_dimension else ""
        reason_text = f"原因是 {reason}，" if reason else ""
        return (
            f"这个问题需要{source_text}之间的可信关联，{actual_text}{reason_text}"
            f"不能直接把结果当成{dimension_label}口径。我已拦截这次低可信自动关联，避免误算。"
            f"请先确认关联键或选择包含{dimension_label}字段的数据表，"
            f"确认后我才能按{dimension_label}汇总或排名{metric_label}。"
        )
    if action_name == "repair_dimension_binding":
        requested = "、".join(str(item) for item in action.get("requested_dimensions") or []) or "用户点名维度"
        actual = str(action.get("actual_dimension") or params.get("dimension") or "")
        if action.get("missing_dimension"):
            requested_label = _semantic_dimension_label(requested)
            available = [str(item) for item in action.get("available_columns") or [] if str(item)]
            available_text = "；当前可用字段包括：" + "、".join(available[:8]) if available else ""
            return f"当前上传表结构里没有可用于“{requested_label}”的字段，不能把其他字段替代成该口径来回答{available_text}。"
        requested_label = _semantic_dimension_label(requested)
        actual_label = _semantic_dimension_label(actual) if actual else "其他维度"
        return f"这个问题点名要按 {requested_label} 分析，但当前计划绑定到了 {actual_label}，所以不能把这个结果标记为成功。"
    if action_name == "repair_metric_definition":
        if "利润率" in user_question.question or "margin" in user_question.question.lower():
            return "这个问题问的是利润率，必须按 profit / sales 这类分子/分母口径计算；当前计划没有可靠的派生指标口径，所以不能用销售额或利润额直接排名。"
    return None


def _referent_answer_prefix(verification: VerificationResult) -> str:
    task_contract = verification.task_contract if isinstance(verification.task_contract, dict) else {}
    if not task_contract.get("requires_previous_artifact"):
        return ""
    if task_contract.get("auto_expand_topn_if_needed"):
        return ""
    values = [str(value) for value in task_contract.get("referent_values") or [] if str(value)]
    if not values:
        return ""
    label = _semantic_dimension_label(str(task_contract.get("referent_dimension") or ""))
    if len(values) == 1:
        if label:
            return f"这里的 Top 对象来自上一轮结果，仅包含{values[0]}一个{label}；如果要比较多个对象，需要先把上一轮排名扩大为 TopN。"
        return f"这里的 Top 对象来自上一轮结果，仅包含{values[0]}；如果要比较多个对象，需要先把上一轮排名扩大为 TopN。"
    joined = "、".join(values[:10])
    suffix = "等" if len(values) > 10 else ""
    return f"本次分析对象来自上一轮 Top 结果，共 {len(values)} 个{label or '对象'}：{joined}{suffix}。"


def _semantic_dimension_label(value: str) -> str:
    labels = {
        "product": "产品",
        "category": "品类",
        "store": "门店",
        "city": "城市",
        "channel": "渠道",
        "customer": "客户",
        "month": "月份",
        "time": "时间",
    }
    alias_labels = (
        ("channel", "渠道"),
        ("渠道", "渠道"),
        ("category", "品类"),
        ("ctg", "品类"),
        ("品类", "品类"),
        ("类目", "品类"),
        ("month", "月份"),
        ("月份", "月份"),
        ("月度", "月份"),
        ("statmonth", "月份"),
        ("yearmonth", "月份"),
    )
    parts: list[str] = []
    for raw in value.split("、"):
        item = raw.strip()
        if not item:
            continue
        if item in labels:
            parts.append(labels[item])
            continue
        normalized = "".join(char for char in item.lower() if char.isalnum() or "\u4e00" <= char <= "\u9fff")
        parts.append(next((label for token, label in alias_labels if token in normalized), item))
    return "、".join(parts) if parts else value


def _vds_current_metric_top_answer(plan: AnalysisPlan, execution_result: ExecutionResult) -> str | None:
    logic = plan.logic_form
    if logic.operation != "vds_current_filtered_metric_top":
        return None
    rows = _result_rows(execution_result)
    if not rows:
        return None
    params = logic.parameters
    entity = str(params.get("entity") or logic.group_by or logic.output_format.get("entity_field") or "")
    metric = str(params.get("metric") or logic.metric or logic.output_format.get("metric") or "")
    if not entity or not metric or entity not in rows[0] or metric not in rows[0]:
        return None
    row_answers = [str(row.get("answer")).strip() for row in rows if row.get("answer")]
    if row_answers:
        return "；".join(row_answers)
    top_row = rows[0]
    period = str(params.get("current_period") or "本周")
    direction = "最低" if str(params.get("sort_order") or "desc") == "asc" else "最高"
    entity_label = entity.replace("名称", "")
    metric_label = metric[:-4] if metric.endswith("_row") else metric
    filter_phrase = _value_filters_phrase(params.get("value_filters") or {})
    top_value = _to_float(top_row.get(metric))
    value_text = _format_display_number(top_value) if top_value is not None else str(top_row.get(metric))
    row_count = len(rows)
    return (
        f"{period}{filter_phrase}{entity_label}中，{metric_label} {direction}的是"
        f"{top_row.get(entity)}（{metric_label}={value_text}）。"
        f"下表列出本次可返回的 Top{row_count}。"
    )


def _value_filters_phrase(filters: Any) -> str:
    if not isinstance(filters, dict) or not filters:
        return ""
    parts: list[str] = []
    for column, raw_values in filters.items():
        values = list(raw_values) if isinstance(raw_values, (list, tuple, set)) else [raw_values]
        values = [str(value) for value in values if str(value)]
        if values:
            parts.append(f"{column}为{'/'.join(values)}")
    return "" if not parts else "、".join(parts) + "的"


def _overview_display_payload(question: str, plan: AnalysisPlan, execution_result: ExecutionResult) -> dict[str, Any] | None:
    if not execution_result.success:
        return None
    rows = _result_rows(execution_result)
    if not rows or not _looks_like_overview_question(question):
        return None
    source_columns = list(execution_result.columns or rows[0].keys())
    if len(rows) < 2 or len(source_columns) < 4:
        return None
    metric_column = _preferred_metric_column(rows, source_columns, question)
    if not metric_column:
        return None
    values = [_to_float(row.get(metric_column)) for row in rows]
    numeric_values = [value for value in values if value is not None]
    if not numeric_values:
        return None
    dimension_column = _preferred_dimension_column(source_columns)
    period_column = _preferred_period_column(source_columns)
    total = sum(numeric_values)
    average = total / len(numeric_values)
    max_row = max((row for row in rows if _to_float(row.get(metric_column)) is not None), key=lambda row: _to_float(row.get(metric_column)) or 0)
    min_row = min((row for row in rows if _to_float(row.get(metric_column)) is not None), key=lambda row: _to_float(row.get(metric_column)) or 0)
    overview_rows = _field_overview_rows(rows, source_columns, metric_column=metric_column, dimension_column=dimension_column, period_column=period_column)
    period_phrase = f"，覆盖 {len({str(row.get(period_column)) for row in rows if row.get(period_column) not in {None, ''}})} 个{period_column}" if period_column else ""
    dimension_phrase = f"，可继续按{dimension_column}下钻" if dimension_column else ""
    answer = (
        f"整体来看，共有 {len(rows)} 条记录、{len(source_columns)} 个字段{period_phrase}。"
        f"{metric_column}合计 {_format_display_number(total)}，平均 {_format_display_number(average)}；"
        f"最高值为 {_describe_row_metric(max_row, metric_column, dimension_column, period_column)}，"
        f"最低值为 {_describe_row_metric(min_row, metric_column, dimension_column, period_column)}"
        f"{dimension_phrase}。字段清单和类型见下表。"
    )
    return {
        "answer": answer,
        "columns": ["字段", "类型", "角色", "样例"],
        "rows": overview_rows,
        "value": {
            "row_count": len(rows),
            "column_count": len(source_columns),
            "metric_column": metric_column,
            "metric_total": total,
            "metric_average": average,
        },
        "source_row_count": len(rows),
        "source_column_count": len(source_columns),
        "metric_column": metric_column,
        "dimension_column": dimension_column,
    }


def _field_overview_rows(
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    metric_column: str,
    dimension_column: str | None,
    period_column: str | None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for column in columns:
        role = "指标" if column == metric_column else "维度" if column == dimension_column else "时间" if column == period_column else "字段"
        sample = next((row.get(column) for row in rows if row.get(column) not in {None, ""}), "")
        output.append(
            {
                "字段": column,
                "类型": _display_column_type(rows, column),
                "角色": role,
                "样例": sample,
            }
        )
    return output


def _display_column_type(rows: list[dict[str, Any]], column: str) -> str:
    if _numeric_ratio(rows, column) >= 0.75:
        return "number"
    lowered = column.lower()
    if any(token in lowered for token in ("date", "month", "time", "日期", "月份", "时间")):
        return "date/time"
    return "text"


def _result_rows(execution_result: ExecutionResult) -> list[dict[str, Any]]:
    if execution_result.rows:
        return [row for row in execution_result.rows if isinstance(row, dict)]
    value = execution_result.value
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return []


def _attach_display_rows(result: dict[str, Any], *, output_format: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("rows")
    columns = result.get("columns")
    if not isinstance(rows, list) or not rows or not isinstance(columns, list):
        return result
    result["display_rows"] = [
        {column: _format_display_cell(column, row.get(column), output_format) for column in columns}
        for row in rows
        if isinstance(row, dict)
    ]
    return result


def _format_display_cell(column: str, value: Any, output_format: dict[str, Any]) -> Any:
    number = _to_float(value)
    if number is None:
        return value
    if _looks_like_integer_display_column(column):
        return f"{int(round(number)):,}"
    decimals = int(output_format.get("decimals") or 2)
    if _looks_like_rate_display_column(column):
        return f"{number:,.{decimals}f}%"
    if math.isclose(number, round(number)) and not _looks_like_amount_display_column(column):
        return f"{int(round(number)):,}"
    return f"{number:,.{decimals}f}"


def _looks_like_integer_display_column(column: str) -> bool:
    lowered = column.lower()
    return any(
        token in lowered
        for token in ("year", "month", "day", "hour", "minute", "日期", "月份", "年", "数量", "次数", "记录数", "count", "行数")
    ) and not _looks_like_amount_display_column(column)


def _looks_like_rate_display_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("rate", "ratio", "share", "percent", "%", "达成率", "完成率", "占比", "比例"))


def _looks_like_amount_display_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("金额", "销售额", "收入", "利润", "target", "actual", "amount", "revenue", "sales", "fee"))


def _looks_like_overview_question(question: str) -> bool:
    text = question.lower()
    compact = text.replace(" ", "")
    overview_tokens = (
        "整体",
        "总体",
        "概览",
        "总览",
        "情况",
        "看一下",
        "看下",
        "看看",
        "分析一下",
        "主要讲什么",
        "讲什么",
        "主要内容",
        "什么意思",
        "字段含义",
        "有什么字段",
        "有哪些字段",
        "overview",
        "summary",
        "summarize",
        "overall",
        "look at",
    )
    subject_tokens = ("数据", "这个表", "文件", "销售", "收入", "订单", "订阅", "业绩", "经营", "sales", "revenue", "amount", "business", "dataset", "table")
    specific_tokens = ("哪个", "最高", "最低", "top", "排名", "多少", "占比", "增长", "对比", "趋势", "按", "筛选", "列出", "质量", "空值", "重复")
    return any(token in text for token in overview_tokens) and any(token in compact or token in text for token in subject_tokens) and not any(token in compact for token in specific_tokens)


def _preferred_metric_column(rows: list[dict[str, Any]], columns: list[str], question: str) -> str | None:
    lowered_question = question.lower()
    preferred = [
        "销售额",
        "订阅收入",
        "收入",
        "订单金额",
        "金额",
        "销售",
        "ARR_row",
        "毛利",
        "利润",
        "sales",
        "revenue",
        "amount",
        "gmv",
        "arr",
    ]
    numeric_columns = [column for column in columns if _numeric_ratio(rows, column) >= 0.75 and not _looks_like_identifier_column(column)]
    for token in preferred:
        for column in numeric_columns:
            if token.lower() in column.lower() or column.lower() in lowered_question:
                return column
    return numeric_columns[0] if numeric_columns else None


def _looks_like_identifier_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("id", "code", "invoice", "reference", "ref", "number", "stock", "customer", "编号", "编码", "序号"))


def _preferred_dimension_column(columns: list[str]) -> str | None:
    preferred = ("区域", "城市", "获客渠道", "渠道", "产品线", "套餐名称", "客户类型", "category", "city", "region", "channel", "product")
    for token in preferred:
        for column in columns:
            if token.lower() in column.lower():
                return column
    return None


def _preferred_period_column(columns: list[str]) -> str | None:
    preferred = ("月份", "周标签", "日期", "周序号", "month", "week", "date")
    for token in preferred:
        for column in columns:
            if token.lower() in column.lower():
                return column
    return None


def _numeric_ratio(rows: list[dict[str, Any]], column: str) -> float:
    values = [row.get(column) for row in rows if row.get(column) not in {None, ""}]
    if not values:
        return 0.0
    numeric = sum(1 for value in values if _to_float(value) is not None)
    return numeric / len(values)


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _format_display_number(value: float) -> str:
    if math.isclose(value, round(value)):
        return f"{int(round(value)):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _describe_row_metric(row: dict[str, Any], metric_column: str, dimension_column: str | None, period_column: str | None) -> str:
    parts = []
    if dimension_column and row.get(dimension_column) not in {None, ""}:
        parts.append(str(row.get(dimension_column)))
    if period_column and row.get(period_column) not in {None, ""}:
        parts.append(str(row.get(period_column)))
    prefix = " / ".join(parts)
    value = _to_float(row.get(metric_column)) or 0.0
    formatted = _format_display_number(value)
    return f"{prefix}：{formatted}" if prefix else formatted


def _top_group(rows: list[dict[str, Any]], dimension_column: str, metric_column: str) -> str | None:
    totals: dict[str, float] = {}
    for row in rows:
        dimension = row.get(dimension_column)
        value = _to_float(row.get(metric_column))
        if dimension in {None, ""} or value is None:
            continue
        key = str(dimension)
        totals[key] = totals.get(key, 0.0) + value
    if not totals:
        return None
    key, value = max(totals.items(), key=lambda item: item[1])
    return f"{key}：{_format_display_number(value)}"


def classify_not_applicable(value: Any, plan: AnalysisPlan) -> dict[str, Any]:
    """Classify Not Applicable as true unsupported or a capability gap."""

    if not _is_not_applicable_value(value):
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


def _is_not_applicable_value(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        return text in {"not applicable", "n/a", "na"} or "not applicable" in text
    if isinstance(value, dict):
        for key in ("answer", "value", "result"):
            if key in value and _is_not_applicable_value(value[key]):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_is_not_applicable_value(item) for item in value)
    return False


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
        return "没有匹配记录"
    group_key = next(key for key in rows[0] if key != "eur_amount")
    parts = [f"{row[group_key]}: {_format_number(float(row['eur_amount']), decimals)}" for row in rows]
    return "[" + ", ".join(parts) + "]"


def _apply_structured_answer_framework(response: FinalResponse) -> FinalResponse:
    """Attach the shared sectioned answer frame without changing result payloads."""

    referent_prefix = ""
    if isinstance(response.debug, dict):
        referent_prefix = str(response.debug.get("referent_answer_prefix") or "")
    try:
        payload = apply_text_answer_framework(response.to_dict(), question=response.question)
    except Exception:  # noqa: BLE001 - final response construction must stay stable.
        return response
    response.answer = payload.get("answer", response.answer)
    if referent_prefix and not str(response.answer).startswith(referent_prefix):
        if _should_append_referent_prefix(response):
            response.answer = str(response.answer) + referent_prefix
        else:
            response.answer = referent_prefix + str(response.answer)
    response.debug = payload.get("debug", response.debug)
    sections = payload.get("structured_answer_sections")
    if isinstance(sections, dict):
        response.structured_answer_sections = {
            str(key): [str(item) for item in value if str(item or "").strip()]
            for key, value in sections.items()
            if isinstance(value, list)
        }
    insight_payload = payload.get("insight")
    if isinstance(insight_payload, dict):
        allowed = {field.name for field in fields(InsightResult)}
        response.insight = InsightResult(**{key: value for key, value in insight_payload.items() if key in allowed})
    return response


def _should_append_referent_prefix(response: FinalResponse) -> bool:
    if not isinstance(response.debug, dict):
        return False
    task_contract = response.debug.get("task_contract")
    if not isinstance(task_contract, dict):
        return False
    return bool(
        task_contract.get("requires_previous_artifact")
        and str(task_contract.get("task_family") or "") == "trend"
    )


def _to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value
