"""Rule-first chart planner for verified analysis results."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec


CHART_TYPES = {"bar", "horizontal_bar", "line", "pie", "donut", "histogram", "box", "scatter", "kpi", None}


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
    numeric_columns = [column for column in safe_columns if _numeric_column(rows, column)]
    categorical_columns = [column for column in safe_columns if column not in numeric_columns]
    logic = plan_dict.get("logic_form") if isinstance(plan_dict.get("logic_form"), dict) else {}
    task_type = str(logic.get("task_type") or "")
    operation = str(logic.get("operation") or "")

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

    if len(safe_columns) == 1 and numeric_columns:
        column = numeric_columns[0]
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

    if len(safe_columns) < 2 or not numeric_columns:
        return ChartSpec(
            chart_type="kpi",
            title="分析结果",
            data=rows,
            reason="Result does not contain a category-metric pair suitable for a chart.",
            selection_reason="non_numeric_or_scalar_result",
            confidence=0.7,
        )

    x_column = _time_column(safe_columns) or (categorical_columns[0] if categorical_columns else safe_columns[0])
    y_columns = [column for column in numeric_columns if column != x_column]
    y_column = y_columns[0] if y_columns else numeric_columns[0]
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
        if any(token in lowered for token in ("date", "day", "month", "year", "week", "time", "日期", "时间", "月份", "年份", "周")):
            return column
    return None


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
