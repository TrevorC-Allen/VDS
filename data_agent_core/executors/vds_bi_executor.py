"""Executor helpers for VDS Chinese BI period-comparison operations."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm


VDS_BI_OPERATIONS = {
    "vds_period_rank_change",
    "vds_period_delta_top",
    "vds_period_growth_count_share",
    "vds_period_threshold_count",
    "vds_period_rate_top",
    "vds_current_threshold_top",
    "vds_current_category_share_top",
    "vds_current_filtered_metric_top",
    "vds_peer_anomaly",
}

MEAN_METRICS = {
    "AT",
    "UPT",
    "USD",
    "CR",
    "LHR",
    "AST",
    "QS",
    "HW",
    "AWT",
    "ASP",
    "RCR",
    "RSI",
    "OTD",
    "CPP",
    "DPR",
    "ADR",
    "ARPA",
    "CHR",
    "NRR",
}


def is_vds_bi_operation(operation: str) -> bool:
    """Return whether an operation belongs to VDS BI period comparison."""

    return operation in VDS_BI_OPERATIONS


def execute_vds_bi_operation(logic: LogicForm, context: dict[str, Any]) -> Any:
    """Execute a VDS BI operation against uploaded tables."""

    tables = context["tables"]
    params = logic.parameters
    df = tables[str(params["table"])]
    op = logic.operation
    if op == "vds_period_rank_change":
        return _period_rank_change(df, params)
    if op == "vds_period_delta_top":
        return _period_delta_top(df, params)
    if op == "vds_period_growth_count_share":
        return _period_growth_count_share(df, params)
    if op == "vds_period_threshold_count":
        return _period_threshold_count(df, params)
    if op == "vds_period_rate_top":
        return _period_rate_top(df, params)
    if op == "vds_current_threshold_top":
        return _current_threshold_top(df, params)
    if op == "vds_current_category_share_top":
        return _current_category_share_top(df, params)
    if op == "vds_current_filtered_metric_top":
        return _current_filtered_metric_top(df, params)
    if op == "vds_peer_anomaly":
        return _peer_anomaly(df, params)
    raise ValueError(f"Unsupported VDS BI operation: {op}")


def _period_rank_change(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    current, previous = _period_values(df, params)
    merged = _merged_period_frame(current, previous)
    if merged.empty:
        return []
    descending = True
    merged["current_rank"] = merged["current_value"].rank(method="min", ascending=not descending)
    merged["previous_rank"] = merged["previous_value"].rank(method="min", ascending=not descending)
    merged["rank_change"] = merged["current_rank"] - merged["previous_rank"]
    direction = str(params.get("direction") or "decline")
    ascending = direction == "rise"
    ranked = merged.sort_values(["rank_change", "current_value"], ascending=[ascending, False]).head(int(params.get("limit") or 10))
    return _records(ranked, params["entity"], ["current_rank", "previous_rank", "rank_change", "current_value", "previous_value"])


def _period_delta_top(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    df = _apply_optional_value_filter(df, params)
    current, previous = _period_values(df, params)
    merged = _with_delta(_merged_period_frame(current, previous))
    if merged.empty:
        return []
    direction = str(params.get("direction") or "increase")
    ranked = merged.sort_values("delta", ascending=direction == "decrease").head(int(params.get("limit") or 10))
    return _records(ranked, params["entity"], ["current_value", "previous_value", "delta", "delta_rate"])


def _period_growth_count_share(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    current, previous = _period_values(df, params)
    merged = _with_delta(_merged_period_frame(current, previous))
    if merged.empty or "delta" not in merged.columns:
        return {"answer": "0, 0.00%", "count": 0, "share": 0.0, "total": 0}
    total = len(merged)
    count = int((merged["delta"] > 0).sum())
    share = 0.0 if total == 0 else count / total * 100
    return {"answer": f"{count}, {share:.2f}%", "count": count, "share": share, "total": total}


def _period_threshold_count(df: pd.DataFrame, params: dict[str, Any]) -> int:
    current, previous = _period_values(df, params)
    merged = _with_delta(_merged_period_frame(current, previous))
    if merged.empty or "delta_rate" not in merged.columns:
        return 0
    threshold = float(params.get("threshold") or 0.1)
    if str(params.get("direction") or "increase") == "decrease":
        return int((merged["delta_rate"] < -threshold).sum())
    return int((merged["delta_rate"] > threshold).sum())


def _period_rate_top(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    group_by = str(params.get("group_by") or params.get("entity"))
    adjusted = dict(params)
    adjusted["entity"] = group_by
    current, previous = _period_values(df, adjusted)
    merged = _with_delta(_merged_period_frame(current, previous))
    if merged.empty or "delta_rate" not in merged.columns:
        return []
    direction = str(params.get("direction") or "increase")
    ranked = merged.sort_values("delta_rate", ascending=direction == "decrease").head(int(params.get("limit") or 10))
    return _records(ranked, group_by, ["current_value", "previous_value", "delta", "delta_rate"])


def _current_threshold_top(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    data = _apply_optional_value_filter(df, params)
    current_period = str(params.get("current_period") or "本周")
    data = data[data["是否本周/上周"].astype(str) == current_period]
    entity = str(params["entity"])
    metric = str(params["metric"])
    if data.empty:
        return []
    values = _aggregate_current(data, entity, metric)
    threshold = float(params.get("threshold") or 0.0)
    if str(params.get("operator") or "lt") == "gt":
        selected = values[values > threshold].sort_values(ascending=False)
    else:
        selected = values[values < threshold].sort_values(ascending=True)
    selected = selected.head(int(params.get("limit") or 10))
    return [{entity: index, metric: float(value)} for index, value in selected.items()]


def _current_category_share_top(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    data = df[df["是否本周/上周"].astype(str) == str(params.get("current_period") or "本周")]
    entity = str(params["entity"])
    category_column = str(params["category_column"])
    category_value = str(params["category_value"])
    if data.empty or entity not in data.columns or category_column not in data.columns:
        return []
    total = data.groupby(entity, dropna=True).size()
    matched = data[data[category_column].astype(str) == category_value].groupby(entity, dropna=True).size()
    result = pd.DataFrame({"total_count": total, "category_count": matched}).fillna(0)
    if result.empty:
        return []
    result["share"] = result.apply(lambda row: 0.0 if float(row["total_count"]) == 0.0 else float(row["category_count"]) / float(row["total_count"]) * 100, axis=1)
    result = result.sort_values(["share", "category_count", "total_count"], ascending=[False, False, False]).head(int(params.get("limit") or 10))
    return [
        {
            entity: index,
            category_column: category_value,
            "category_count": int(row["category_count"]),
            "total_count": int(row["total_count"]),
            "share": float(row["share"]),
        }
        for index, row in result.iterrows()
    ]


def _current_filtered_metric_top(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    current_period = str(params.get("current_period") or "本周")
    data = df[df["是否本周/上周"].astype(str) == current_period]
    data = _apply_value_filters(data, params.get("value_filters") or {})
    entity = str(params["entity"])
    metric = str(params["metric"])
    if data.empty or entity not in data.columns or metric not in data.columns:
        return []
    values = _aggregate_current(data, entity, metric)
    if values.empty:
        return []
    ascending = str(params.get("sort_order") or "desc") == "asc"
    selected = values.sort_values(ascending=ascending).head(int(params.get("limit") or 10))
    return [{entity: index, metric: _native_number(value)} for index, value in selected.items()]


def _peer_anomaly(df: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
    current_period = str(params.get("current_period") or "本周")
    data = df[df["是否本周/上周"].astype(str) == current_period]
    entity = str(params["entity"])
    metric = str(params["metric"])
    peer_group = str(params.get("peer_group") or "")
    if data.empty or peer_group not in data.columns:
        return []
    grouped = (
        data.groupby([peer_group, entity], dropna=True)[metric].mean()
        if _metric_code(metric) in MEAN_METRICS
        else data.groupby([peer_group, entity], dropna=True)[metric].sum()
    ).reset_index(name="entity_value")
    grouped["peer_sum"] = grouped.groupby(peer_group)["entity_value"].transform("sum")
    grouped["peer_count"] = grouped.groupby(peer_group)["entity_value"].transform("count")
    grouped["peer_average"] = grouped.apply(
        lambda row: row["entity_value"]
        if int(row["peer_count"]) <= 1
        else (float(row["peer_sum"]) - float(row["entity_value"])) / (int(row["peer_count"]) - 1),
        axis=1,
    )
    multiplier = float(params.get("multiplier") or 2.0)
    if str(params.get("operator") or "gt") == "lt":
        selected = grouped[grouped["entity_value"] < grouped["peer_average"] * multiplier]
        selected = selected.sort_values("entity_value", ascending=True)
    else:
        selected = grouped[grouped["entity_value"] > grouped["peer_average"] * multiplier]
        selected = selected.sort_values("entity_value", ascending=False)
    return [
        {
            entity: row[entity],
            peer_group: row[peer_group],
            "current_value": float(row["entity_value"]),
            "peer_average": float(row["peer_average"]),
        }
        for _, row in selected.iterrows()
    ]


def _period_values(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    entity = str(params["entity"])
    metric = str(params["metric"])
    current_period = str(params.get("current_period") or "本周")
    previous_period = str(params.get("previous_period") or "上周")
    return (
        _aggregate_period(df, entity, metric, current_period),
        _aggregate_period(df, entity, metric, previous_period),
    )


def _aggregate_period(df: pd.DataFrame, entity: str, metric: str, period: str) -> pd.Series:
    data = df[df["是否本周/上周"].astype(str) == period]
    if data.empty:
        return pd.Series(dtype=float)
    values = pd.to_numeric(data[metric], errors="coerce")
    grouped = values.groupby(data[entity]).mean() if _metric_code(metric) in MEAN_METRICS else values.groupby(data[entity]).sum()
    return grouped.dropna()


def _aggregate_current(data: pd.DataFrame, entity: str, metric: str) -> pd.Series:
    values = pd.to_numeric(data[metric], errors="coerce")
    grouped = values.groupby(data[entity]).mean() if _metric_code(metric) in MEAN_METRICS else values.groupby(data[entity]).sum()
    return grouped.dropna()


def _merged_period_frame(current: pd.Series, previous: pd.Series) -> pd.DataFrame:
    merged = pd.DataFrame({"current_value": current, "previous_value": previous}).fillna(0.0)
    merged.index.name = "entity"
    return merged.reset_index()


def _with_delta(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data
    data = data.copy()
    data["delta"] = data["current_value"] - data["previous_value"]
    data["delta_rate"] = data.apply(
        lambda row: 0.0 if float(row["previous_value"]) == 0.0 else float(row["delta"]) / float(row["previous_value"]),
        axis=1,
    )
    return data


def _records(data: pd.DataFrame, entity_column: str, value_columns: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, row in data.iterrows():
        item: dict[str, Any] = {entity_column: row["entity"]}
        for column in value_columns:
            value = row[column]
            item[column] = int(value) if isinstance(value, float) and value.is_integer() and "rank" in column else float(value)
        out.append(item)
    return out


def _metric_code(metric: str) -> str:
    return metric[:-4] if metric.endswith("_row") else metric


def _apply_optional_value_filter(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("filter_column")
    value = params.get("filter_value")
    if not column or not value or str(column) not in df.columns:
        return df
    return _apply_value_filters(df, {str(column): value})


def _apply_value_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    data = df
    for column, value in filters.items():
        column_name = str(column)
        if column_name not in data.columns:
            continue
        if isinstance(value, (list, tuple, set)):
            candidates = {str(item) for item in value if str(item)}
            if candidates:
                data = data[data[column_name].astype(str).isin(candidates)]
        elif value:
            data = data[data[column_name].astype(str) == str(value)]
    return data


def _native_number(value: Any) -> int | float:
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric
