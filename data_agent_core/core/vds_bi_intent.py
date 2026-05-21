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
    metric = _extract_metric_column(question, df)
    entity = _extract_entity_column(question, df)
    if not metric or not entity:
        return None
    current_period, previous_period = _extract_period_pair(question)
    limit = _extract_limit(question, default=10)
    output_format = {"guidelines": guidelines, "answer_type": "table"}

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
    for column in ("人员类型", "患者类型", "客户类型", "项目类别", "科室", "货品类别", "套餐名称", "来源渠道", "预约渠道", "下单渠道", "获客渠道"):
        if column in df.columns:
            values = df[column].dropna().astype(str).unique()
            if any(str(value) in question for value in values):
                return column
    return None


def _extract_filter_value(question: str, df: pd.DataFrame) -> str | None:
    column = _extract_filter_column(question, df)
    if not column:
        return None
    values = sorted((str(value) for value in df[column].dropna().astype(str).unique()), key=len, reverse=True)
    for value in values:
        if value in question:
            return value
    return None
