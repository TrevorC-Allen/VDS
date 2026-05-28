"""Final response builder for stable analyze responses."""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
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
        result=display_result,
        verification=_to_dict(verification),
        insight=InsightResult(summary=answer if success else ""),
        chart=ChartSpec(),
        quality_report=quality_report,
        reasoning_trace_view=reasoning_trace_view or [],
        execution_artifacts=build_execution_artifacts(
            plan=plan,
            execution_result=execution_result,
            verification_passed=success,
        ),
        warnings=warnings,
        errors=errors,
        debug=debug_payload,
    )


def format_answer(value: Any, output_format: dict[str, Any]) -> str:
    """Format a raw execution value according to benchmark/API guidelines."""

    return canonicalize_final_answer(value, output_format).answer


def _semantic_failure_answer(user_question: UserQuestion, plan: AnalysisPlan, verification: VerificationResult) -> str | None:
    if verification.passed:
        return None
    action = verification.correction_action if isinstance(verification.correction_action, dict) else {}
    action_name = str(action.get("action") or "")
    if action_name not in {"clarify_join_key", "repair_table_selection_or_join", "repair_dimension_binding", "repair_metric_definition"}:
        return None
    logic = plan.logic_form
    params = logic.parameters or {}
    join_plan = logic.join_plan or params.get("join_plan") or {}
    if isinstance(join_plan, dict) and join_plan and action_name in {"clarify_join_key", "repair_table_selection_or_join"}:
        left_table = str(join_plan.get("left_table") or params.get("table") or "左表")
        right_table = str(join_plan.get("right_table") or "右表")
        left_key = str(join_plan.get("left_key") or "待确认字段")
        right_key = str(join_plan.get("right_key") or "待确认字段")
        reason = str(join_plan.get("reason") or action.get("reason") or "")
        overlap = join_plan.get("overlap_rate")
        risk = "，且存在多对多风险" if join_plan.get("many_to_many_risk") else ""
        overlap_text = f"，当前键值重叠率约 {float(overlap):.0%}" if isinstance(overlap, (int, float)) else ""
        reason_text = f"；原因是 {reason}" if reason else ""
        return (
            "这个问题需要先确认跨表关联，不能直接把单表结果当成城市口径。"
            f"建议检查关联键：{left_table}.{left_key} -> {right_table}.{right_key}{overlap_text}{risk}{reason_text}。"
            "确认后我才能按城市汇总销售额。"
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
    parts = [labels.get(item.strip(), item.strip()) for item in value.split("、") if item.strip()]
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
    overview_rows = [
        {"指标": "记录数", "数值": str(len(rows))},
        {"指标": f"{metric_column}合计", "数值": _format_display_number(total)},
        {"指标": f"{metric_column}平均", "数值": _format_display_number(average)},
        {"指标": f"{metric_column}最高", "数值": _describe_row_metric(max_row, metric_column, dimension_column, period_column)},
        {"指标": f"{metric_column}最低", "数值": _describe_row_metric(min_row, metric_column, dimension_column, period_column)},
    ]
    if dimension_column:
        top_dimension = _top_group(rows, dimension_column, metric_column)
        if top_dimension is not None:
            overview_rows.append({"指标": f"最高{dimension_column}", "数值": top_dimension})
    period_phrase = f"，覆盖 {len({str(row.get(period_column)) for row in rows if row.get(period_column) not in {None, ''}})} 个{period_column}" if period_column else ""
    dimension_phrase = f"，可继续按{dimension_column}下钻" if dimension_column else ""
    answer = (
        f"整体来看，共有 {len(rows)} 条记录{period_phrase}。"
        f"{metric_column}合计 {_format_display_number(total)}，平均 {_format_display_number(average)}；"
        f"最高值为 {_describe_row_metric(max_row, metric_column, dimension_column, period_column)}，"
        f"最低值为 {_describe_row_metric(min_row, metric_column, dimension_column, period_column)}"
        f"{dimension_phrase}。"
    )
    return {
        "answer": answer,
        "columns": ["指标", "数值"],
        "rows": overview_rows,
        "value": {
            "row_count": len(rows),
            "metric_column": metric_column,
            "metric_total": total,
            "metric_average": average,
        },
        "source_row_count": len(rows),
        "source_column_count": len(source_columns),
        "metric_column": metric_column,
        "dimension_column": dimension_column,
    }


def _result_rows(execution_result: ExecutionResult) -> list[dict[str, Any]]:
    if execution_result.rows:
        return [row for row in execution_result.rows if isinstance(row, dict)]
    value = execution_result.value
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return []


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


def _to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value
