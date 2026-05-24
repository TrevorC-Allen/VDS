"""Chinese BI intent parsing for VDS desktop test datasets.

The parser recognizes reusable period-comparison patterns across sales,
education, logistics, SaaS, and medical single-table files. It is schema-backed
and does not depend on question ids or standard answers.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm
from data_agent_core.core.logic_form import make_logic_form


PERIOD_COLUMN = "是否本周/上周"


def parse_vds_bi_question(question: str, tables: dict[str, pd.DataFrame], guidelines: str = "") -> LogicForm | None:
    """Parse common Chinese BI period-comparison questions."""

    table_name, df = _select_vds_bi_table(tables)
    if df is None or not table_name:
        return None
    entity = _extract_entity_column(question, df)
    if not entity:
        return None
    current_period, previous_period = _extract_period_pair(question)
    limit = _extract_limit(question, default=10)
    output_format = {"guidelines": guidelines, "answer_type": "table"}
    category_condition = _extract_category_condition(question, df)
    if "占比" in question and category_condition and ("Top" in question or "top" in question or "前" in question or "最高" in question):
        category_column, category_value = category_condition
        return make_logic_form(
            task_type="ranking",
            operation="vds_current_category_share_top",
            parameters={
                "table": table_name,
                "entity": entity,
                "category_column": category_column,
                "category_value": category_value,
                "current_period": current_period,
                "limit": limit,
            },
            output_format=output_format | {"answer_type": "table", "decimals": 2},
        )

    metric = _extract_metric_column(question, df)
    if not metric:
        return None

    if "排名" in question and ("下降" in question or "上升" in question):
        return make_logic_form(
            task_type="ranking",
            operation="vds_period_rank_change",
            parameters={
                "table": table_name,
                "metric": metric,
                "entity": entity,
                "current_period": current_period,
                "previous_period": previous_period,
                "direction": "rise" if "上升" in question else "decline",
                "limit": limit,
            },
            output_format=output_format,
        )

    if "环比增长率" in question and ("Top" in question or "top" in question or "前" in question):
        return make_logic_form(
            task_type="ranking",
            operation="vds_period_rate_top",
            parameters={
                "table": table_name,
                "metric": metric,
                "group_by": _extract_group_column(question, df) or entity,
                "current_period": current_period,
                "previous_period": previous_period,
                "direction": "decrease" if "下降" in question else "increase",
                "limit": limit,
            },
            output_format=output_format,
        )

    if ("增加最多" in question or "增长最多" in question or "减少最多" in question or "下降最多" in question) and "环比增长率" not in question:
        return make_logic_form(
            task_type="ranking",
            operation="vds_period_delta_top",
            parameters={
                "table": table_name,
                "metric": metric,
                "entity": entity,
                "current_period": current_period,
                "previous_period": previous_period,
                "direction": "decrease" if ("减少" in question or "下降" in question) else "increase",
                "limit": limit,
                "filter_column": _extract_filter_column(question, df),
                "filter_value": _extract_filter_value(question, df),
            },
            output_format=output_format,
        )

    if ("低于" in question or "高于" in question) and ("Top" in question or "top" in question or "前" in question):
        return make_logic_form(
            task_type="filtering",
            operation="vds_current_threshold_top",
            parameters={
                "table": table_name,
                "metric": metric,
                "entity": entity,
                "current_period": current_period,
                "operator": "lt" if "低于" in question else "gt",
                "threshold": _extract_percentage_threshold(question, default=0.8),
                "limit": limit,
                "filter_column": _extract_filter_column(question, df),
                "filter_value": _extract_filter_value(question, df),
            },
            output_format=output_format,
        )

    if "平均值" in question and ("高于" in question or "低于" in question):
        return make_logic_form(
            task_type="anomaly_detection",
            operation="vds_peer_anomaly",
            parameters={
                "table": table_name,
                "metric": metric,
                "entity": entity,
                "peer_group": _extract_peer_group_column(question, df),
                "current_period": current_period,
                "operator": "lt" if "低于" in question else "gt",
                "multiplier": _extract_multiplier(question, default=2.0),
            },
            output_format=output_format,
        )

    if _is_current_metric_top_question(question):
        value_filters = _extract_value_filters(question, df, entity=entity, metric=metric)
        sort_order = _current_metric_sort_order(question)
        return make_logic_form(
            task_type="ranking",
            operation="vds_current_filtered_metric_top",
            metric=metric,
            group_by=entity,
            objective="minimize" if sort_order == "asc" else "maximize",
            filters=value_filters,
            parameters={
                "table": table_name,
                "metric": metric,
                "entity": entity,
                "current_period": current_period,
                "value_filters": value_filters,
                "sort_order": sort_order,
                "limit": limit,
            },
            entity_grain={"entity_field": entity},
            time_window={"period_column": PERIOD_COLUMN, "current_period": current_period},
            candidate_set={"filters": value_filters, "limit": limit},
            output_format=output_format
            | {
                "answer_type": "table",
                "entity_field": entity,
                "metric": metric,
            },
            output_contract={
                "primary_entity_field": entity,
                "metric": metric,
                "sort_order": sort_order,
            },
        )

    if "较上周增长" in question and ("数量" in question or "占比" in question):
        return make_logic_form(
            task_type="aggregation",
            operation="vds_period_growth_count_share",
            parameters={
                "table": table_name,
                "metric": metric,
                "entity": entity,
                "current_period": current_period,
                "previous_period": previous_period,
            },
            output_format={"guidelines": guidelines, "answer_type": "text"},
        )

    if "环比" in question and "超过" in question and ("有多少" in question or "多少家" in question):
        return make_logic_form(
            task_type="aggregation",
            operation="vds_period_threshold_count",
            parameters={
                "table": table_name,
                "metric": metric,
                "entity": entity,
                "current_period": current_period,
                "previous_period": previous_period,
                "direction": "decrease" if "下降" in question else "increase",
                "threshold": _extract_percentage_threshold(question, default=0.1),
            },
            output_format={"guidelines": guidelines, "answer_type": "number", "decimals": 0},
        )

    return None


def _select_vds_bi_table(tables: dict[str, pd.DataFrame]) -> tuple[str | None, pd.DataFrame | None]:
    for name, df in tables.items():
        columns = {str(column) for column in df.columns}
        if PERIOD_COLUMN in columns and any(str(column).endswith("_row") for column in df.columns):
            return name, df
    return None, None


def _extract_metric_column(question: str, df: pd.DataFrame) -> str | None:
    metric_codes = sorted((str(column)[:-4] for column in df.columns if str(column).endswith("_row")), key=len, reverse=True)
    upper_question = question.upper()
    for code in metric_codes:
        if re.search(rf"(?<![A-Z0-9]){re.escape(code.upper())}(?![A-Z0-9])", upper_question):
            return f"{code}_row"
    return None


def _extract_entity_column(question: str, df: pd.DataFrame) -> str | None:
    candidates = (
        ("门店", "门店名称"),
        ("校区", "校区名称"),
        ("院区", "院区名称"),
        ("站点", "站点名称"),
        ("客户", "客户名称"),
    )
    for token, column in candidates:
        if token in question and column in df.columns:
            return column
    for column in df.columns:
        name = str(column)
        if name.endswith("名称") and name in question:
            return name
    for fallback in ("门店名称", "校区名称", "院区名称", "站点名称", "客户名称"):
        if fallback in df.columns:
            return fallback
    return None


def _extract_period_pair(question: str) -> tuple[str, str]:
    if "上周" in question and "上上周" in question and "本周" not in question:
        return "上周", "上上周"
    return "本周", "上周"


def _extract_limit(question: str, default: int) -> int:
    match = re.search(r"(?:Top|top|前)\s*(\d+)", question)
    if match:
        return int(match.group(1))
    return default


def _extract_percentage_threshold(question: str, default: float) -> float:
    match = re.search(r"(?:超过|低于|高于)\s*(\d+(?:\.\d+)?)\s*%", question)
    if not match:
        return default
    return float(match.group(1)) / 100


def _extract_multiplier(question: str, default: float) -> float:
    match = re.search(r"平均值\s*(\d+(?:\.\d+)?)\s*倍", question)
    return float(match.group(1)) if match else default


def _is_current_metric_top_question(question: str) -> bool:
    top_language = ("Top", "top", "前", "最高", "最大", "最低", "最小", "影响最大", "影响最小")
    if not any(token in question for token in top_language):
        return False
    comparison_language = ("与上周相比", "较上周", "环比", "排名下降", "排名上升", "增加最多", "增长最多", "减少最多", "下降最多")
    if any(token in question for token in comparison_language):
        return False
    if "占比" in question or "平均值" in question:
        return False
    return True


def _current_metric_sort_order(question: str) -> str:
    return "asc" if any(token in question for token in ("最低", "最小", "影响最小")) else "desc"


def _extract_group_column(question: str, df: pd.DataFrame) -> str | None:
    for token, column in (
        ("城市", "城市"),
        ("区域", "区域"),
        ("商圈", "商圈"),
        ("学区", "学区"),
        ("医疗圈", "医疗圈"),
        ("配送圈", "配送圈"),
        ("行业", "行业分层"),
        ("来源渠道", "来源渠道"),
        ("预约渠道", "预约渠道"),
        ("下单渠道", "下单渠道"),
        ("获客渠道", "获客渠道"),
        ("支付方式", "支付方式"),
        ("付费方式", "付费方式"),
        ("配送方式", "配送方式"),
    ):
        if token in question and column in df.columns:
            return column
    return None


def _extract_peer_group_column(question: str, df: pd.DataFrame) -> str:
    explicit = _extract_group_column(question, df)
    if explicit:
        return explicit
    if "商圈" in df.columns:
        return "商圈"
    return _fallback_peer_group(df)


def _fallback_peer_group(df: pd.DataFrame) -> str:
    for column in ("学区", "医疗圈", "配送圈", "行业分层", "商圈", "区域", "城市"):
        if column in df.columns:
            return column
    return str(df.columns[0])


def _extract_filter_column(question: str, df: pd.DataFrame) -> str | None:
    filters = _extract_value_filters(question, df, entity=None, metric=None)
    if filters:
        return next(iter(filters))
    return None


def _extract_filter_value(question: str, df: pd.DataFrame) -> str | None:
    column = _extract_filter_column(question, df)
    if not column:
        return None
    filters = _extract_value_filters(question, df, entity=None, metric=None)
    value = filters.get(column)
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None


def _extract_category_condition(question: str, df: pd.DataFrame) -> tuple[str, str] | None:
    for column in ("状态", "人员类型", "患者类型", "客户类型", "项目类别", "科室", "货品类别", "套餐名称"):
        if column not in df.columns:
            continue
        values = sorted((str(value) for value in df[column].dropna().unique()), key=len, reverse=True)
        for value in values:
            if value and value in question:
                return column, value
    return None


def _extract_value_filters(question: str, df: pd.DataFrame, *, entity: str | None, metric: str | None) -> dict[str, list[str]]:
    excluded = {PERIOD_COLUMN}
    if entity:
        excluded.add(entity)
    if metric:
        excluded.add(metric)
    filters: dict[str, list[str]] = {}
    for column in _candidate_filter_columns(df, excluded):
        values = _matching_filter_values(question, df, column)
        if values:
            filters[column] = values
    return filters


def _candidate_filter_columns(df: pd.DataFrame, excluded: set[str]) -> list[str]:
    priority = (
        "状态",
        "订阅状态",
        "人员类型",
        "患者类型",
        "客户类型",
        "项目类别",
        "科室",
        "货品类别",
        "套餐名称",
        "产品线",
        "业务类型",
        "来源渠道",
        "预约渠道",
        "下单渠道",
        "获客渠道",
        "支付方式",
        "付费方式",
        "配送方式",
        "行业分层",
        "实施复杂度",
        "区域",
        "城市",
        "商圈",
        "学区",
        "医疗圈",
        "配送圈",
    )
    ordered: list[str] = []
    for column in priority:
        if column in df.columns and column not in excluded:
            ordered.append(column)
    for column in df.columns:
        name = str(column)
        if name in excluded or name in ordered or pd.api.types.is_numeric_dtype(df[column]):
            continue
        if len(df[column].dropna().astype(str).unique()) <= 80:
            ordered.append(name)
    return ordered


def _matching_filter_values(question: str, df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns:
        return []
    values = [str(value) for value in df[column].dropna().astype(str).unique() if str(value)]
    if len(values) > 80:
        return []
    matches: list[str] = []
    for value in sorted(values, key=len, reverse=True):
        if _filter_value_in_question(value, question, column):
            matches.append(value)
    if _looks_status_column(column):
        for status_value in _status_values_from_question(question, values):
            if status_value not in matches:
                matches.append(status_value)
    return matches


def _filter_value_in_question(value: str, question: str, column: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", value):
        if len(value.strip()) == 1:
            return _single_char_value_in_question(value.strip(), question, column)
        return value in question
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", question, flags=re.I))


def _single_char_value_in_question(value: str, question: str, column: str) -> bool:
    escaped_value = re.escape(value)
    escaped_column = re.escape(column)
    if re.search(rf"{escaped_column}\s*(?:为|是|=|等于)?\s*{escaped_value}", question):
        return True
    if re.search(rf"{escaped_value}\s*(?:的)?\s*{escaped_column}", question):
        return True
    if "复杂度" in column and re.search(rf"(?:复杂度\s*(?:为|是|=|等于)?\s*{escaped_value}|{escaped_value}\s*复杂度)", question):
        return True
    return False


def _looks_status_column(column: str) -> bool:
    return "状态" in column or column in {"是否流失", "是否暂停"}


def _status_values_from_question(question: str, known_values: list[str]) -> list[str]:
    tokens = ("流失", "暂停", "已退课", "退课", "取消", "关闭")
    values: list[str] = []
    for token in tokens:
        if token not in question:
            continue
        canonical = next((value for value in known_values if token in value or value in token), token)
        if canonical not in values:
            values.append(canonical)
    return values
