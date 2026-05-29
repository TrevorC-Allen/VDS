"""Rule-first chart planner for verified analysis results."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec


CHART_TYPES = {
    "bar",
    "horizontal_bar",
    "line",
    "combo_column_line",
    "stacked_column",
    "stacked_area",
    "dual_axis_line",
    "pie",
    "donut",
    "histogram",
    "box",
    "scatter",
    "kpi",
    None,
}


def build_chart_spec(
    *,
    plan: AnalysisPlan | dict[str, Any],
    execution_result: ExecutionResult | dict[str, Any],
    verification_passed: bool,
) -> ChartSpec:
    """Select a frontend-neutral chart spec from verified result shape."""

    if not verification_passed:
        return ChartSpec(
            chart_type=None,
            reason="No chart because verification did not pass.",
            fallback_reason="verification_failed",
        )

    plan_dict = _as_dict(plan)
    result_dict = _as_dict(execution_result)
    rows, columns = _rows_and_columns(result_dict)
    if not rows:
        return ChartSpec(
            chart_type="kpi",
            title="分析结果",
            data=[],
            reason="No rows were returned; KPI-style answer display is sufficient.",
            selection_reason="empty_or_scalar_result",
            confidence=0.75,
        )

    safe_columns = columns or list(rows[0])
    logic = plan_dict.get("logic_form") if isinstance(plan_dict.get("logic_form"), dict) else {}
    task_type = str(logic.get("task_type") or "")
    operation = str(logic.get("operation") or "")
    output_format = logic.get("output_format") if isinstance(logic.get("output_format"), dict) else {}
    requested_chart_type = _requested_chart_type(output_format, logic)
    if _looks_like_detail_rows(rows, safe_columns, operation, task_type):
        return ChartSpec(
            chart_type=None,
            title="明细结果",
            data=rows,
            reason="No chart because the result is row-level detail; a table is the safer display.",
            selection_reason="detail_rows_prefer_table",
            fallback_reason="detail_rows_prefer_table",
            confidence=0.88,
        )

    numeric_columns = [column for column in safe_columns if _numeric_column(rows, column)]
    metric_numeric_columns = [column for column in numeric_columns if not _looks_like_identifier_or_time_metric(column, rows)]
    categorical_columns = [column for column in safe_columns if column not in metric_numeric_columns]

    if len(rows) == 1 and len(safe_columns) == 1:
        return ChartSpec(
            chart_type="kpi",
            title="核心结果",
            data=rows,
            reason="Selected KPI display for a single scalar result.",
            encoding={"value": safe_columns[0]},
            confidence=0.82,
            selection_reason="single_scalar_result",
        )

    if len(safe_columns) == 1 and metric_numeric_columns:
        column = metric_numeric_columns[0]
        return ChartSpec(
            chart_type="histogram",
            x=column,
            y="count",
            title=f"{column} 分布",
            data=rows,
            reason="Selected histogram for a one-column numeric distribution.",
            encoding={"x": column, "y": "count"},
            series=[{"type": "histogram", "x": column, "y": "count"}],
            confidence=0.78,
            selection_reason="single_numeric_distribution",
        )

    if len(safe_columns) < 2 or not metric_numeric_columns:
        return ChartSpec(
            chart_type="kpi",
            title="分析结果",
            data=rows,
            reason="Result does not contain a safe category-metric pair suitable for a chart.",
            selection_reason="non_numeric_or_identifier_only_result",
            confidence=0.7,
        )

    x_column = _time_column(safe_columns) or _preferred_category_column(categorical_columns, metric_numeric_columns)
    y_columns = [column for column in metric_numeric_columns if column != x_column]
    y_column = y_columns[0] if y_columns else metric_numeric_columns[0]
    if not x_column or _looks_like_identifier_metric(y_column):
        return ChartSpec(
            chart_type=None,
            title="结果表",
            data=rows,
            reason="No chart because the available numeric fields look like identifiers or time buckets.",
            selection_reason="unsafe_metric_column",
            fallback_reason="unsafe_metric_column",
            confidence=0.86,
        )
    combo_chart = _combo_chart_spec(
        rows=rows,
        x_column=x_column,
        metric_columns=y_columns or [y_column],
        requested_chart_type=requested_chart_type,
    )
    if combo_chart is not None:
        return combo_chart
    stacked_chart = _stacked_chart_spec(
        rows=rows,
        x_column=x_column,
        metric_columns=y_columns or [y_column],
        requested_chart_type=requested_chart_type,
    )
    if stacked_chart is not None:
        return stacked_chart
    dual_axis_chart = _dual_axis_line_spec(
        rows=rows,
        x_column=x_column,
        metric_columns=y_columns or [y_column],
        requested_chart_type=requested_chart_type,
    )
    if dual_axis_chart is not None:
        return dual_axis_chart
    chart_type = "bar"
    selection_reason = "category_metric_comparison"
    title = "数据对比"

    if _time_column([x_column]) or task_type == "trend" or operation == "trend":
        chart_type = "line"
        selection_reason = "time_series_trend"
        title = f"{y_column} 趋势"
    elif len(y_columns) > 1:
        chart_type = "bar"
        selection_reason = "multi_metric_grouped_comparison"
        title = "多指标对比"
    elif _looks_part_to_whole(operation, y_column, rows, y_column):
        chart_type = "donut" if len(rows) > 5 else "pie"
        selection_reason = "part_to_whole_share"
        title = f"{y_column} 构成"
    elif len(rows) > 12:
        chart_type = "horizontal_bar"
        selection_reason = "long_category_ranking"
        title = f"{y_column} 排名"
    elif task_type == "ranking" or operation in {"ranking", "filtered_metric_ranking", "rank_by_metric", "top_count"}:
        title = f"{y_column} 排名"
    if requested_chart_type == "horizontal_bar":
        chart_type = "horizontal_bar"
        selection_reason = "explicit_horizontal_ranking"
    elif requested_chart_type in CHART_TYPES and requested_chart_type not in {None, "kpi"}:
        chart_type = requested_chart_type

    return ChartSpec(
        chart_type=chart_type,
        x=x_column,
        y=y_column,
        title=title,
        data=rows,
        reason=f"Selected {chart_type} for {selection_reason}.",
        encoding={"x": x_column, "y": y_column},
        series=[{"type": chart_type, "x": x_column, "y": column} for column in (y_columns or [y_column])],
        confidence=0.86,
        selection_reason=selection_reason,
    )


def _requested_chart_type(output_format: dict[str, Any], logic: dict[str, Any]) -> str | None:
    requested = str(output_format.get("chart_type") or logic.get("chart_type") or "").strip()
    if requested in CHART_TYPES:
        return requested
    return None


def _combo_chart_spec(
    *,
    rows: list[dict[str, Any]],
    x_column: str,
    metric_columns: list[str],
    requested_chart_type: str | None,
) -> ChartSpec | None:
    rate_columns = [column for column in metric_columns if _looks_like_rate_column(column)]
    amount_columns = [column for column in metric_columns if column not in rate_columns]
    wants_combo = requested_chart_type == "combo_column_line"
    if not wants_combo and not (_time_column([x_column]) and rate_columns and len(amount_columns) >= 1):
        return None
    bar_columns = amount_columns[:2] if amount_columns else metric_columns[:1]
    line_columns = rate_columns[:1] if rate_columns else metric_columns[1:2]
    if not bar_columns or not line_columns:
        return None
    title = "目标、实际与达成率对比" if _looks_like_target_actual_combo(bar_columns, line_columns) else "柱线组合图"
    series = [{"type": "bar", "x": x_column, "y": column, "axis": "left"} for column in bar_columns]
    series.extend({"type": "line", "x": x_column, "y": column, "axis": "right"} for column in line_columns)
    return ChartSpec(
        chart_type="combo_column_line",
        x=x_column,
        y=bar_columns[0],
        title=title,
        data=rows,
        reason="Selected combo chart for target/actual comparison with rate overlay.",
        encoding={"x": x_column, "y": bar_columns[0], "y_left": bar_columns, "y_right": line_columns},
        series=series,
        confidence=0.9,
        selection_reason="combo_target_actual_rate" if wants_combo or _looks_like_target_actual_combo(bar_columns, line_columns) else "explicit_combo_chart",
    )


def _stacked_chart_spec(
    *,
    rows: list[dict[str, Any]],
    x_column: str,
    metric_columns: list[str],
    requested_chart_type: str | None,
) -> ChartSpec | None:
    if requested_chart_type not in {"stacked_column", "stacked_area"}:
        return None
    usable_metrics = [column for column in metric_columns if column != x_column]
    if len(usable_metrics) < 2:
        return None
    chart_type = requested_chart_type
    series_type = "area" if chart_type == "stacked_area" else "bar"
    return ChartSpec(
        chart_type=chart_type,
        x=x_column,
        y=usable_metrics[0],
        title="堆叠趋势图" if chart_type == "stacked_area" else "堆叠对比图",
        data=rows,
        reason=f"Selected {chart_type} for explicit stacked multi-series request.",
        encoding={"x": x_column, "y": usable_metrics[0], "stack": usable_metrics},
        series=[{"type": series_type, "x": x_column, "y": column, "stacked": True} for column in usable_metrics],
        confidence=0.9,
        selection_reason=f"explicit_{chart_type}",
    )


def _dual_axis_line_spec(
    *,
    rows: list[dict[str, Any]],
    x_column: str,
    metric_columns: list[str],
    requested_chart_type: str | None,
) -> ChartSpec | None:
    if requested_chart_type != "dual_axis_line":
        return None
    usable_metrics = [column for column in metric_columns if column != x_column]
    if len(usable_metrics) < 2:
        return None
    left_metric = usable_metrics[0]
    right_metric = usable_metrics[1]
    return ChartSpec(
        chart_type="dual_axis_line",
        x=x_column,
        y=left_metric,
        title="双轴趋势图",
        data=rows,
        reason="Selected dual-axis line chart for explicit two-metric monthly trend request.",
        encoding={"x": x_column, "y_left": [left_metric], "y_right": [right_metric]},
        series=[
            {"type": "line", "x": x_column, "y": left_metric, "axis": "left"},
            {"type": "line", "x": x_column, "y": right_metric, "axis": "right"},
        ],
        confidence=0.9,
        selection_reason="explicit_dual_axis_line",
    )


def _rows_and_columns(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = list(result.get("rows") or [])
    columns = list(result.get("columns") or [])
    value = result.get("value")
    if not rows and isinstance(value, list) and all(isinstance(row, dict) for row in value):
        rows = list(value)
    if not rows and isinstance(value, dict):
        rows = [value]
    if not columns and rows:
        columns = [str(column) for column in rows[0].keys()]
    return rows, columns


def _numeric_column(rows: list[dict[str, Any]], column: str) -> bool:
    values = [row.get(column) for row in rows if _has_value(row.get(column))]
    if not values:
        return False
    numeric = 0
    for value in values[:50]:
        try:
            float(value)
            numeric += 1
        except (TypeError, ValueError):
            pass
    return numeric / len(values[:50]) >= 0.8


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value == "":
        return False
    return True


def _time_column(columns: list[str]) -> str | None:
    for column in columns:
        lowered = column.lower()
        if any(token in lowered for token in ("date", "month", "week", "日期", "时间", "月份", "周标签")):
            return column
    return None


def _preferred_category_column(categorical_columns: list[str], metric_columns: list[str]) -> str | None:
    for column in categorical_columns:
        if not _looks_like_identifier_metric(column):
            return column
    for column in categorical_columns:
        if column not in metric_columns:
            return column
    return None


def _looks_like_detail_rows(rows: list[dict[str, Any]], columns: list[str], operation: str, task_type: str) -> bool:
    lowered = f"{operation} {task_type}".lower()
    if any(token in lowered for token in ("detail", "lookup", "raw", "sample")) and len(columns) >= 4:
        return True
    if len(columns) >= 8 and len(rows) >= 5:
        numeric_columns = [column for column in columns if _numeric_column(rows, column)]
        unsafe_numeric = [column for column in numeric_columns if _looks_like_identifier_or_time_metric(column, rows)]
        categorical = [column for column in columns if column not in numeric_columns]
        return len(unsafe_numeric) >= max(2, len(numeric_columns) - 1) and len(categorical) >= 2
    return False


def _looks_like_identifier_or_time_metric(column: str, rows: list[dict[str, Any]]) -> bool:
    if _looks_like_identifier_metric(column):
        return True
    lowered = column.lower()
    if any(token == lowered or token in lowered for token in ("year", "年份", "hour", "小时", "minute", "分钟", "day_of_year", "dayofyear", "周序号")):
        return True
    values = [row.get(column) for row in rows if _has_value(row.get(column))]
    if not values:
        return False
    unique_ratio = len({str(value) for value in values}) / len(values)
    if unique_ratio > 0.9 and len(values) >= 8 and not any(token in lowered for token in ("amount", "sales", "revenue", "金额", "销售额", "收入", "利润", "数量", "count", "rate", "占比")):
        return True
    return False


def _looks_like_identifier_metric(column: str) -> bool:
    lowered = column.lower()
    compact = lowered.replace("_", "").replace("-", "").replace(" ", "")
    return any(
        token in lowered
        for token in (
            "reference",
            "psp",
            "bin",
            "编号",
            "代码",
            "流水",
            "卡号",
        )
    ) or compact in {"id", "ids"} or compact.endswith("id") or compact.endswith("ids") or compact in {"number", "cardnumber"}


def _looks_like_rate_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("rate", "ratio", "share", "pct", "percent", "%", "达成率", "完成率", "占比", "比例"))


def _looks_like_target_actual_combo(bar_columns: list[str], line_columns: list[str]) -> bool:
    bars_text = " ".join(bar_columns).lower()
    lines_text = " ".join(line_columns).lower()
    return (
        any(token in bars_text for token in ("目标", "target"))
        and any(token in bars_text for token in ("实际", "actual", "金额", "amount"))
        and any(token in lines_text for token in ("rate", "达成率", "完成率"))
    )


def _looks_part_to_whole(operation: str, metric: str, rows: list[dict[str, Any]], y_column: str) -> bool:
    lowered_metric = metric.lower()
    if operation in {"top_k_share", "boolean_percentage"}:
        return True
    if any(token in lowered_metric for token in ("share", "percentage", "rate", "占比", "比例", "百分比")) and len(rows) <= 8:
        total = 0.0
        for row in rows:
            try:
                total += float(row.get(y_column) or 0)
            except (TypeError, ValueError):
                return False
        return 0 < total <= 105
    return False


def _as_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {}
