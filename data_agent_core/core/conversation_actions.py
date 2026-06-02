"""Structured conversation context and follow-up action helpers."""

from __future__ import annotations

import re
from typing import Any, Mapping

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.core.capability_registry import capability_for_operation


def build_analysis_context(
    response: Mapping[str, Any] | None,
    *,
    previous_context: Mapping[str, Any] | None = None,
    original_question: str = "",
) -> dict[str, Any]:
    """Build the persisted analysis state object for a conversation turn."""

    payload = dict(response or {})
    active_payload = _active_payload_for_context(payload)
    logic = _logic_form_dict(active_payload)
    previous = dict(previous_context or {})
    if not logic:
        state_name = "awaiting_clarification" if active_payload.get("answer_type") == "clarification" else "chat_only"
        return {
            "state_version": "v1",
            "state_name": state_name,
            "dataset_id": str(active_payload.get("dataset_id") or previous.get("dataset_id") or ""),
            "run_id": str(active_payload.get("run_id") or ""),
            "question": str(original_question or active_payload.get("question") or ""),
            "previous_run_id": str(previous.get("run_id") or ""),
            "active": state_name == "awaiting_clarification",
            "history_depth": int(previous.get("history_depth") or 0),
            "available_followup_actions": list(previous.get("available_followup_actions") or []),
        }

    operation = str(logic.get("operation") or logic.get("task_type") or "")
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    time_window = logic.get("time_window") if isinstance(logic.get("time_window"), dict) else {}
    result = active_payload.get("result") if isinstance(active_payload.get("result"), dict) else {}
    rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
    columns = [str(column) for column in result.get("columns") or (rows[0].keys() if rows else [])]
    context = {
        "state_version": "v1",
        "state_name": "analysis_ready" if active_payload.get("success") is not False else "analysis_failed",
        "active": active_payload.get("success") is not False,
        "dataset_id": str(active_payload.get("dataset_id") or previous.get("dataset_id") or ""),
        "run_id": str(active_payload.get("run_id") or ""),
        "question": str(original_question or active_payload.get("question") or ""),
        "operation": operation,
        "capability": capability_for_operation(operation).to_dict(),
        "logic_form": logic,
        "scope": {
            "source_tables": _source_tables(logic, params),
            "metric": _first_text(logic.get("metric"), params.get("metric")),
            "dimension": _first_text(logic.get("group_by"), params.get("dimension"), params.get("group_by")),
            "time_window": time_window or _retail_time_window(params),
            "filters": logic.get("filters") if isinstance(logic.get("filters"), dict) else {},
            "parameters": _compact_parameters(params),
        },
        "last_result": {
            "columns": columns,
            "row_count": len(rows),
            "first_row": rows[0] if rows else {},
        },
        "history_depth": int(previous.get("history_depth") or 0) + 1,
    }
    context["available_followup_actions"] = build_next_actions(
        question=str(active_payload.get("question") or original_question or ""),
        plan=logic,
        rows=rows,
    )
    completed = payload.get("agent_actions") if isinstance(payload.get("agent_actions"), list) else []
    if completed:
        context["last_completed_actions"] = completed
    return context


def build_next_actions(
    *,
    question: str,
    plan: AnalysisPlan | Mapping[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return executable follow-up actions derived from operation capability metadata."""

    logic = _logic_form_dict(plan)
    parameters = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    operation = str(logic.get("operation") or logic.get("task_type") or "")
    question_text = str(question or "")
    rows = rows or []
    columns = [str(column) for column in (rows[0].keys() if rows else [])]
    metric = _first_text(logic.get("metric"), parameters.get("metric"), _first_numeric_column(rows, columns), "核心指标")
    dimension = _first_text(logic.get("group_by"), parameters.get("dimension"), parameters.get("group_by"), _first_dimension_column(rows, columns))

    if operation == "retail_category_distribution_monthly_trend" or (
        "分品类" in question_text and "历史分销金额" in question_text and "趋势" in question_text
    ):
        window = _retail_month_window_text(parameters.get("start_ym"), parameters.get("end_ym")) or _retail_month_window_from_question(question_text)
        return [
            _action(
                action_id="review_extremes",
                label="复核峰值、低点和最大波动期",
                operation="retail_category_distribution_monthly_trend",
                question=f"{window}分品类历史分销金额趋势，标出峰值、低点和最大波动期？" if window else "分品类历史分销金额趋势，标出峰值、低点和最大波动期？",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "ctg_name", "metric": "sign_amt"},
                dimension="ctg_name",
            ),
            _action(
                action_id="drilldown_customer_source",
                label="按客户拆分来源 Top 排名",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按客户拆分来源Top排名。" if window else "请生成历史分销金额按客户拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "cust_name", "metric": "sign_amt"},
                dimension="cust_name",
            ),
            _action(
                action_id="drilldown_product_source",
                label="按产品拆分来源 Top 排名",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按产品拆分来源Top排名。" if window else "请生成历史分销金额按产品拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "sku_name", "metric": "sign_amt"},
                dimension="sku_name",
            ),
        ]

    if operation == "retail_distribution_topn_chart":
        window = _retail_month_window_text(parameters.get("start_ym"), parameters.get("end_ym"))
        return [
            _action(
                action_id="switch_to_customer_source",
                label="按客户拆分来源",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按客户拆分来源Top排名。" if window else "请生成历史分销金额按客户拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "cust_name", "metric": "sign_amt"},
                dimension="cust_name",
            ),
            _action(
                action_id="switch_to_product_source",
                label="按产品拆分来源",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按产品拆分来源Top排名。" if window else "请生成历史分销金额按产品拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "sku_name", "metric": "sign_amt"},
                dimension="sku_name",
            ),
        ]

    if _looks_like_trend(operation, question_text):
        return [
            _action(
                action_id="review_extremes",
                label="复核峰值、低点和最大波动期",
                operation=operation,
                question=f"把{metric}的峰值、低点和最大波动期标出来？",
                inherited_parameters=_generic_inherited_parameters(logic, parameters),
                parameters={"metric": metric, "dimension": dimension},
                dimension=dimension,
            )
        ]
    if _looks_like_ranking(operation, question_text):
        return [
            _action(
                action_id="drilldown_top_results",
                label="继续下钻 Top 结果",
                operation=operation,
                question=f"把排名靠前的{dimension or '对象'}继续下钻，比较{metric}差距？",
                inherited_parameters=_generic_inherited_parameters(logic, parameters),
                parameters={"metric": metric, "dimension": dimension},
                dimension=dimension,
            )
        ]
    return []


def plan_followup_actions(question: str, context: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Plan executable follow-up actions from the current analysis context."""

    if not isinstance(context, Mapping) or context.get("state_name") not in {"analysis_ready", "analysis_failed"}:
        return []
    compact = re.sub(r"\s+", "", str(question or ""))
    if not compact:
        return []
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    operation = str(context.get("operation") or logic.get("operation") or logic.get("task_type") or "")
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = list(context.get("available_followup_actions") or [])
    actions: list[dict[str, Any]] = []

    if _asks_extreme_review(compact):
        action = _find_action(available, "review_extremes") or _retail_review_extremes_action(params)
        if action:
            actions.append(action)
    if _asks_source_drilldown(compact):
        dimension = _followup_dimension(compact)
        action = _find_retail_drilldown_action(available, dimension) or _retail_source_action(params, dimension)
        if action:
            actions.append(action)
    if not actions and operation == "retail_distribution_topn_chart" and _asks_dimension_switch(compact):
        dimension = _followup_dimension(compact)
        action = _find_retail_drilldown_action(available, dimension) or _retail_source_action(params, dimension)
        if action:
            actions.append(action)

    unique: list[dict[str, Any]] = []
    seen = set()
    for action in actions:
        key = (action.get("operation"), action.get("question"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(action))
    return unique


def action_questions(actions: list[Mapping[str, Any]]) -> list[str]:
    """Extract user-facing questions from structured actions."""

    questions = []
    for action in actions:
        question = str(action.get("question") or "").strip()
        if question:
            questions.append(question)
    return questions


def _active_payload_for_context(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    sub_results = result.get("sub_results") if isinstance(result.get("sub_results"), list) else []
    for sub in reversed(sub_results):
        if isinstance(sub, dict) and sub.get("success") is not False and isinstance(sub.get("logic_form"), dict):
            return sub
    return payload


def _logic_form_dict(plan: AnalysisPlan | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(plan, AnalysisPlan):
        return _as_dict(plan.logic_form)
    if isinstance(plan, Mapping):
        logic = plan.get("logic_form")
        if isinstance(logic, Mapping):
            return dict(logic)
        return dict(plan)
    return {}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _action(
    *,
    action_id: str,
    label: str,
    operation: str,
    question: str,
    inherited_parameters: dict[str, Any],
    parameters: dict[str, Any],
    dimension: str = "",
) -> dict[str, Any]:
    capability = capability_for_operation(operation)
    return {
        "action_id": action_id,
        "label": label,
        "operation": operation,
        "question": question,
        "inherited_parameters": {key: value for key, value in inherited_parameters.items() if value not in (None, "", [], {})},
        "parameters": {key: value for key, value in parameters.items() if value not in (None, "", [], {})},
        "dimension": dimension,
        "status": "executable" if capability.supports_pandas else "unsupported",
        "capability_family": capability.capability_family,
        "support_boundary": capability.support_boundary,
    }


def _find_action(actions: list[Any], action_id: str) -> dict[str, Any]:
    for action in actions:
        if isinstance(action, Mapping) and str(action.get("action_id") or "") == action_id:
            return dict(action)
    return {}


def _find_retail_drilldown_action(actions: list[Any], dimension: str) -> dict[str, Any]:
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        if action.get("operation") != "retail_distribution_topn_chart":
            continue
        if dimension and action.get("dimension") == dimension:
            return dict(action)
        if not dimension and action.get("dimension") in {"cust_name", "sku_name"}:
            return dict(action)
    return {}


def _retail_review_extremes_action(params: Mapping[str, Any]) -> dict[str, Any]:
    window = _retail_month_window_text(params.get("start_ym"), params.get("end_ym"))
    return _action(
        action_id="review_extremes",
        label="复核峰值、低点和最大波动期",
        operation="retail_category_distribution_monthly_trend",
        question=f"{window}分品类历史分销金额趋势，标出峰值、低点和最大波动期？" if window else "分品类历史分销金额趋势，标出峰值、低点和最大波动期？",
        inherited_parameters=_inherit_retail_window(params),
        parameters={"dimension": "ctg_name", "metric": "sign_amt"},
        dimension="ctg_name",
    )


def _retail_source_action(params: Mapping[str, Any], dimension: str) -> dict[str, Any]:
    dimension = dimension or "cust_name"
    label = "按产品拆分来源 Top 排名" if dimension == "sku_name" else "按客户拆分来源 Top 排名"
    text = "产品" if dimension == "sku_name" else "客户"
    window = _retail_month_window_text(params.get("start_ym"), params.get("end_ym"))
    return _action(
        action_id="drilldown_product_source" if dimension == "sku_name" else "drilldown_customer_source",
        label=label,
        operation="retail_distribution_topn_chart",
        question=f"请生成{window}历史分销金额按{text}拆分来源Top排名。" if window else f"请生成历史分销金额按{text}拆分来源Top排名。",
        inherited_parameters=_inherit_retail_window(params),
        parameters={"dimension": dimension, "metric": "sign_amt"},
        dimension=dimension,
    )


def _asks_extreme_review(compact: str) -> bool:
    return any(token in compact for token in ("复核", "高点", "低点", "峰值", "异常高", "异常低", "波动"))


def _asks_source_drilldown(compact: str) -> bool:
    return any(token in compact for token in ("拆分", "来源", "拉动", "驱动", "构成", "组成", "下钻", "按客户", "按产品", "按品类"))


def _asks_dimension_switch(compact: str) -> bool:
    return any(token in compact for token in ("按客户", "按产品", "按品类", "也看", "换成"))


def _followup_dimension(compact: str) -> str:
    if "产品" in compact or "sku" in compact.lower() or "SKU" in compact:
        return "sku_name"
    if "品类" in compact:
        return "ctg_name"
    if "客户" in compact:
        return "cust_name"
    return ""


def _inherit_retail_window(params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "start_ym": params.get("start_ym"),
        "end_ym": params.get("end_ym"),
        "top_n": params.get("top_n") or params.get("limit"),
        "metric": params.get("metric") or "sign_amt",
    }


def _generic_inherited_parameters(logic: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metric": _first_text(logic.get("metric"), params.get("metric")),
        "dimension": _first_text(logic.get("group_by"), params.get("dimension"), params.get("group_by")),
        "filters": logic.get("filters"),
        "time_window": logic.get("time_window"),
    }


def _compact_parameters(params: Mapping[str, Any]) -> dict[str, Any]:
    keep = ("table", "metric", "dimension", "group_by", "aggregation", "start_ym", "end_ym", "ym", "top_n", "limit")
    return {key: params.get(key) for key in keep if params.get(key) not in (None, "", [], {})}


def _source_tables(logic: Mapping[str, Any], params: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for item in logic.get("source_tables") or []:
        if item:
            values.append(str(item))
    for key in ("source_tables", "tables", "table"):
        raw = params.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
        elif raw:
            values.append(str(raw))
    return list(dict.fromkeys(values))


def _retail_time_window(params: Mapping[str, Any]) -> dict[str, Any]:
    return {key: params.get(key) for key in ("start_ym", "end_ym", "ym") if params.get(key)}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_numeric_column(rows: list[dict[str, Any]], columns: list[str]) -> str:
    for column in columns:
        if any(_to_float(row.get(column)) is not None for row in rows):
            return column
    return ""


def _first_dimension_column(rows: list[dict[str, Any]], columns: list[str]) -> str:
    numeric = {_first_numeric_column(rows, columns)}
    for column in columns:
        if column not in numeric and not re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column, re.I):
            return column
    return ""


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _looks_like_trend(operation: str, question_text: str) -> bool:
    return "trend" in operation or any(token in question_text for token in ("趋势", "波动", "环比", "同比", "增长", "下降"))


def _looks_like_ranking(operation: str, question_text: str) -> bool:
    return any(token in operation for token in ("rank", "top")) or any(token in question_text for token in ("排名", "top", "最高", "最低", "最大", "最小", "第一", "前"))


def _retail_month_window_from_question(question: str) -> str:
    match = re.search(r"(\d{4})年\s*(\d{1,2})月?\s*至\s*(?:(\d{4})年)?\s*(\d{1,2})月", str(question or ""))
    if not match:
        return ""
    start_year = int(match.group(1))
    start_month = int(match.group(2))
    end_year = int(match.group(3) or start_year)
    end_month = int(match.group(4))
    if not (1 <= start_month <= 12 and 1 <= end_month <= 12):
        return ""
    return f"{start_year}年{start_month}月至{end_year}年{end_month}月"


def _retail_month_window_text(start_ym: Any, end_ym: Any) -> str:
    start_text = _ym_text(start_ym)
    end_text = _ym_text(end_ym)
    if start_text and end_text and start_text != end_text:
        return f"{start_text}至{end_text}"
    return start_text or end_text


def _ym_text(value: Any) -> str:
    try:
        ym_value = int(value)
    except (TypeError, ValueError):
        return ""
    year, month = divmod(ym_value, 100)
    if year <= 0 or month <= 0 or month > 12:
        return ""
    return f"{year}年{month}月"
