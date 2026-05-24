"""Dataset overview response builder for broad workbench questions."""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

from data_agent_core.contracts.response_contracts import InsightResult


def build_dataset_overview_response(
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    tables: dict[str, pd.DataFrame],
    profile: Any = None,
    agent_mode: str = "multi_agent",
) -> dict[str, Any]:
    """Build a full-table, user-facing dataset overview response."""

    table_name, df = _primary_table(tables)
    profile_payload = _profile_payload(profile)
    table_profile = _table_profile(profile_payload, table_name)
    source_file = table_profile.get("source_file") or profile_payload.get("file_name") or table_name
    sheet = table_profile.get("sheet")
    row_count = int(len(df))
    columns = [str(column) for column in df.columns]
    metric_column = _preferred_metric_column(df, question)
    dimension_column = _preferred_dimension_column(columns, metric_column)
    period_column = _preferred_period_column(columns)

    result_rows = [
        {"指标": "数据表", "数值": _join_non_empty([table_name, source_file, sheet], " / ")},
        {"指标": "行列规模", "数值": f"{row_count} 行，{len(columns)} 列"},
        {"指标": "主要字段", "数值": "、".join(columns[:8]) + (" ..." if len(columns) > 8 else "")},
    ]
    answer_parts = [
        f"我先按数据概览来看：当前主表“{table_name}”有 {row_count} 行、{len(columns)} 列。"
    ]

    metric_summary = None
    if metric_column:
        metric_summary = _metric_summary(df, metric_column, dimension_column, period_column)
        result_rows.extend(metric_summary["rows"])
        answer_parts.append(
            f"优先识别的关键数值字段是“{metric_column}”：{metric_column}合计 {metric_summary['total']}，"
            f"平均 {metric_summary['average']}，最高 {metric_summary['max_description']}，最低 {metric_summary['min_description']}。"
        )
        if metric_summary.get("top_group"):
            result_rows.append({"指标": f"最高{dimension_column}", "数值": metric_summary["top_group"]})
            answer_parts.append(f"按“{dimension_column}”汇总，最高的是 {metric_summary['top_group']}。")
    else:
        answer_parts.append("我没有找到稳定的数值指标字段，所以先给出表规模、字段结构和可追问方向。")

    if period_column:
        period_count = df[period_column].dropna().astype(str).nunique() if period_column in df.columns else 0
        if period_count:
            result_rows.append({"指标": f"{period_column}覆盖", "数值": f"{period_count} 个取值"})
    if dimension_column:
        answer_parts.append(f"你可以继续让我按“{dimension_column}”下钻，或指定某个指标、时间、渠道、客户类型来比较。")
    else:
        answer_parts.append("你可以继续指定想看的指标、维度或时间范围，我再做更精确的分析。")

    return {
        "response_version": "v1",
        "success": True,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "answer_type": "overview",
        "execution_mode": "overview",
        "answer": "".join(answer_parts),
        "logic_form": {
            "task_type": "dataset_overview",
            "operation": "dataset_overview",
            "parameters": {
                "table": table_name,
                "metric": metric_column,
                "dimension": dimension_column,
                "period": period_column,
            },
            "source_tables": [table_name],
            "output_format": {"answer_type": "overview"},
        },
        "result": {
            "columns": ["指标", "数值"],
            "rows": result_rows,
            "value": {
                "table": table_name,
                "row_count": row_count,
                "column_count": len(columns),
                "metric_column": metric_column,
                "dimension_column": dimension_column,
            },
        },
        "verification": {
            "passed": True,
            "confidence": 1.0,
            "notes": ["Dataset overview was computed from the uploaded table, not from a row-count shortcut."],
        },
        "insight": InsightResult(summary="").__dict__,
        "chart": None,
        "quality_report": None,
        "reasoning_trace_view": [
            {
                "step_id": "intent",
                "name": "理解问题",
                "status": "completed",
                "summary": "这是宽泛的数据概览请求，我会先给出表规模、关键数值字段和可下钻方向。",
            },
            {
                "step_id": "select_table",
                "name": "选择数据",
                "status": "completed",
                "summary": f"使用主表“{table_name}”，共 {row_count} 行、{len(columns)} 列。",
            },
            {
                "step_id": "summarize",
                "name": "生成概览",
                "status": "completed",
                "summary": "已整理为汇总指标表，避免把原始明细行或单个行数当作回答。",
            },
        ],
        "warnings": [],
        "errors": [],
        "debug": {
            "agent_mode": agent_mode,
            "message_intent": "dataset_overview",
            "operation": "dataset_overview",
            "source_tables": [table_name],
            "user_experience_shaping": {
                "applied": True,
                "reason": "generic_dataset_overview_prevents_row_count_or_raw_detail_answer",
                "source_row_count": row_count,
                "source_column_count": len(columns),
                "metric_column": metric_column,
                "dimension_column": dimension_column,
            },
        },
    }


def _primary_table(tables: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
    if not tables:
        raise ValueError("No parsed tables are available.")
    return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))


def _profile_payload(profile: Any) -> dict[str, Any]:
    if profile is None:
        return {}
    if is_dataclass(profile):
        return asdict(profile)
    if isinstance(profile, dict):
        return profile
    return {}


def _table_profile(profile: dict[str, Any], table_name: str) -> dict[str, Any]:
    for table in profile.get("tables") or []:
        if not isinstance(table, dict):
            continue
        if str(table.get("table_name") or "") == table_name:
            return table
    return {}


def _preferred_metric_column(df: pd.DataFrame, question: str) -> str | None:
    columns = [str(column) for column in df.columns]
    numeric_columns = [column for column in columns if _numeric_ratio(df[column]) >= 0.75]
    if not numeric_columns:
        return None
    lowered_question = question.lower()
    preferred_tokens = (
        "订阅收入",
        "销售额",
        "收入",
        "订单金额",
        "成交金额",
        "金额",
        "毛利",
        "利润",
        "arr",
        "gmv",
        "sales",
        "revenue",
        "amount",
    )
    for token in preferred_tokens:
        for column in numeric_columns:
            if token in column.lower() or column.lower() in lowered_question:
                return column
    non_identifier = [column for column in numeric_columns if not _looks_like_identifier_or_score(column)]
    return non_identifier[0] if non_identifier else numeric_columns[0]


def _preferred_dimension_column(columns: list[str], metric_column: str | None) -> str | None:
    preferred_tokens = ("区域", "城市", "获客渠道", "渠道", "产品线", "套餐名称", "客户类型", "行业", "category", "city", "region", "channel", "product")
    for token in preferred_tokens:
        for column in columns:
            if column == metric_column:
                continue
            if token in column.lower():
                return column
    return None


def _preferred_period_column(columns: list[str]) -> str | None:
    for token in ("月份", "周标签", "日期", "month", "week", "date"):
        for column in columns:
            if token in column.lower():
                return column
    return None


def _metric_summary(df: pd.DataFrame, metric_column: str, dimension_column: str | None, period_column: str | None) -> dict[str, Any]:
    values = pd.to_numeric(df[metric_column], errors="coerce").dropna()
    total = float(values.sum()) if not values.empty else 0.0
    average = float(values.mean()) if not values.empty else 0.0
    max_index = values.idxmax() if not values.empty else None
    min_index = values.idxmin() if not values.empty else None
    max_row = df.loc[max_index].to_dict() if max_index is not None else {}
    min_row = df.loc[min_index].to_dict() if min_index is not None else {}
    rows = [
        {"指标": f"{metric_column}合计", "数值": _format_number(total)},
        {"指标": f"{metric_column}平均", "数值": _format_number(average)},
        {"指标": f"{metric_column}最高", "数值": _describe_row_metric(max_row, metric_column, dimension_column, period_column)},
        {"指标": f"{metric_column}最低", "数值": _describe_row_metric(min_row, metric_column, dimension_column, period_column)},
    ]
    return {
        "rows": rows,
        "total": _format_number(total),
        "average": _format_number(average),
        "max_description": _describe_row_metric(max_row, metric_column, dimension_column, period_column),
        "min_description": _describe_row_metric(min_row, metric_column, dimension_column, period_column),
        "top_group": _top_group(df, dimension_column, metric_column) if dimension_column else None,
    }


def _numeric_ratio(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return 0.0
    numeric = pd.to_numeric(non_null, errors="coerce").notna().sum()
    return float(numeric) / float(len(non_null))


def _looks_like_identifier_or_score(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("id", "序号", "编号", "评分", "score", "rate", "率", "天数", "账号数", "席位"))


def _describe_row_metric(row: dict[str, Any], metric_column: str, dimension_column: str | None, period_column: str | None) -> str:
    parts = []
    if dimension_column and row.get(dimension_column) not in {None, ""}:
        parts.append(str(row.get(dimension_column)))
    if period_column and row.get(period_column) not in {None, ""}:
        parts.append(str(row.get(period_column)))
    value = _as_float(row.get(metric_column)) or 0.0
    prefix = " / ".join(parts)
    return f"{prefix}：{_format_number(value)}" if prefix else _format_number(value)


def _top_group(df: pd.DataFrame, dimension_column: str | None, metric_column: str) -> str | None:
    if not dimension_column or dimension_column not in df.columns:
        return None
    data = df[[dimension_column, metric_column]].copy()
    data[metric_column] = pd.to_numeric(data[metric_column], errors="coerce")
    grouped = data.dropna(subset=[dimension_column, metric_column]).groupby(dimension_column, dropna=True)[metric_column].sum()
    if grouped.empty:
        return None
    key = grouped.idxmax()
    return f"{key}：{_format_number(float(grouped.loc[key]))}"


def _format_number(value: float) -> str:
    if not math.isfinite(value):
        return "-"
    if math.isclose(value, round(value)):
        return f"{int(round(value)):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _join_non_empty(values: list[Any], sep: str) -> str:
    return sep.join(str(value) for value in values if value not in {None, ""})
